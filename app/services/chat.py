"""Soru-cevap akışı (master plan §5.2): yetkili arama → eşik → LLM → kaynak doğrulama.

"Bilgi yok" ve "yetki yok" aynı sabit cevabı alır. Arama yetkisiz belgeleri zaten hiç görmediği
için iki durum sistemin içinde de aynı yoldan geçer; cevap gizli bir belgenin varlığını ele vermez.
"""

import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import User
from app.repositories.vector_store import ChunkHit, VectorStore, point_id
from app.services.embeddings import Embedder
from app.services.llm import LLMClient
from app.services.prompt import SYSTEM_PROMPT, LabeledSource, build_user_message, label_sources, parse_answer
from app.services.retrieval import retrieve

NO_EVIDENCE_MESSAGE = "Yetkiniz dahilindeki belgelerde bu soruya yeterli bilgi bulamadım."
_SNIPPET_CHARS = 300


@dataclass(frozen=True)
class Source:
    source_id: str
    document_id: str
    filename: str
    page_number: int | None
    chunk_id: str
    snippet: str


@dataclass(frozen=True)
class ChatResult:
    answer: str
    sources: list[Source]
    no_evidence: bool
    retrieval_ms: int
    generation_ms: int


def answer_question(
    db: Session,
    store: VectorStore,
    embedder: Embedder,
    llm: LLMClient,
    user: User,
    question: str,
    *,
    top_k: int,
    min_score: float,
    history: list[str] | None = None,
) -> ChatResult:
    started = time.perf_counter()
    previous_questions = history or []
    retrieval_context = "\n".join(previous_questions[-2:])
    retrieval_query = f"{question}\n{retrieval_context}" if retrieval_context else question
    hits = retrieve(db, store, embedder, user, retrieval_query, top_k)
    # Birinci çekimserlik katmanı: eşiğin altındaki chunk'lar LLM'e hiç gitmez.
    evidence = [hit for hit in hits if hit.score >= min_score]
    retrieval_ms = _elapsed_ms(started)
    if not evidence:
        return _no_evidence(retrieval_ms, generation_ms=0)

    sources = label_sources(evidence)
    generated = llm.generate(
        SYSTEM_PROMPT, build_user_message(question, sources, previous_questions)
    )
    parsed = parse_answer(generated.text, sources)
    if parsed.insufficient:
        # İkinci katman: kaynaklar soruyu karşılamıyorsa model INSUFFICIENT_CONTEXT döndürür.
        return _no_evidence(retrieval_ms, generated.latency_ms)

    by_label = {source.label: source for source in sources}
    # Model geçerli etiket kullanmadıysa uydurma kaynak yazılmaz; bağlama verilen kaynaklar gösterilir.
    shown = [by_label[label] for label in parsed.cited_labels] or sources
    return ChatResult(
        answer=parsed.text,
        sources=[_to_source(source) for source in shown],
        no_evidence=False,
        retrieval_ms=retrieval_ms,
        generation_ms=generated.latency_ms,
    )


def _no_evidence(retrieval_ms: int, generation_ms: int) -> ChatResult:
    return ChatResult(
        answer=NO_EVIDENCE_MESSAGE,
        sources=[],
        no_evidence=True,
        retrieval_ms=retrieval_ms,
        generation_ms=generation_ms,
    )


def _to_source(source: LabeledSource) -> Source:
    hit: ChunkHit = source.hit
    snippet = hit.text if len(hit.text) <= _SNIPPET_CHARS else hit.text[:_SNIPPET_CHARS].rstrip() + "…"
    return Source(
        source_id=source.label,
        document_id=hit.document_id,
        filename=hit.filename,
        page_number=hit.page_number,
        chunk_id=point_id(hit.document_id, hit.chunk_index),
        snippet=snippet,
    )


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
