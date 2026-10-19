"""
엣지 게이트웨이: PLC(OPC UA) 태그를 구독해 기존과 같은 MQTT 텔레메트리로 올리고,
위(백엔드)에서 내려온 설정값 명령을 OPC UA 쓰기로 PLC 에 전달한다.

  OPC UA → MQTT  factory/line1/{설비ID}/telemetry
                 {"equipmentId","type","ts","metrics":{...},"units":{...}}   (가상 센서와 같은 형식)
  MQTT → OPC UA  factory/line1/commands          {"requestId","equipmentId","tag","value"}
  결과 보고      factory/line1/commands/results  {"requestId","equipmentId","tag","requested","status",
                                                   "code","message","before","after","ts"}
                 status: APPLIED(반영) / INTERLOCKED(PLC 인터록 거부) / FAILED(통신 오류 등)

태그 목록은 설정 파일 없이 PLC 주소 공간(Objects/Line1/{설비}/{태그})을 browse 해서 찾는다.
PLC 가 아직 안 떠 있거나 끊기면 몇 초 뒤 다시 붙는다.

실행 (python 폴더에서):
  python -m plc.edge_gateway
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from asyncua import Client, Node, ua

from .virtual_plc import INTERLOCK_TAG, LINE, NAMESPACE_URI

TOPIC_PREFIX = "factory/line1"
COMMAND_TOPIC = f"{TOPIC_PREFIX}/commands"
RESULT_TOPIC = f"{TOPIC_PREFIX}/commands/results"
DEFAULT_URL = "opc.tcp://localhost:4840/factory/line1/"
RETRY_SECONDS = 3.0


@dataclass
class Tag:
    equipment_id: str
    name: str
    unit: str
    role: str  # PV / SP
    node: Node


@dataclass
class Equipment:
    equipment_id: str
    type: str
    tags: dict[str, Tag] = field(default_factory=dict)
    interlock: Node | None = None


def _iso(ts: datetime | None) -> str:
    ts = ts or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def parse_command(payload: bytes) -> dict:
    """명령 메시지를 검사한다. 형식이 틀리면 ValueError."""
    cmd = json.loads(payload.decode("utf-8"))
    if not isinstance(cmd, dict):
        raise ValueError("command must be a JSON object")
    for key in ("equipmentId", "tag", "value"):
        if cmd.get(key) is None:
            raise ValueError(f"missing '{key}'")
    cmd["value"] = float(cmd["value"])
    return cmd


def build_telemetry(eq: Equipment, values: dict[str, float], ts: datetime | None) -> dict:
    return {
        "equipmentId": eq.equipment_id,
        "type": eq.type,
        "ts": _iso(ts),
        "metrics": {name: round(values[name], 2) for name in eq.tags if name in values},
        "units": {name: tag.unit for name, tag in eq.tags.items()},
    }


async def browse_line(client: Client) -> dict[str, Equipment]:
    """Objects/Line1 아래 설비와 태그를 찾는다."""
    idx = await client.get_namespace_index(NAMESPACE_URI)
    line = await client.nodes.objects.get_child([f"{idx}:{LINE}"])
    equipment: dict[str, Equipment] = {}
    for obj in await line.get_children(nodeclassmask=ua.NodeClass.Object):
        eq_id = (await obj.read_browse_name()).Name
        props = {(await p.read_browse_name()).Name: await p.read_value() for p in await obj.get_properties()}
        eq = Equipment(eq_id, props.get("EquipmentType", "UNKNOWN"))
        for var in await obj.get_variables():
            name = (await var.read_browse_name()).Name
            if name == INTERLOCK_TAG:
                eq.interlock = var
                continue
            meta = {(await p.read_browse_name()).Name: await p.read_value() for p in await var.get_properties()}
            eq.tags[name] = Tag(eq_id, name, meta.get("Unit", ""), meta.get("Role", "PV"), var)
        equipment[eq_id] = eq
    return equipment


class _Collector:
    """OPC UA 구독 콜백: 최신값과 현장 시각을 모아 둔다."""

    def __init__(self, by_node: dict[ua.NodeId, Tag]):
        self.by_node = by_node
        self.values: dict[tuple[str, str], float] = {}
        self.stamps: dict[str, datetime] = {}

    def datachange_notification(self, node: Node, val, data) -> None:
        tag = self.by_node.get(node.nodeid)
        if tag is None or val is None:
            return
        self.values[(tag.equipment_id, tag.name)] = float(val)
        ts = data.monitored_item.Value.SourceTimestamp
        if ts is not None:
            self.stamps[tag.equipment_id] = ts


async def write_setpoint(eq: Equipment | None, cmd: dict) -> dict:
    """설정값 1건을 OPC UA 로 쓰고 결과 메시지를 만든다. PLC 가 거부하면 인터록 사유를 함께 읽는다."""
    result = {
        "requestId": cmd.get("requestId"),
        "equipmentId": cmd["equipmentId"],
        "tag": cmd["tag"],
        "requested": cmd["value"],
        "before": None,
        "after": None,
        "code": "Good",
        "message": "",
    }
    tag = eq.tags.get(cmd["tag"]) if eq else None
    if tag is None or tag.role != "SP":
        result.update(status="INTERLOCKED", code="BadNotWritable",
                      message=f"{cmd['equipmentId']}.{cmd['tag']} 는 쓰기 가능한 설정값 태그가 아닙니다")
        return _stamp(result)
    try:
        result["before"] = await tag.node.read_value()
        await tag.node.write_value(ua.DataValue(ua.Variant(cmd["value"], ua.VariantType.Double)))
        result["after"] = await tag.node.read_value()
        result["status"] = "APPLIED"
        result["message"] = "PLC 설정값 반영"
    except ua.UaStatusCodeError as e:
        result["code"] = ua.StatusCode(e.code).name
        result["after"] = await tag.node.read_value()
        reason = ""
        if eq.interlock is not None:
            await asyncio.sleep(0.05)  # PLC 가 사유 태그를 쓰는 동안 잠깐 기다린다
            reason = await eq.interlock.read_value()
        result["status"] = "INTERLOCKED"
        result["message"] = reason.split(" ", 1)[-1] if reason else f"PLC 가 쓰기를 거부했습니다 ({result['code']})"
    return _stamp(result)


def _stamp(result: dict) -> dict:
    result["ts"] = _iso(None)
    return result


class EdgeGateway:
    def __init__(self, url: str, mqtt_host: str, mqtt_port: int, interval: float):
        self.url = url
        self.interval = interval
        self.commands: asyncio.Queue = asyncio.Queue()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="edge-gateway")
        self.mqtt.on_connect = self._on_connect
        self.mqtt.on_message = self._on_message
        self.mqtt_host, self.mqtt_port = mqtt_host, mqtt_port

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        client.subscribe(COMMAND_TOPIC, qos=1)

    def _on_message(self, client, userdata, msg):
        try:
            cmd = parse_command(msg.payload)
        except (ValueError, TypeError) as e:
            print(f"[GATEWAY] invalid command: {e!r}", file=sys.stderr, flush=True)
            return
        self.loop.call_soon_threadsafe(self.commands.put_nowait, cmd)

    def publish(self, topic: str, payload: dict, qos: int = 0) -> None:
        self.mqtt.publish(topic, json.dumps(payload, ensure_ascii=False), qos=qos)

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.mqtt.connect(self.mqtt_host, self.mqtt_port, keepalive=30)
        self.mqtt.loop_start()
        print(f"edge gateway: {self.url} -> mqtt://{self.mqtt_host}:{self.mqtt_port},"
              f" commands on {COMMAND_TOPIC}", flush=True)
        try:
            while True:
                try:
                    await self._session()
                except Exception as e:  # noqa: BLE001 - PLC 재시작·통신 끊김 등 무엇이든 다시 붙는다
                    print(f"[GATEWAY] PLC connection lost or unavailable ({e!r}), retry in {RETRY_SECONDS}s",
                          flush=True)
                await asyncio.sleep(RETRY_SECONDS)
        finally:
            self.mqtt.loop_stop()
            self.mqtt.disconnect()

    async def _session(self) -> None:
        async with Client(self.url, timeout=5) as client:
            equipment = await browse_line(client)
            by_node = {t.node.nodeid: t for eq in equipment.values() for t in eq.tags.values()}
            collector = _Collector(by_node)
            sub = await client.create_subscription(int(self.interval * 500), collector)
            await sub.subscribe_data_change([t.node for t in by_node.values()])
            print(f"[GATEWAY] connected: {len(equipment)} equipment, {len(by_node)} tags subscribed"
                  f" ({sum(t.role == 'SP' for t in by_node.values())} writable setpoints)", flush=True)
            # 텔레메트리는 주기적으로, 명령은 들어오는 즉시. 한쪽이 실패하면 세션을 닫고 다시 붙는다
            await asyncio.gather(self._publish_loop(client, equipment, collector), self._command_loop(equipment))

    async def _publish_loop(self, client: Client, equipment: dict[str, Equipment], collector: _Collector) -> None:
        while True:
            for eq in equipment.values():
                values = {name: v for (eq_id, name), v in collector.values.items() if eq_id == eq.equipment_id}
                if values:
                    self.publish(f"{TOPIC_PREFIX}/{eq.equipment_id}/telemetry",
                                 build_telemetry(eq, values, collector.stamps.get(eq.equipment_id)))
            await client.check_connection()
            await asyncio.sleep(self.interval)

    async def _command_loop(self, equipment: dict[str, Equipment]) -> None:
        while True:
            cmd = await self.commands.get()
            result = await write_setpoint(equipment.get(cmd["equipmentId"]), cmd)
            print(f"[GATEWAY] command #{result['requestId']} {result['equipmentId']}.{result['tag']}"
                  f" <- {result['requested']}: {result['status']} {result['code']} {result['message']}", flush=True)
            self.publish(RESULT_TOPIC, result, qos=1)


def main() -> int:
    p = argparse.ArgumentParser(description="Edge gateway: OPC UA -> MQTT telemetry, MQTT commands -> OPC UA writes")
    p.add_argument("--url", default=DEFAULT_URL, help="PLC OPC UA 엔드포인트")
    p.add_argument("--mqtt-host", default="localhost")
    p.add_argument("--mqtt-port", type=int, default=1883)
    p.add_argument("--interval", type=float, default=1.0, help="MQTT 발행 주기(초)")
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("asyncua").setLevel(logging.ERROR)  # 보안 정책 없음 경고 등은 데모에서 생략
    try:
        asyncio.run(EdgeGateway(args.url, args.mqtt_host, args.mqtt_port, args.interval).run())
    except KeyboardInterrupt:
        print("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
