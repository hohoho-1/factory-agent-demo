"""
AI 조치 에이전트.

factory/line1/alarms 를 구독하다가 알람이 발생(RAISED)하거나 심각도가 올라가면(ESCALATED)
설비 매뉴얼을 검색해 조치 지시서를 만들고 백엔드에 저장한다.

실행 (python 폴더에서):
  python -m agent.agent                       # MQTT 구독 모드
  python -m agent.agent --search "배합기 진동"  # 매뉴얼 검색만 해 보기
  python -m agent.agent --alarm-id 3 --dry-run # 기존 알람으로 지시서 미리보기
  python -m agent.agent --generator template   # 키가 있어도 템플릿만

지시서 생성기: python/.env(또는 환경변수)에 ANTHROPIC_API_KEY 가 있으면 Claude(LLM), 없으면 매뉴얼 템플릿.
LLM 이 실패하거나 근거 검증을 통과하지 못하면 그 건은 템플릿으로 쓴다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import paho.mqtt.client as mqtt

from .handover import HandoverWriter
from .rag import ManualIndex, load_manuals
from .work_order import TemplateGenerator

HANDLED_EVENTS = {"RAISED", "ESCALATED"}
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"  # python/.env (git 제외)


def load_env_file(path: Path = ENV_FILE) -> None:
    """python/.env 의 KEY=VALUE 를 환경변수로 읽는다. 이미 설정된 환경변수가 우선."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def make_generator(kind: str):
    """auto: 키가 있으면 LLM(실패 시 템플릿), 없으면 템플릿."""
    if kind == "template" or (kind == "auto" and not os.environ.get("ANTHROPIC_API_KEY")):
        return TemplateGenerator()
    from .llm import FallbackGenerator, LlmGenerator
    return FallbackGenerator(LlmGenerator())


class Backend:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def get_alarm(self, alarm_id: int) -> dict:
        with urllib.request.urlopen(f"{self.base_url}/api/alarms/{alarm_id}", timeout=5) as r:
            return json.load(r)

    def get_history(self, alarm: dict) -> list[dict]:
        """작업자가 조치를 마친 과거 지시서: 같은 설비·지표 먼저, 이어서 같은 유형 다른 설비 (각각 최근 완료 순)."""
        query = urllib.parse.urlencode({
            "equipmentId": alarm["equipmentId"],
            "metric": alarm["metric"],
            "excludeAlarmId": alarm["id"],
            "equipmentType": alarm["equipmentType"],
        })
        with urllib.request.urlopen(f"{self.base_url}/api/work-orders/history?{query}", timeout=5) as r:
            return json.load(r)

    def save_work_order(self, alarm_id: int, work_order: dict) -> dict:
        return self._post(f"/api/alarms/{alarm_id}/work-orders", work_order)

    def get_handover_context(self, report_id: int) -> dict:
        with urllib.request.urlopen(f"{self.base_url}/api/handover-reports/{report_id}/context", timeout=5) as r:
            return json.load(r)

    def save_handover(self, report_id: int, report: dict) -> dict:
        return self._post(f"/api/handover-reports/{report_id}/result", report)

    def _post(self, path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.load(r)


class Agent:
    def __init__(self, index: ManualIndex, backend: Backend, dry_run: bool = False, generator=None):
        self.index = index
        self.backend = backend
        self.generator = generator or TemplateGenerator()
        self.dry_run = dry_run
        # 인수인계 리포트도 지시서와 같은 LLM 설정을 쓴다 (키가 없으면 템플릿)
        self.handover = HandoverWriter(getattr(self.generator, "primary", None))

    def handle_handover(self, report_id: int) -> None:
        ctx = self.backend.get_handover_context(report_id)
        report = self.handover.write(ctx)
        print(f"[AGENT] handover #{report_id}: {len(ctx.get('alarms') or [])} alarms,"
              f" {len(ctx.get('workOrders') or [])} work orders, generator {report['generator']}")
        if self.dry_run:
            print(report["body"])
            return
        self.backend.save_handover(report_id, report)
        print(f"        -> handover #{report_id} saved: {report['title']}")

    def handle(self, alarm: dict, event: str) -> None:
        history = self._history(alarm)
        wo = self.generator.generate(alarm, self.index, history)
        # 어느 심각도 기준으로 썼는지 함께 보낸다 (LLM 이 쓰는 동안 알람이 위험으로 올라갈 수 있다)
        wo["severity"] = alarm["severity"]
        top = wo["references"][0]
        print(f"[AGENT] {event} alarm #{alarm['id']} {alarm['message']}")
        print(f"        -> {top['manualId']} / {top['section']} (score {top['score']}), generator {wo['generator']}")
        if history:
            print(f"        -> past actions: {len(history)} (latest WO-{history[0]['id']})")
        if self.dry_run:
            print(wo["body"])
            return
        saved = self.backend.save_work_order(alarm["id"], wo)
        print(f"        -> work order #{saved['id']} saved: {saved['title']}")

    def _history(self, alarm: dict) -> list[dict]:
        # 이력 조회가 안 돼도 매뉴얼 기반 지시서는 써야 한다
        try:
            return self.backend.get_history(alarm)
        except (urllib.error.URLError, ValueError) as e:
            print(f"[AGENT] history lookup failed, continuing without it: {e!r}", file=sys.stderr)
            return []


def run_mqtt(agent: Agent, host: str, port: int, topic: str, handover_topic: str) -> None:
    def on_connect(client, userdata, flags, reason_code, properties):
        print(f"connected to mqtt://{host}:{port} ({reason_code}), subscribing {topic}, {handover_topic}")
        client.subscribe([(topic, 1), (handover_topic, 1)])

    # LLM 지시서는 수십 초 걸린다. 알람마다 작업 스레드에서 처리해 경고·위험 지시서를 나란히 만들고,
    # MQTT 수신 루프(keepalive 포함)는 막지 않는다.
    workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="work-order")

    def handle_safely(alarm: dict, event: str) -> None:
        try:
            agent.handle(alarm, event)
        except (urllib.error.URLError, KeyError, ValueError, RuntimeError) as e:
            # 알람 하나 처리 실패로 에이전트가 멈추지 않게 한다
            print(f"[AGENT] failed to handle alarm #{alarm.get('id')}: {e!r}", file=sys.stderr)

    def handover_safely(report_id: int) -> None:
        try:
            agent.handle_handover(report_id)
        except (urllib.error.URLError, KeyError, ValueError, RuntimeError) as e:
            print(f"[AGENT] failed to write handover #{report_id}: {e!r}", file=sys.stderr)

    def on_message(client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except ValueError as e:
            print(f"[AGENT] invalid message: {e!r}", file=sys.stderr)
            return
        if msg.topic == handover_topic and "reportId" in data:
            workers.submit(handover_safely, data["reportId"])
        elif data.get("event") in HANDLED_EVENTS and "alarm" in data:
            workers.submit(handle_safely, data["alarm"], data["event"])

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="factory-ai-agent")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(host, port, keepalive=30)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        client.disconnect()
        print("stopped")
    finally:
        workers.shutdown(wait=False, cancel_futures=True)


def main() -> int:
    p = argparse.ArgumentParser(description="Factory AI work-order agent")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--topic", default="factory/line1/alarms")
    p.add_argument("--handover-topic", default="factory/line1/handover/requests")
    p.add_argument("--api", default="http://localhost:8080", help="백엔드 주소")
    p.add_argument("--search", help="매뉴얼 검색만 수행할 질의")
    p.add_argument("--alarm-id", type=int, help="기존 알람 1건에 대해 지시서 작성")
    p.add_argument("--handover-id", type=int, help="기존 인수인계 리포트 요청 1건을 작성")
    p.add_argument("--dry-run", action="store_true", help="저장하지 않고 지시서 본문만 출력")
    p.add_argument("--generator", choices=["auto", "template", "llm"], default="auto",
                   help="auto: ANTHROPIC_API_KEY 가 있으면 LLM(실패 시 템플릿), 없으면 템플릿")
    args = p.parse_args()
    load_env_file()

    manuals = load_manuals()
    index = ManualIndex(manuals)
    print(f"loaded {len(manuals)} manuals, {len(index.chunks)} chunks")

    if args.search:
        for h in index.search(args.search, k=5):
            print(f"{h.score:.3f}  {h.chunk.manual.id} / {h.chunk.section}")
        return 0

    generator = make_generator(args.generator)
    print(f"work order generator: {generator.name}"
          + (f" ({generator.primary.model}, effort {generator.primary.effort})" if generator.name == "llm" else ""))
    agent = Agent(index, Backend(args.api), dry_run=args.dry_run, generator=generator)
    if args.alarm_id:
        agent.handle(agent.backend.get_alarm(args.alarm_id), "MANUAL")
        return 0
    if args.handover_id:
        agent.handle_handover(args.handover_id)
        return 0

    run_mqtt(agent, args.host, args.port, args.topic, args.handover_topic)
    return 0


if __name__ == "__main__":
    sys.exit(main())
