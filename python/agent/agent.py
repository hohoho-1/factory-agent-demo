"""
AI 조치 에이전트.

factory/line1/alarms 를 구독하다가 알람이 발생(RAISED)하거나 심각도가 올라가면(ESCALATED)
설비 매뉴얼을 검색해 조치 지시서를 만들고 백엔드에 저장한다.

실행 (python 폴더에서):
  python -m agent.agent                       # MQTT 구독 모드
  python -m agent.agent --search "배합기 진동"  # 매뉴얼 검색만 해 보기
  python -m agent.agent --alarm-id 3 --dry-run # 기존 알람으로 지시서 미리보기
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

import paho.mqtt.client as mqtt

from .rag import ManualIndex, load_manuals
from .work_order import TemplateGenerator

HANDLED_EVENTS = {"RAISED", "ESCALATED"}


class Backend:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def get_alarm(self, alarm_id: int) -> dict:
        with urllib.request.urlopen(f"{self.base_url}/api/alarms/{alarm_id}", timeout=5) as r:
            return json.load(r)

    def save_work_order(self, alarm_id: int, work_order: dict) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}/api/alarms/{alarm_id}/work-orders",
            data=json.dumps(work_order, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.load(r)


class Agent:
    def __init__(self, index: ManualIndex, backend: Backend, dry_run: bool = False):
        self.index = index
        self.backend = backend
        self.generator = TemplateGenerator()
        self.dry_run = dry_run

    def handle(self, alarm: dict, event: str) -> None:
        wo = self.generator.generate(alarm, self.index)
        top = wo["references"][0]
        print(f"[AGENT] {event} alarm #{alarm['id']} {alarm['message']}")
        print(f"        -> {top['manualId']} / {top['section']} (score {top['score']})")
        if self.dry_run:
            print(wo["body"])
            return
        saved = self.backend.save_work_order(alarm["id"], wo)
        print(f"        -> work order #{saved['id']} saved: {saved['title']}")


def run_mqtt(agent: Agent, host: str, port: int, topic: str) -> None:
    def on_connect(client, userdata, flags, reason_code, properties):
        print(f"connected to mqtt://{host}:{port} ({reason_code}), subscribing {topic}")
        client.subscribe(topic, qos=1)

    def on_message(client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode("utf-8"))
            if data.get("event") in HANDLED_EVENTS:
                agent.handle(data["alarm"], data["event"])
        except (urllib.error.URLError, KeyError, ValueError, RuntimeError) as e:
            # 메시지 하나 처리 실패로 에이전트가 멈추지 않게 한다
            print(f"[AGENT] failed to handle message: {e!r}", file=sys.stderr)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="factory-ai-agent")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(host, port, keepalive=30)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        client.disconnect()
        print("stopped")


def main() -> int:
    p = argparse.ArgumentParser(description="Factory AI work-order agent")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--topic", default="factory/line1/alarms")
    p.add_argument("--api", default="http://localhost:8080", help="백엔드 주소")
    p.add_argument("--search", help="매뉴얼 검색만 수행할 질의")
    p.add_argument("--alarm-id", type=int, help="기존 알람 1건에 대해 지시서 작성")
    p.add_argument("--dry-run", action="store_true", help="저장하지 않고 지시서 본문만 출력")
    args = p.parse_args()

    manuals = load_manuals()
    index = ManualIndex(manuals)
    print(f"loaded {len(manuals)} manuals, {len(index.chunks)} chunks")

    if args.search:
        for h in index.search(args.search, k=5):
            print(f"{h.score:.3f}  {h.chunk.manual.id} / {h.chunk.section}")
        return 0

    agent = Agent(index, Backend(args.api), dry_run=args.dry_run)
    if args.alarm_id:
        agent.handle(agent.backend.get_alarm(args.alarm_id), "MANUAL")
        return 0

    run_mqtt(agent, args.host, args.port, args.topic)
    return 0


if __name__ == "__main__":
    sys.exit(main())
