"""
오케스트레이터 라우터 평가.

실행 (python 폴더에서):
  .venv\\Scripts\\python -m eval.run_router_eval

정답: alarm_eval_set.json(20문항)의 expectedRoute + router_eval_set.json(헷갈리기 쉬운 8문항).
비교: 규칙 라우터(매뉴얼 범위 확인 + 지표·배치 단계) vs 지표만 보는 단순 라우터.
API 호출 없음. 결과는 화면과 eval/results/<날짜>-router.md 에 남는다.

주의: 정답과 규칙을 같은 사람이 정했으므로 정확도 100% 는 '규칙이 의도대로 동작한다'는 뜻이지
일반화 성능이 아니다. 실제 공장 알람 이력으로 정답셋을 다시 만들어야 의미 있는 수치가 된다.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime

from agent.orchestrator import BATCH, EQUIPMENT, HANDOFF, PROCESS, ROUTE_KO, classify, classify_naive
from agent.rag import ManualIndex, load_manuals

from .run_eval import EVAL_DIR, RESULT_DIR, SET_FILE, to_alarm

EXTRA_FILE = EVAL_DIR / "router_eval_set.json"
ROUTES = [EQUIPMENT, BATCH, PROCESS, HANDOFF]


def load_cases() -> list[dict]:
    base = json.loads(SET_FILE.read_text(encoding="utf-8"))["cases"]
    extra = json.loads(EXTRA_FILE.read_text(encoding="utf-8"))["cases"]
    return base + extra


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.0%})" if d else "-"


def per_route(rows: list[dict], key: str) -> list[str]:
    lines = []
    for r in ROUTES:
        expected = [x for x in rows if x["expected"] == r]
        predicted = [x for x in rows if x[key] == r]
        tp = sum(x[key] == r for x in expected)
        lines.append(f"| {ROUTE_KO[r]} ({r}) | {len(expected)} | {pct(tp, len(predicted))} | {pct(tp, len(expected))} |")
    return lines


def main() -> None:
    index = ManualIndex(load_manuals())
    rows = []
    for case in load_cases():
        alarm = to_alarm(case)
        route = classify(alarm, index)
        rows.append({"case": case, "expected": case["expectedRoute"], "rule": route.kind,
                     "reason": route.reason, "naive": classify_naive(alarm)})

    n = len(rows)
    rule_ok = sum(r["rule"] == r["expected"] for r in rows)
    naive_ok = sum(r["naive"] == r["expected"] for r in rows)
    confusion = Counter((r["expected"], r["rule"]) for r in rows)

    lines = [
        "# 알람 라우터 평가 결과",
        "",
        f"- 실행: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 문항: {n} (alarm_eval_set.json 20 + router_eval_set.json {n - 20})",
        "- 정답과 규칙을 같은 사람이 정했으므로, 이 정확도는 일반화 성능이 아니라 규칙이 의도대로 동작하는지 확인한 값이다.",
        "",
        "## 정확도",
        "",
        "| 라우터 | 정확도 |",
        "|---|---|",
        f"| 규칙 라우터 (매뉴얼 범위 확인 + 지표·배치 단계) | {pct(rule_ok, n)} |",
        f"| 단순 라우터 (지표만, 매뉴얼 확인 없음) | {pct(naive_ok, n)} |",
        "",
        "## 경로별 (규칙 라우터)",
        "",
        "| 경로 | 문항 | 정밀도 | 재현율 |",
        "|---|---|---|---|",
        *per_route(rows, "rule"),
        "",
        "## 경로별 (단순 라우터)",
        "",
        "| 경로 | 문항 | 정밀도 | 재현율 |",
        "|---|---|---|---|",
        *per_route(rows, "naive"),
        "",
        "## 혼동 행렬 (규칙 라우터, 행=정답 / 열=예측)",
        "",
        "| 정답 \\ 예측 | " + " | ".join(ROUTES) + " |",
        "|---|" + "---|" * len(ROUTES),
        *[f"| {e} | " + " | ".join(str(confusion[(e, p)]) for p in ROUTES) + " |" for e in ROUTES],
        "",
        "## 문항별",
        "",
        "| 번호 | 알람 | 정답 | 규칙 | 단순 | 규칙 라우터 판단 이유 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        c = r["case"]
        alarm = f"{c['equipmentId']} {c['metric']} {c['direction']} {c['severity']}" + (
            f" ({c['batchPhase']})" if c.get("batchPhase") else "")
        mark = lambda k: r[k] + ("" if r[k] == r["expected"] else " ✗")  # noqa: E731
        lines.append(f"| {c['id']} | {alarm} | {r['expected']} | {mark('rule')} | {mark('naive')} | {r['reason']} |")

    report = "\n".join(lines) + "\n"
    RESULT_DIR.mkdir(exist_ok=True)
    out = RESULT_DIR / f"{datetime.now():%Y%m%d-%H%M}-router.md"
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
