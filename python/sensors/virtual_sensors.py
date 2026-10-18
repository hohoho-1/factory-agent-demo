"""
KMPC 스타일 미니 라인 가상 센서 시뮬레이터.

설비별로 1초(기본)마다 텔레메트리를 MQTT로 발행한다.
  topic   : factory/line1/{equipmentId}/telemetry
  payload : {"equipmentId", "type", "ts", "metrics": {name: value}, "units": {name: unit}}

정상 구간은 목표값 주변 랜덤워크로 움직이고, --anomaly 옵션이나
--anomaly-rate 확률로 이상 시나리오(과열, 진동 급증 등)를 주입한다.
"""
import argparse
import json
import random
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

TOPIC_PREFIX = "factory/line1"


@dataclass
class Metric:
    name: str
    unit: str
    target: float          # 정상 운전 목표값
    noise: float           # 1틱당 랜덤워크 폭
    lo: float              # 물리적 하한
    hi: float              # 물리적 상한
    value: float = 0.0
    drift: float = 0.0     # 이상 주입 시 1틱당 추가 변화량

    def __post_init__(self):
        self.value = self.target

    def step(self):
        # 목표값으로 되돌아가려는 힘 + 노이즈 + 이상 드리프트
        pull = (self.target - self.value) * 0.1 if self.drift == 0 else 0.0
        self.value += pull + random.uniform(-self.noise, self.noise) + self.drift
        self.value = max(self.lo, min(self.hi, self.value))
        return round(self.value, 2)


@dataclass
class Equipment:
    equipment_id: str
    type: str
    metrics: dict[str, Metric] = field(default_factory=dict)

    def read(self):
        return {name: m.step() for name, m in self.metrics.items()}


def build_line():
    def m(*args):
        return Metric(*args)

    return [
        Equipment("TANK-01", "RAW_TANK", {
            "level": m("level", "%", 70.0, 0.5, 0.0, 100.0),
            "temperature": m("temperature", "C", 25.0, 0.2, 0.0, 120.0),
        }),
        Equipment("TANK-02", "RAW_TANK", {
            "level": m("level", "%", 65.0, 0.5, 0.0, 100.0),
            "temperature": m("temperature", "C", 40.0, 0.2, 0.0, 120.0),
        }),
        Equipment("MIXER-01", "MIXER", {
            "vibration": m("vibration", "mm/s", 2.5, 0.15, 0.0, 30.0),
            "current": m("current", "A", 12.0, 0.3, 0.0, 50.0),
        }),
        Equipment("FILLER-01", "FILLER", {
            "speed": m("speed", "bpm", 120.0, 2.0, 0.0, 200.0),
        }),
    ]


# 이상 시나리오: (설비, 지표, 1틱당 드리프트, 지속 틱 수)
SCENARIOS = {
    "tank_overheat": ("TANK-02", "temperature", +1.5, 20),
    "tank_low_level": ("TANK-01", "level", -3.0, 20),
    "mixer_vibration": ("MIXER-01", "vibration", +0.8, 15),
    "mixer_overcurrent": ("MIXER-01", "current", +1.2, 15),
    "filler_slowdown": ("FILLER-01", "speed", -5.0, 15),
}


class AnomalyInjector:
    def __init__(self, line):
        self.by_id = {e.equipment_id: e for e in line}
        self.active = None  # (scenario, metric, 남은 틱)

    def start(self, name):
        if self.active:
            return
        eq_id, metric_name, drift, ticks = SCENARIOS[name]
        metric = self.by_id[eq_id].metrics[metric_name]
        metric.drift = drift
        self.active = (name, metric, ticks)
        print(f"[ANOMALY] start {name}: {eq_id}.{metric_name} drift={drift}/tick x{ticks}")

    def tick(self):
        if not self.active:
            return
        name, metric, left = self.active
        if left <= 1:
            metric.drift = 0.0  # 이후 목표값으로 서서히 복귀
            self.active = None
            print(f"[ANOMALY] end {name}")
        else:
            self.active = (name, metric, left - 1)


def parse_args():
    p = argparse.ArgumentParser(description="Virtual sensor MQTT publisher")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--interval", type=float, default=1.0, help="발행 주기(초)")
    p.add_argument("--anomaly", choices=SCENARIOS.keys(), help="시작 직후 주입할 이상 시나리오")
    p.add_argument("--anomaly-rate", type=float, default=0.0,
                   help="틱마다 랜덤 이상이 시작될 확률 (예: 0.01)")
    p.add_argument("--count", type=int, default=0, help="발행 틱 수 (0이면 무한)")
    return p.parse_args()


def main():
    args = parse_args()
    line = build_line()
    injector = AnomalyInjector(line)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="virtual-sensors")
    client.connect(args.host, args.port, keepalive=30)
    client.loop_start()
    print(f"connected to mqtt://{args.host}:{args.port}, publishing every {args.interval}s")

    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)

    if args.anomaly:
        injector.start(args.anomaly)

    tick = 0
    while running and (args.count == 0 or tick < args.count):
        if args.anomaly_rate and not injector.active and random.random() < args.anomaly_rate:
            injector.start(random.choice(list(SCENARIOS)))

        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        for eq in line:
            payload = {
                "equipmentId": eq.equipment_id,
                "type": eq.type,
                "ts": ts,
                "metrics": eq.read(),
                "units": {n: m.unit for n, m in eq.metrics.items()},
            }
            topic = f"{TOPIC_PREFIX}/{eq.equipment_id}/telemetry"
            client.publish(topic, json.dumps(payload), qos=0)

        injector.tick()
        tick += 1
        time.sleep(args.interval)

    client.loop_stop()
    client.disconnect()
    print("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
