"""Run the small end-to-end RAG evaluation against the configured LLM.

The evaluation corpus, SQLite database, and Qdrant collection are created in memory;
the running demo API and its persistent Qdrant directory are never modified.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.models import Base, Department, Document, Role, User, Visibility
from app.repositories.vector_store import VectorStore, point_id
from app.services.authorization import allowed_document_ids
from app.services.chat import answer_question
from app.services.embeddings import get_embedder
from app.services.ingest import ingest_document
from app.services.llm import get_llm
from app.services.retrieval import retrieve
from scripts.seed_demo_documents import load_manifest

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_PATH = ROOT / "eval" / "questions.jsonl"
DEFAULT_OUTPUT_PATH = ROOT / "eval" / "results" / "current-llm-2026-10-22.json"
DEMO_USERS = {
    "admin@demo.local": (Role.ADMIN, None),
    "it@demo.local": (Role.MEMBER, Department.IT),
    "hr@demo.local": (Role.MEMBER, Department.HR),
    "finance@demo.local": (Role.MEMBER, Department.FINANCE),
}


@dataclass(frozen=True)
class EvalQuestion:
    id: str
    category: str
    question: str
    user_email: str
    expected_document: str | None
    expected_answer_contains: list[str]
    should_abstain: bool
    unauthorized_document: str | None
    forbidden_answer_contains: list[str]


def load_questions(path: Path = QUESTIONS_PATH) -> list[EvalQuestion]:
    questions = [
        EvalQuestion(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not 15 <= len(questions) <= 25:
        raise ValueError(f"Evaluation set must contain 15–25 questions, got {len(questions)}")
    ids = [question.id for question in questions]
    if len(set(ids)) != len(ids):
        raise ValueError("Evaluation question IDs must be unique")
    return questions


def prepare_isolated_corpus(db: Session, store: VectorStore, embedder: Any) -> dict[str, User]:
    users: dict[str, User] = {}
    for email, (role, department) in DEMO_USERS.items():
        user = User(email=email, password_hash="unused-evaluation-account", role=role, department=department)
        db.add(user)
        db.flush()
        users[email] = user

    admin_id = users["admin@demo.local"].id
    settings = get_settings()
    for demo in load_manifest(ROOT / "data" / "demo_docs"):
        document = ingest_document(
            db,
            store,
            embedder,
            filename=demo.filename,
            content=(ROOT / "data" / "demo_docs" / demo.filename).read_bytes(),
            department=demo.department,
            visibility=demo.visibility,
            uploaded_by=admin_id,
            max_mb=settings.max_upload_mb,
        )
        if document.status.value != "active":
            raise RuntimeError(f"Evaluation document failed to index: {demo.filename}")
    return users


def evaluate_question(
    db: Session,
    store: VectorStore,
    embedder: Any,
    llm: Any,
    user: User,
    question: EvalQuestion,
) -> dict[str, Any]:
    settings = get_settings()
    hits = retrieve(db, store, embedder, user, question.question, top_k=5)
    hit_documents = {hit.document_id for hit in hits}
    documents = {document.id: document for document in db.scalars(select(Document))}
    hit_filenames = {documents[doc_id].filename_original for doc_id in hit_documents}
    allowed_filenames = {
        document.filename_original
        for document in db.scalars(
            select(Document).where(Document.id.in_(allowed_document_ids(db, user)))
        )
    }

    started = time.perf_counter()
    result = answer_question(
        db,
        store,
        embedder,
        llm,
        user,
        question.question,
        top_k=settings.retrieval_top_k,
        min_score=settings.retrieval_min_score,
    )
    end_to_end_ms = round((time.perf_counter() - started) * 1000)

    top_five_point_ids = {point_id(hit.document_id, hit.chunk_index) for hit in hits}
    source_filenames = {source.filename for source in result.sources}
    citations_valid = all(
        source.filename in allowed_filenames
        and source.filename in hit_filenames
        and source.chunk_id in top_five_point_ids
        for source in result.sources
    )
    if question.should_abstain:
        citations_valid = citations_valid and not result.sources
    else:
        citations_valid = citations_valid and bool(result.sources)

    answer = result.answer
    answer_folded = _normalize_text(answer)
    expected_facts = (
        all(_normalize_text(token) in answer_folded for token in question.expected_answer_contains)
        if question.expected_answer_contains
        else None
    )
    forbidden_output = [
        token for token in question.forbidden_answer_contains if _normalize_text(token) in answer_folded
    ]
    forbidden_retrieval = question.unauthorized_document in hit_filenames if question.unauthorized_document else False
    forbidden_citation = question.unauthorized_document in source_filenames if question.unauthorized_document else False
    acl_pass = not (forbidden_retrieval or forbidden_citation or forbidden_output)

    return {
        "id": question.id,
        "category": question.category,
        "question": question.question,
        "user_email": question.user_email,
        "answer": answer,
        "sources": [asdict(source) for source in result.sources],
        "retrieved_top5": [
            {"filename": hit.filename, "score": round(hit.score, 4)} for hit in hits
        ],
        "expected_document": question.expected_document,
        "recall_at_5": (
            question.expected_document in hit_filenames if question.expected_document else None
        ),
        "expected_answer_facts_present": expected_facts,
        "should_abstain": question.should_abstain,
        "did_abstain": result.no_evidence,
        "abstention_correct": result.no_evidence == question.should_abstain,
        "citation_correct": citations_valid,
        "acl_pass": acl_pass,
        "acl_checks": {
            "unauthorized_document_in_retrieval": forbidden_retrieval,
            "unauthorized_document_in_citations": forbidden_citation,
            "forbidden_answer_markers": forbidden_output,
        },
        "latency_ms": {
            "retrieval": result.retrieval_ms,
            "generation": result.generation_ms,
            "end_to_end": end_to_end_ms,
        },
    }


def _rate(values: list[bool]) -> dict[str, int | float]:
    return {
        "passed": sum(values),
        "total": len(values),
        "rate": round(sum(values) / len(values), 4) if values else 0.0,
    }


def _normalize_text(value: str) -> str:
    # LLM çıktıları dar/kırılmaz boşluk kullanabiliyor; bunları normal boşluğa indir.
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _latency_summary(values: list[int]) -> dict[str, int | float]:
    if not values:
        return {"count": 0, "mean_ms": 0, "median_ms": 0}
    return {
        "count": len(values),
        "mean_ms": round(statistics.mean(values)),
        "median_ms": round(statistics.median(values)),
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    recalls = [row["recall_at_5"] for row in results if row["recall_at_5"] is not None]
    expected_facts = [
        row["expected_answer_facts_present"]
        for row in results
        if row["expected_answer_facts_present"] is not None
    ]
    return {
        "question_count": len(results),
        "answerable_question_count": len(recalls),
        "recall_at_5": _rate(recalls),
        "expected_answer_fact_coverage": _rate(expected_facts),
        "abstention_accuracy": _rate([row["abstention_correct"] for row in results]),
        "citation_correctness": _rate([row["citation_correct"] for row in results]),
        "acl_leakage": {
            "leaks": sum(not row["acl_pass"] for row in results),
            "cases": len(results),
            "passed": all(row["acl_pass"] for row in results),
        },
        "latency_ms": {
            "retrieval": _latency_summary([row["latency_ms"]["retrieval"] for row in results]),
            "generation": _latency_summary(
                [row["latency_ms"]["generation"] for row in results if row["latency_ms"]["generation"] > 0]
            ),
            "end_to_end": _latency_summary([row["latency_ms"]["end_to_end"] for row in results]),
        },
    }


def run(output_path: Path = DEFAULT_OUTPUT_PATH) -> dict[str, Any]:
    settings = get_settings()
    questions = load_questions()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    client = QdrantClient(":memory:")
    embedder = get_embedder()
    store = VectorStore(client, f"{settings.qdrant_collection}_eval", embedder.dimension)
    store.ensure_collection()
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            users = prepare_isolated_corpus(db, store, embedder)
            llm = get_llm()
            results = [
                evaluate_question(db, store, embedder, llm, users[item.user_email], item)
                for item in questions
            ]
        report = {
            "created_at": datetime.now(UTC).isoformat(),
            "llm_model": settings.llm_model,
            "embedding_model": settings.embedding_model,
            "retrieval_top_k": 5,
            "retrieval_min_score": settings.retrieval_min_score,
            "corpus_document_count": len(load_manifest(ROOT / "data" / "demo_docs")),
            "metrics": summarize(results),
            "results": results,
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
    args = parser.parse_args()
    run(args.output)


if __name__ == "__main__":
    main()
