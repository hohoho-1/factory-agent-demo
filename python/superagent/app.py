"""
SuperAgent 서비스 (경영 질문 → 여러 시스템 조회 → 답).

실행 (python 폴더에서):  .venv\\Scripts\\python -m superagent.app   → http://localhost:8095/command/...
대시보드 'ERP · 경영' 화면의 SuperAgent 패널이 /command 로 부른다 (Vite 프록시).
질문 · 답 · 실행 기록은 logs/superagent.jsonl 에 남는다 (git 제외). 키가 없으면 503.
"""
from __future__ import annotations

import json
import os
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .agent import SuperAgent, SuperAgentError

LOG = Path(__file__).resolve().parents[2] / "logs" / "superagent.jsonl"
app = FastAPI(title="SuperAgent (NEXA Command 역할)", docs_url="/command/docs", openapi_url="/command/openapi.json")
_history: deque = deque(maxlen=10)
_lock = threading.Lock()
_agent: SuperAgent | None = None


def agent() -> SuperAgent:
    global _agent
    if _agent is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise HTTPException(503, "ANTHROPIC_API_KEY 가 없어 SuperAgent 를 쓸 수 없습니다 (python/.env)")
        _agent = SuperAgent()
    return _agent


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=500)


@app.get("/command/health")
def health() -> dict:
    return {"status": "ok", "llm": bool(os.environ.get("ANTHROPIC_API_KEY"))}


@app.get("/command/history")
def history() -> list[dict]:
    return list(_history)


@app.post("/command/ask")
def ask(q: Question) -> dict:
    """질문 하나. 도구를 여러 번 부르므로 수십 초 걸릴 수 있다. 한 번에 하나씩만 처리한다."""
    if not _lock.acquire(blocking=False):
        raise HTTPException(409, "다른 질문을 처리하는 중입니다. 잠시 뒤 다시 물어보세요")
    try:
        result = agent().ask(q.question.strip()).to_dict()
    except SuperAgentError as e:
        raise HTTPException(502, str(e)) from e
    except Exception as e:  # noqa: BLE001 - API 키 · 네트워크 · 크레딧 오류를 화면에 그대로 알린다
        raise HTTPException(502, f"SuperAgent 오류: {type(e).__name__}: {e}") from e
    finally:
        _lock.release()
    result["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _history.appendleft(result)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return result


def main() -> None:
    from agent.agent import load_env_file
    load_env_file()
    uvicorn.run(app, host="127.0.0.1", port=8095, log_level="info")


if __name__ == "__main__":
    main()
