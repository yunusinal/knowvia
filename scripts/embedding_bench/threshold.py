"""RETRIEVAL_MIN_SCORE eşiğini gerçek akışla ölçer: demo belgeleri + yetki filtreli arama.

Geçici bir klasörde boş SQLite ve Qdrant kurulur, 13 demo belgesi gerçek modelle indekslenir;
proje veritabanına dokunulmaz. Her soru dört kullanıcı için sorulur ve üç gruba ayrılır:
cevaplanmalı / reddedilmeli (cevap yetkisiz belgede) / reddedilmeli (cevap hiçbir belgede yok).

Çalıştırma (repo kökünden):
    uv run python -m scripts.embedding_bench.threshold [chunk_tokens]
"""

import json
import sys
import tempfile
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path

from qdrant_client import QdrantClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import Base, Department, Document, Role, User
from app.repositories.vector_store import VectorStore
from app.services import ingest
from app.services.authorization import can_access_document
from app.services.chunking import chunk_pages
from app.services.embeddings import SUPPORTED_MODELS, FastEmbedEmbedder
from app.services.retrieval import retrieve
from app.services.sparse import get_sparse_encoder
from scripts.embedding_bench.corpus_large import NO_ANSWER, PASSAGES, QUESTIONS
from scripts.seed_demo_documents import DEMO_DOCS_DIR, seed_documents

RESULTS_DIR = Path(__file__).resolve().parent / "results" / "threshold"
TOP_K = 5
SHOULD_ANSWER = "cevaplanmalı"
UNAUTHORIZED = "reddedilmeli: cevap yetkisiz belgede"
NO_EVIDENCE = "reddedilmeli: cevap hiçbir belgede yok"
GROUPS = (SHOULD_ANSWER, UNAUTHORIZED, NO_EVIDENCE)


@dataclass(frozen=True)
class Observation:
    user: str
    question: str
    group: str
    top_score: float | None  # izinli sonuçlar arasındaki en yüksek skor; sonuç yoksa None
    expected_rank: int | None  # doğru belgenin ilk TOP_K sonuç içindeki sırası; yoksa None


def passage_to_document() -> dict[str, str]:
    """Her soru parçasının hangi demo belgesine girdiği (belge metninde aranarak)."""
    texts = {path.name: path.read_text(encoding="utf-8") for path in DEMO_DOCS_DIR.glob("*.md")}
    mapping = {}
    for passage_id, passage in PASSAGES.items():
        [filename] = [name for name, text in texts.items() if passage in text]
        mapping[passage_id] = filename
    return mapping


def build_users(db: Session) -> dict[str, User]:
    users = {
        "admin": User(email="admin@eval.local", role=Role.ADMIN, department=None),
        "it": User(email="it@eval.local", role=Role.MEMBER, department=Department.IT),
        "hr": User(email="hr@eval.local", role=Role.MEMBER, department=Department.HR),
        "finance": User(email="finance@eval.local", role=Role.MEMBER, department=Department.FINANCE),
    }
    for user in users.values():
        user.password_hash = hash_password("eval-only")
        db.add(user)
    db.commit()
    return users


def observe(workdir: Path) -> tuple[list[Observation], int]:
    settings = get_settings()
    spec = SUPPORTED_MODELS[settings.embedding_model]
    embedder = FastEmbedEmbedder(spec, Path(settings.model_cache_dir))
    engine = create_engine(f"sqlite:///{workdir / 'eval.db'}")
    Base.metadata.create_all(engine)
    store = VectorStore(QdrantClient(path=str(workdir / "qdrant")), "threshold_eval", spec.dimension, get_sparse_encoder())
    store.ensure_collection()

    observations: list[Observation] = []
    try:
        with Session(engine) as db:
            users = build_users(db)
            seed_documents(db, store, embedder, users["admin"].id)
            documents = {d.filename_original: d for d in db.scalars(select(Document))}
            chunk_count = sum(d.chunk_count for d in documents.values())
            expected_file = passage_to_document()

            for name, user in users.items():
                for question, passage_id, _ in QUESTIONS:
                    expected = documents[expected_file[passage_id]]
                    group = SHOULD_ANSWER if can_access_document(user, expected) else UNAUTHORIZED
                    hits = retrieve(db, store, embedder, user, question, TOP_K)
                    ranks = [i for i, hit in enumerate(hits, start=1) if hit.document_id == expected.id]
                    observations.append(
                        Observation(name, question, group, hits[0].score if hits else None, ranks[0] if ranks else None)
                    )
                for question in NO_ANSWER:
                    hits = retrieve(db, store, embedder, user, question, TOP_K)
                    observations.append(Observation(name, question, NO_EVIDENCE, hits[0].score if hits else None, None))
    finally:
        store.close()
        engine.dispose()
    return observations, chunk_count


def passes(observation: Observation, threshold: float) -> bool:
    """Eşiği geçen soru LLM'e gider; geçemeyen "kanıt yok" ile reddedilir."""
    return observation.top_score is not None and observation.top_score >= threshold


def sweep(observations: list[Observation]) -> list[dict[str, float]]:
    rows = []
    for step in range(70, 91):
        threshold = step / 100
        row: dict[str, float] = {"threshold": threshold}
        for group in GROUPS:
            members = [o for o in observations if o.group == group]
            row[group] = sum(passes(o, threshold) for o in members) / len(members)
        rows.append(row)
    return rows


def main(chunk_tokens: int) -> None:
    # Yükleme akışı aynen kullanılır; yalnızca chunk boyutu deney için değiştirilir.
    ingest.chunk_pages = partial(chunk_pages, chunk_tokens=chunk_tokens, overlap_tokens=min(50, chunk_tokens // 4))
    with tempfile.TemporaryDirectory(prefix="knowvia-threshold-") as workdir:
        observations, chunk_count = observe(Path(workdir))

    groups = {group: [o for o in observations if o.group == group] for group in GROUPS}
    answerable = groups[SHOULD_ANSWER]
    first = sum(o.expected_rank == 1 for o in answerable) / len(answerable)
    in_context = sum(o.expected_rank is not None for o in answerable) / len(answerable)
    print(f"== chunk_tokens={chunk_tokens}: {chunk_count} chunk; grup büyüklükleri {[len(v) for v in groups.values()]}")
    print(f"   doğru belge 1. sırada: {first:.1%} | ilk {TOP_K} içinde (LLM bağlamı): {in_context:.1%}")
    for group, members in groups.items():
        scores = sorted(o.top_score for o in members if o.top_score is not None)
        print(f"   {group}: en düşük {scores[0]:.3f}, medyan {scores[len(scores) // 2]:.3f}, en yüksek {scores[-1]:.3f}")
    print("   Eşik | cevaplanmalı geçen | yetkisiz-cevaplı geçen | cevapsız geçen")
    rows = sweep(observations)
    for row in rows:
        if 0.76 <= row["threshold"] <= 0.84:
            print(f"   {row['threshold']:.2f} | {row[SHOULD_ANSWER]:>17.1%} | {row[UNAUTHORIZED]:>22.1%} | {row[NO_EVIDENCE]:>14.1%}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # "paragraph": paragraf sınırını koruyan parçalama (ADR-07). Eski açgözlü yöntemin sonuçları greedy-*.json.
    results_file = RESULTS_DIR / f"paragraph-e5-large-chunk{chunk_tokens}.json"
    results_file.write_text(
        json.dumps(
            {
                "model": get_settings().embedding_model,
                "chunk_tokens": chunk_tokens,
                "chunk_count": chunk_count,
                "top_k": TOP_K,
                "expected_first": first,
                "expected_in_top_k": in_context,
                "group_sizes": {group: len(v) for group, v in groups.items()},
                "sweep": rows,
                "observations": [asdict(o) for o in observations],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 350)
