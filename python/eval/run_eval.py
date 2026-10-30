"""
알람 지시서 평가 (정답셋: eval/alarm_eval_set.json).

실행 (python 폴더에서):
  .venv\\Scripts\\python -m eval.run_eval              # 템플릿 생성기, API 비용 없음
  .venv\\Scripts\\python -m eval.run_eval --llm        # Claude 생성기 (python/.env 의 키 사용, 문항당 API 호출 1번)

재는 것
- 매뉴얼 선택 정확도: 지시서의 주 매뉴얼이 정답 매뉴얼인가 (매뉴얼이 있는 문항)
- 검색 Recall@k: 정답 섹션이 검색 상위 k 안에 들어왔는가
- LOTO 포함률: 잠금·표지가 필요한 문항에서 지시서가 그 안내를 담았는가
- 범위 밖 처리: 다룰 매뉴얼이 없는 알람에 '매뉴얼 없음'으로 답했는가
- 매뉴얼 가드: 검색 1위 매뉴얼의 설비·지표·방향이 알람과 다르면 '매뉴얼 없음'으로 돌리는 규칙(Manual.covers)이
  범위 밖 문항을 몇 개 잡고, 정상 문항을 몇 개 잘못 막는가
  (2026-10-30 첫 측정은 가드 없이 범위 밖 0/5 → 가드를 넣고 재측정. results/ 의 두 파일 비교)
- (--llm) 근거 번호 검증 통과율, 문항당 소요 시간

결과는 화면과 eval/results/<날짜>-<생성기>.md 에 남는다.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from agent.rag import Manual, ManualIndex, load_manuals
from agent.work_order import TemplateGenerator, build_query

EVAL_DIR = Path(__file__).parent
SET_FILE = EVAL_DIR / "alarm_eval_set.json"
RESULT_DIR = EVAL_DIR / "results"
K = 6  # 생성기와 같은 검색 개수


def to_alarm(case: dict) -> dict:
    return {
        "id": 0, "equipmentId": case["equipmentId"], "equipmentType": case["equipmentType"],
        "metric": case["metric"], "unit": case.get("unit", ""), "severity": case["severity"],
        "direction": case["direction"], "thresholdValue": case["threshold"], "triggerValue": case["value"],
        "peakValue": case["value"], "lastValue": case["value"], "raisedAt": "2026-10-30T05:00:00Z",
        "batchPhase": case.get("batchPhase"), "batchId": "B-EVAL-01" if case.get("batchPhase") else None,
    }


def metadata_matches(manual: Manual | None, alarm: dict) -> bool:
    """검색 1위 매뉴얼이 이 알람(설비 유형·지표·방향)을 다루는 매뉴얼인가."""
    return manual is not None and manual.covers(alarm["equipmentType"], alarm["metric"], alarm["direction"])


def has_loto(body: str) -> bool:
    return "LOTO" in body or "잠금·표지" in body


def evaluate(case: dict, index: ManualIndex, generator) -> dict:
    alarm = to_alarm(case)
    hits = index.search(build_query(alarm), alarm["equipmentType"], alarm["metric"], k=K)
    chosen = index.best_manual(hits)
    expected = case["expectedManual"]
    found = {(h.chunk.manual.id, h.chunk.section) for h in hits}

    row = {
        "id": case["id"], "case": case, "chosen": chosen.id if chosen else None,
        "topScore": hits[0].score if hits else 0.0,
        "guardPass": metadata_matches(chosen, alarm),
        "recallHit": sum((expected, s) in found for s in case["expectedSections"]),
        "recallTotal": len(case["expectedSections"]),
    }

    started = time.perf_counter()
    try:
        wo = generator.generate(alarm, index)
        row["error"] = None
    except Exception as e:  # noqa: BLE001 - 실패도 결과로 센다
        wo = None
        row["error"] = f"{type(e).__name__}: {e}"
    row["seconds"] = time.perf_counter() - started
    body = wo["body"] if wo else ""
    row["cited"] = next((m for m in index.manuals if f"근거 매뉴얼: {m} " in body), None)
    row["loto"] = has_loto(body)
    row["manualOk"] = row["cited"] == expected if expected else None
    return row


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.0%})" if d else "-"


def summarize(rows: list[dict], generator_name: str) -> list[str]:
    covered = [r for r in rows if r["case"]["expectedManual"]]
    outside = [r for r in rows if not r["case"]["expectedManual"]]
    loto_cases = [r for r in covered if r["case"]["expectLoto"]]
    ok_rows = [r for r in rows if not r["error"]]

    lines = [
        f"# 알람 지시서 평가 결과 — {generator_name}",
        "",
        f"- 실행: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 정답셋: alarm_eval_set.json (매뉴얼 있음 {len(covered)}문항 + 매뉴얼 없음 {len(outside)}문항)",
        "",
        "## 지표",
        "",
        "| 지표 | 결과 |",
        "|---|---|",
        f"| 매뉴얼 선택 정확도 | {pct(sum(bool(r['manualOk']) for r in covered), len(covered))} |",
        f"| 검색 Recall@{K} (정답 섹션) | {pct(sum(r['recallHit'] for r in covered), sum(r['recallTotal'] for r in covered))} |",
        f"| LOTO 포함률 (필요 문항) | {pct(sum(r['loto'] for r in loto_cases), len(loto_cases))} |",
        f"| 범위 밖 알람을 '매뉴얼 없음'으로 처리 | {pct(sum(r['cited'] is None and r['error'] is None for r in outside), len(outside))} |",
        f"| 지시서 생성 성공 (오류·근거 검증 실패 없음) | {pct(len(ok_rows), len(rows))} |",
        f"| 문항당 평균 소요 | {sum(r['seconds'] for r in rows) / len(rows):.2f}초 |",
        "",
        "## 매뉴얼 가드 판정",
        "",
        "규칙: 검색 1위 매뉴얼의 설비 유형·지표·방향이 알람과 다르면 지시서 대신 '매뉴얼 없음, 담당자 확인'으로 돌린다.",
        "",
        f"- 범위 밖 알람을 잡음: {pct(sum(not r['guardPass'] for r in outside), len(outside))}",
        f"- 정상 알람을 잘못 막음: {pct(sum(not r['guardPass'] for r in covered), len(covered))}",
        "",
        "## 문항별",
        "",
        "| 번호 | 알람 | 정답 매뉴얼 | 지시서 근거 | Recall | LOTO | 가드 | 비고 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        c = r["case"]
        alarm = f"{c['equipmentId']} {c['metric']} {c['direction']} {c['severity']}"
        expected = c["expectedManual"] or "(없음)"
        mark = "" if r["manualOk"] in (True, None) else " ✗"
        if not c["expectedManual"]:
            mark = " ✗ 엉뚱한 근거" if r["cited"] else " ✓"
        recall = f"{r['recallHit']}/{r['recallTotal']}" if r["recallTotal"] else "-"
        loto = ("✓" if r["loto"] else "✗") if c["expectLoto"] else "-"
        guard = "통과" if r["guardPass"] else "막음"
        note = r["error"] or c["note"]
        lines.append(f"| {r['id']} | {alarm} | {expected} | {r['cited'] or '-'}{mark} | {recall} | {loto} | {guard} | {note} |")
    return lines


def make_generator(use_llm: bool):
    if not use_llm:
        return TemplateGenerator()
    from agent.agent import load_env_file
    from agent.llm import LlmGenerator
    load_env_file()
    return LlmGenerator()  # 폴백 없이: 근거 검증 실패도 실패로 센다


def main() -> None:
    parser = argparse.ArgumentParser(description="알람 지시서 평가")
    parser.add_argument("--llm", action="store_true", help="Claude 생성기로 평가 (API 비용 발생)")
    parser.add_argument("--only", help="쉼표로 구분한 문항 번호만 (예: C02,N02)")
    args = parser.parse_args()

    eval_set = json.loads(SET_FILE.read_text(encoding="utf-8"))
    cases = eval_set["cases"]
    if args.only:
        wanted = {s.strip() for s in args.only.split(",")}
        cases = [c for c in cases if c["id"] in wanted]

    index = ManualIndex(load_manuals())
    generator = make_generator(args.llm)
    name = f"llm ({generator.model})" if args.llm else "template"

    rows = []
    for case in cases:
        row = evaluate(case, index, generator)
        print(f"{row['id']}: 근거 {row['cited'] or '-'} (정답 {case['expectedManual'] or '없음'})"
              f"{' 오류: ' + row['error'] if row['error'] else ''}")
        rows.append(row)

    report = "\n".join(summarize(rows, name)) + "\n"
    RESULT_DIR.mkdir(exist_ok=True)
    out = RESULT_DIR / f"{datetime.now():%Y%m%d-%H%M}-{'llm' if args.llm else 'template'}.md"
    out.write_text(report, encoding="utf-8")
    print()
    print(report)
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
