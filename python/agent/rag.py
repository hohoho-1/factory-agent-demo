"""
설비 매뉴얼 검색 (RAG의 Retrieval 부분).

- manuals/*.md 를 읽어 '## 섹션' 단위로 청크를 만든다.
- 청크를 TF-IDF(문자 2~4gram) 벡터로 만들어 메모리에 둔다. 한국어는 형태소 분석 없이도
  문자 n-gram 으로 '진동', '과전류' 같은 용어가 잘 잡힌다. 모델 다운로드가 필요 없어 가볍다.
- 검색 점수 = 코사인 유사도 + 메타데이터 가점(설비 유형·지표 일치).

나중에 임베딩 모델 + pgvector 로 바꿀 때는 ManualIndex.search 만 교체하면 된다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

MANUAL_DIR = Path(__file__).parent / "manuals"

EQUIPMENT_BOOST = 0.15
METRIC_BOOST = 0.15


@dataclass
class Manual:
    id: str
    title: str
    equipment_type: str
    metrics: list[str]
    direction: str
    sections: dict[str, str] = field(default_factory=dict)  # 섹션 제목 -> 본문 (문서 순서 유지)
    path: Path | None = None


@dataclass
class Chunk:
    manual: Manual
    section: str
    text: str


@dataclass
class Hit:
    chunk: Chunk
    score: float


def parse_manual(text: str, path: Path | None = None) -> Manual:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"front matter 가 없습니다: {path}")
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()

    sections: dict[str, str] = {}
    current = None
    for line in m.group(2).splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = ""
        elif current is not None:
            sections[current] += line + "\n"

    return Manual(
        id=meta["id"],
        title=meta.get("title", meta["id"]),
        equipment_type=meta.get("equipment_type", "ALL"),
        metrics=[s.strip() for s in meta.get("metrics", "").split(",") if s.strip()],
        direction=meta.get("direction", ""),
        sections={k: v.strip() for k, v in sections.items()},
        path=path,
    )


def load_manuals(directory: Path = MANUAL_DIR) -> list[Manual]:
    return [parse_manual(p.read_text(encoding="utf-8"), p) for p in sorted(directory.glob("*.md"))]


class ManualIndex:
    def __init__(self, manuals: list[Manual]):
        self.manuals = {m.id: m for m in manuals}
        self.chunks = [
            Chunk(m, section, f"{m.title} - {section}\n{body}")
            for m in manuals
            for section, body in m.sections.items()
        ]
        self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
        self.matrix = self.vectorizer.fit_transform([c.text for c in self.chunks])

    def search(self, query: str, equipment_type: str | None = None, metric: str | None = None,
               k: int = 5) -> list[Hit]:
        sims = linear_kernel(self.vectorizer.transform([query]), self.matrix).ravel()
        hits = []
        for chunk, sim in zip(self.chunks, sims):
            score = float(sim)
            if equipment_type and chunk.manual.equipment_type == equipment_type:
                score += EQUIPMENT_BOOST
            if metric and metric in chunk.manual.metrics:
                score += METRIC_BOOST
            hits.append(Hit(chunk, score))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]

    def best_manual(self, hits: list[Hit]) -> Manual | None:
        """검색 결과 청크 점수를 매뉴얼별로 합산해 가장 관련 높은 매뉴얼을 고른다."""
        totals: dict[str, float] = {}
        for h in hits:
            totals[h.chunk.manual.id] = totals.get(h.chunk.manual.id, 0.0) + h.score
        if not totals:
            return None
        return self.manuals[max(totals, key=totals.get)]
