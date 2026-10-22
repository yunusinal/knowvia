"""Measure multi-turn follow-ups against the configured LLM (ADR-08 conversation context).

Each scenario runs through the real path: answer_question -> append_exchange -> safe_history.
For every follow-up turn the retrieval query strategy is also compared without extra LLM calls.
Corpus, SQLite and Qdrant are in memory; the running demo API is never touched.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.models import Base, Conversation, User
from app.repositories.vector_store import VectorStore
from app.services.chat import answer_question, retrieval_query
from app.services.conversations import append_exchange, safe_history
from app.services.embeddings import get_embedder
from app.services.llm import LLMUnavailableError, get_llm
from app.services.prompt import HistoryTurn, strip_citations
from app.services.retrieval import retrieve
from app.services.sparse import get_sparse_encoder
from scripts.rag_eval import ROOT, _normalize_text, _rate, prepare_isolated_corpus

SCENARIOS_PATH = ROOT / "eval" / "conversations.jsonl"
DEFAULT_OUTPUT_PATH = ROOT / "eval" / "results" / "followup-current-2026-10-22.json"
# Groq ücretsiz katmanı dakikada 8000 token verir; turlar arasında beklemek 429 hatasını önler.
PAUSE_SECONDS = 12
RETRY_WAIT_SECONDS = 30
STRATEGIES = ("current", "question_only", "previous_question", "llm_rewrite")
# Deneysel "condense question" deseni: uygulamada değil, yalnızca bu ölçümde kullanılır.
REWRITE_PROMPT = """Rewrite the user's latest question as a standalone question in the same language.
Use the conversation history only to resolve references (it, this, "what about ...").
Do not answer it and do not add facts. If it is already standalone, return it unchanged.
Output only the question."""


@dataclass(frozen=True)
class Turn:
    question: str
    expected_document: str | None = None
    expected_answer_contains: list[str] = field(default_factory=list)
    should_abstain: bool = False
    unauthorized_document: str | None = None
    forbidden_answer_contains: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Scenario:
    id: str
    category: str
    user_email: str
    turns: list[Turn]


def load_scenarios(path: Path = SCENARIOS_PATH) -> list[Scenario]:
    scenarios = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            raw = json.loads(line)
            raw["turns"] = [Turn(**turn) for turn in raw["turns"]]
            scenarios.append(Scenario(**raw))
    if len({scenario.id for scenario in scenarios}) != len(scenarios):
        raise ValueError("Scenario IDs must be unique")
    return scenarios


def _with_retry(call: Any) -> Any:
    for attempt in range(3):
        try:
            return call()
        except LLMUnavailableError:
            if attempt == 2:
                raise
            time.sleep(RETRY_WAIT_SECONDS)
    raise RuntimeError("unreachable")


def _rewrite(llm: Any, question: str, history: list[HistoryTurn]) -> str:
    if not history:
        return question
    turns = "\n".join(f"{turn.role}: {strip_citations(turn.content)[:500]}" for turn in history[-4:])
    message = f"History:\n{turns}\n\nLatest question: {question}"
    return _with_retry(lambda: llm.generate(REWRITE_PROMPT, message)).text.strip()


def _strategies(llm: Any | None, question: str, history: list[HistoryTurn]) -> dict[str, str]:
    """llm verilmezse yeniden yazma atlanır (ör. yalnız örneklemde ölçmek için)."""
    previous_questions = [turn.content for turn in history if turn.role == "user"]
    queries = {
        "current": retrieval_query(question, history),  # üretimde kullanılan sorgu
        "question_only": question,
        "previous_question": f"{question}\n{previous_questions[-1]}" if previous_questions else question,
    }
    if llm is not None:
        queries["llm_rewrite"] = _rewrite(llm, question, history)
    return queries


def evaluate_turn(
    db: Session, store: VectorStore, embedder: Any, llm: Any, user: User,
    conversation: Conversation | None, turn: Turn,
) -> tuple[dict[str, Any], Conversation]:
    settings = get_settings()
    history = safe_history(db, user, conversation) if conversation else []

    retrieval: dict[str, dict[str, Any]] = {}
    queries = _strategies(llm, turn.question, history)
    for name, query in queries.items():
        hits = retrieve(db, store, embedder, user, query, settings.retrieval_top_k)
        passing = [hit for hit in hits if hit.score >= settings.retrieval_min_score]
        filenames = [hit.filename for hit in hits]
        retrieval[name] = {
            "top5": [{"filename": hit.filename, "score": round(hit.score, 4)} for hit in hits],
            "expected_in_top5": turn.expected_document in filenames if turn.expected_document else None,
            "expected_first": bool(filenames) and filenames[0] == turn.expected_document
            if turn.expected_document else None,
            "expected_above_threshold": any(hit.filename == turn.expected_document for hit in passing)
            if turn.expected_document else None,
            "unauthorized_in_top5": turn.unauthorized_document in filenames
            if turn.unauthorized_document else False,
            # Ret beklenen turda eşiği geçen parça varsa ilk katman reddedemedi (skor şişmesi).
            "passes_threshold": bool(passing),
        }

    result = _with_retry(lambda: answer_question(
        db, store, embedder, llm, user, turn.question,
        top_k=settings.retrieval_top_k, min_score=settings.retrieval_min_score, history=history,
    ))
    conversation = append_exchange(db, user, conversation, turn.question, result, "rag")

    answer = _normalize_text(result.answer)
    source_files = {source.filename for source in result.sources}
    forbidden = [token for token in turn.forbidden_answer_contains if _normalize_text(token) in answer]
    acl_pass = not (
        forbidden
        or retrieval["current"]["unauthorized_in_top5"]
        or (turn.unauthorized_document in source_files if turn.unauthorized_document else False)
    )
    row = {
        "question": turn.question,
        "rewritten_question": queries["llm_rewrite"],
        "history_turns_available": len(history),
        "answer": result.answer,
        "sources": [asdict(source) for source in result.sources],
        "retrieval": retrieval,
        "expected_document": turn.expected_document,
        "cited_expected_document": turn.expected_document in source_files if turn.expected_document else None,
        "expected_answer_facts_present": all(
            _normalize_text(token) in answer for token in turn.expected_answer_contains
        ) if turn.expected_answer_contains else None,
        "should_abstain": turn.should_abstain,
        "did_abstain": result.no_evidence,
        "abstention_correct": result.no_evidence == turn.should_abstain,
        "acl_pass": acl_pass,
        "latency_ms": {"retrieval": result.retrieval_ms, "generation": result.generation_ms},
    }
    return row, conversation


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    follow_ups = [row for row in rows if row["history_turns_available"] > 0]
    answerable = [row for row in follow_ups if row["expected_document"]]

    refusals = [row for row in follow_ups if row["should_abstain"]]

    def by_strategy(metric: str, subset: list[dict[str, Any]]) -> dict[str, Any]:
        return {name: _rate([row["retrieval"][name][metric] for row in subset]) for name in STRATEGIES}

    def by_category(metric: str) -> dict[str, Any]:
        return {
            category: by_strategy(metric, [row for row in answerable if row["category"] == category])
            for category in sorted({row["category"] for row in answerable})
        }

    categories = sorted({row["category"] for row in follow_ups})
    return {
        "follow_up_turns": len(follow_ups),
        "answerable_follow_up_turns": len(answerable),
        "retrieval_expected_in_top5": by_strategy("expected_in_top5", answerable),
        "retrieval_expected_first": by_strategy("expected_first", answerable),
        "retrieval_expected_above_threshold": by_strategy("expected_above_threshold", answerable),
        "retrieval_expected_first_by_category": by_category("expected_first"),
        "retrieval_expected_in_top5_by_category": by_category("expected_in_top5"),
        # Düşük daha iyi: ret beklenen turda ilk katman (eşik) kaç kez geçildi.
        "refusal_turns_passing_threshold": by_strategy("passes_threshold", refusals),
        "answer_fact_coverage": _rate([row["expected_answer_facts_present"] for row in answerable]),
        "cited_expected_document": _rate([row["cited_expected_document"] for row in answerable]),
        "abstention_accuracy": _rate([row["abstention_correct"] for row in follow_ups]),
        "acl_leaks": sum(not row["acl_pass"] for row in follow_ups),
        "by_category": {
            category: {
                "facts": _rate([
                    row["expected_answer_facts_present"] for row in answerable if row["category"] == category
                ]),
                "abstention": _rate([row["abstention_correct"] for row in follow_ups if row["category"] == category]),
            }
            for category in categories
        },
    }


def run(output_path: Path = DEFAULT_OUTPUT_PATH) -> dict[str, Any]:
    settings = get_settings()
    scenarios = load_scenarios()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    embedder = get_embedder()
    store = VectorStore(QdrantClient(":memory:"), f"{settings.qdrant_collection}_followup_eval", embedder.dimension, get_sparse_encoder())
    store.ensure_collection()
    try:
        Base.metadata.create_all(engine)
        rows: list[dict[str, Any]] = []
        with Session(engine) as db:
            users = prepare_isolated_corpus(db, store, embedder)
            llm = get_llm()
            for scenario in scenarios:
                conversation: Conversation | None = None
                for index, turn in enumerate(scenario.turns):
                    row, conversation = evaluate_turn(
                        db, store, embedder, llm, users[scenario.user_email], conversation, turn,
                    )
                    rows.append({"scenario": scenario.id, "category": scenario.category, "turn": index + 1, **row})
                    time.sleep(PAUSE_SECONDS)
        report = {
            "created_at": datetime.now(UTC).isoformat(),
            "llm_model": settings.llm_model,
            "embedding_model": settings.embedding_model,
            "retrieval_top_k": settings.retrieval_top_k,
            "retrieval_min_score": settings.retrieval_min_score,
            "scenario_count": len(scenarios),
            "metrics": summarize(rows),
            "results": rows,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"output": str(output_path), "metrics": report["metrics"]}, ensure_ascii=False, indent=2))
        return report
    finally:
        store.close()
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()
