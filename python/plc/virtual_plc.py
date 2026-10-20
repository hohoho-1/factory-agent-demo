"""
가상 PLC: 미니 라인의 태그를 OPC UA 서버로 노출한다.

  endpoint : opc.tcp://localhost:4840/factory/line1/
  namespace: urn:factory-agent-demo:line1 (보통 ns=2)
  주소 공간 : Objects / Line1 / {설비ID} / {태그}
              예) ns=2;s=Line1.MIXER-01.vibration   (공정값 PV, 읽기 전용)
                  ns=2;s=Line1.MIXER-01.speed_sp    (설정값 SP, 쓰기 가능 · 인터록 검사)
                  ns=2;s=Line1.MIXER-01.LastInterlock (마지막 인터록 거부 사유)
                  ns=2;s=Line1.MIXER-01.batchPhase  (배치 단계, 문자열 상태 태그. batchId · recipe 도 같은 방식)
  설비 객체에는 EquipmentType, 태그에는 Unit · Role(PV/SP/STATE) 속성(property)이 붙는다.

1초(기본)마다 PLC 스캔을 돌려 태그 값을 갱신한다. 설정값 쓰기는 process.LineProcess 의 인터록을 통과해야
반영되고, 거부되면 OPC UA 상태 코드(BadOutOfRange / BadInvalidState)로 응답한다.

이상 시나리오 주입은 기존 가상 센서와 같은 MQTT 토픽(factory/line1/sim/anomaly)으로 받는다 (데모 조작용).

실행 (python 폴더에서):
  python -m plc.virtual_plc
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from asyncua import Server, ua

from sensors.virtual_sensors import CONTROL_TOPIC, SCENARIOS

from .process import BATCH_START, PLC_RAMP_SCENARIOS, PLC_SCENARIOS, SETPOINT_TAGS, InterlockError, LineProcess

NAMESPACE_URI = "urn:factory-agent-demo:line1"
DEFAULT_ENDPOINT = "opc.tcp://0.0.0.0:4840/factory/line1/"
LINE = "Line1"
INTERLOCK_TAG = "LastInterlock"


def node_id(idx: int, *parts: str) -> ua.NodeId:
    return ua.NodeId(".".join((LINE, *parts)), idx)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _double(value: float) -> ua.DataValue:
    return ua.DataValue(ua.Variant(float(value), ua.VariantType.Double), SourceTimestamp=_now(), ServerTimestamp=_now())


class VirtualPlc:
    def __init__(self, process: LineProcess | None = None, endpoint: str = DEFAULT_ENDPOINT):
        self.process = process or LineProcess()
        self.endpoint = endpoint
        self.server = Server()
        self.idx = 0
        self.values: dict[tuple[str, str], ua.NodeId] = {}
        self.interlock_nodes: dict[str, ua.NodeId] = {}
        self.state_nodes: dict[tuple[str, str], ua.NodeId] = {}
        self._last_states: dict[tuple[str, str], str] = {}
        self._local_write = False  # PLC 스캔이 SP 노드를 갱신할 때는 인터록을 거치지 않는다

    async def start(self) -> None:
        await self.server.init()
        self.server.set_endpoint(self.endpoint)
        self.server.set_server_name("Factory Agent Demo - Line1 Virtual PLC")
        self.server.set_security_policy([ua.SecurityPolicyType.NoSecurity])  # 데모용. 실제 현장은 서명·암호화 필수
        self.idx = await self.server.register_namespace(NAMESPACE_URI)
        await self._build_address_space()
        await self.server.start()

    async def stop(self) -> None:
        await self.server.stop()

    async def _build_address_space(self) -> None:
        idx = self.idx
        line = await self.server.nodes.objects.add_object(node_id(idx), ua.QualifiedName(LINE, idx))
        first = self.process.scan()
        for eq in self.process.line:
            eq_id = eq.equipment_id
            obj = await line.add_object(node_id(idx, eq_id), ua.QualifiedName(eq_id, idx))
            await obj.add_property(node_id(idx, eq_id, "EquipmentType"), ua.QualifiedName("EquipmentType", idx), eq.type)
            for metric, unit in self.process.units(eq_id).items():
                is_sp = (eq_id, metric) in SETPOINT_TAGS
                var = await obj.add_variable(node_id(idx, eq_id, metric), ua.QualifiedName(metric, idx),
                                             ua.Variant(float(first[eq_id][metric]), ua.VariantType.Double))
                await var.add_property(node_id(idx, eq_id, metric, "Unit"), ua.QualifiedName("Unit", idx), unit)
                await var.add_property(node_id(idx, eq_id, metric, "Role"), ua.QualifiedName("Role", idx),
                                       "SP" if is_sp else "PV")
                if is_sp:
                    await var.set_writable()
                    self.server.set_attribute_value_setter(var.nodeid, self._setter(eq_id, metric))
                self.values[(eq_id, metric)] = var.nodeid
            for name, text in self.process.states().get(eq_id, {}).items():
                var = await obj.add_variable(node_id(idx, eq_id, name), ua.QualifiedName(name, idx),
                                             ua.Variant(text, ua.VariantType.String))
                await var.add_property(node_id(idx, eq_id, name, "Role"), ua.QualifiedName("Role", idx), "STATE")
                self.state_nodes[(eq_id, name)] = var.nodeid
            if any(eq == eq_id for eq, _ in SETPOINT_TAGS):
                lock = await obj.add_variable(node_id(idx, eq_id, INTERLOCK_TAG), ua.QualifiedName(INTERLOCK_TAG, idx),
                                              ua.Variant("", ua.VariantType.String))
                self.interlock_nodes[eq_id] = lock.nodeid

    def _setter(self, eq_id: str, tag: str):
        """SP 노드 쓰기 가로채기: 인터록을 통과한 값만 저장한다. 거부하면 상태 코드 예외로 응답한다."""

        def setter(node_data, attr, value: ua.DataValue) -> None:
            if not self._local_write:
                try:
                    requested = float(value.Value.Value)
                except (TypeError, ValueError, AttributeError):
                    raise ua.UaStatusCodeError(ua.StatusCodes.BadTypeMismatch) from None
                try:
                    previous = self.process.write_setpoint(eq_id, tag, requested)
                except InterlockError as e:
                    print(f"[INTERLOCK] {eq_id}.{tag} <- {requested} rejected: {e.code} {e.message}", flush=True)
                    # 게이트웨이가 바로 이어서 사유를 읽어 간다
                    asyncio.get_running_loop().create_task(self._write_interlock(eq_id, e.message))
                    raise ua.UaStatusCodeError(getattr(ua.StatusCodes, e.code)) from None
                print(f"[PLC] {eq_id}.{tag} {previous} -> {requested}", flush=True)
                value = _double(requested)
            node_data.attributes[attr].value = value

        return setter

    async def _write_interlock(self, eq_id: str, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        await self.server.write_attribute_value(self.interlock_nodes[eq_id],
                                                ua.DataValue(ua.Variant(f"{stamp} {message}", ua.VariantType.String)))

    async def scan_once(self) -> None:
        values = self.process.scan()
        self._local_write = True
        try:
            for (eq_id, metric), nid in self.values.items():
                await self.server.write_attribute_value(nid, _double(values[eq_id][metric]))
            for eq_id, states in self.process.states().items():
                for name, text in states.items():
                    key = (eq_id, name)
                    if key in self.state_nodes and self._last_states.get(key) != text:
                        self._last_states[key] = text
                        await self.server.write_attribute_value(self.state_nodes[key], ua.DataValue(
                            ua.Variant(text, ua.VariantType.String), SourceTimestamp=_now(), ServerTimestamp=_now()))
        finally:
            self._local_write = False

    async def run(self, interval: float, anomalies: asyncio.Queue | None = None) -> None:
        while True:
            while anomalies is not None and not anomalies.empty():
                name = anomalies.get_nowait()
                if not self.process.inject(name):
                    print(f"[ANOMALY] unknown scenario '{name}',"
                          f" choose one of {[BATCH_START, *SCENARIOS, *PLC_SCENARIOS, *PLC_RAMP_SCENARIOS]}",
                          flush=True)
            await self.scan_once()
            await asyncio.sleep(interval)


def start_anomaly_listener(host: str, port: int, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
    """MQTT 로 들어오는 시나리오 이름을 asyncio 큐로 넘긴다 (paho 는 자기 스레드에서 콜백을 부른다)."""

    def on_connect(client, userdata, flags, reason_code, properties):
        client.subscribe(CONTROL_TOPIC, qos=1)

    def on_message(client, userdata, msg):
        name = msg.payload.decode("utf-8").strip()
        if name == "random":
            name = random.choice(list(SCENARIOS))
        loop.call_soon_threadsafe(queue.put_nowait, name)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="virtual-plc-sim")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(host, port, keepalive=30)
    client.loop_start()
    return client


async def main_async(args) -> None:
    plc = VirtualPlc(endpoint=args.endpoint)
    await plc.start()
    print(f"virtual PLC listening on {args.endpoint} (namespace {NAMESPACE_URI} = ns={plc.idx}),"
          f" scan every {args.interval}s", flush=True)
    queue: asyncio.Queue = asyncio.Queue()
    client = start_anomaly_listener(args.mqtt_host, args.mqtt_port, asyncio.get_running_loop(), queue)
    print(f"anomaly injection: mqtt://{args.mqtt_host}:{args.mqtt_port} {CONTROL_TOPIC}", flush=True)
    try:
        await plc.run(args.interval, queue)
    finally:
        client.loop_stop()
        client.disconnect()
        await plc.stop()


def main() -> int:
    p = argparse.ArgumentParser(description="Virtual PLC (OPC UA server)")
    p.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    p.add_argument("--interval", type=float, default=1.0, help="PLC 스캔(태그 갱신) 주기(초)")
    p.add_argument("--mqtt-host", default="localhost")
    p.add_argument("--mqtt-port", type=int, default=1883)
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("asyncua").setLevel(logging.ERROR)
    logging.getLogger("asyncua.server.uaprocessor").setLevel(logging.CRITICAL)  # 인터록 거부는 [INTERLOCK] 로 직접 남긴다
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
