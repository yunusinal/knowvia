"""Gerçekçi ~350 token'lık bir chunk'ın embedding süresini ölçer (veri setindeki parçalar ~60 token).

Çalıştırma (repo kökünden):
    uv run --group bench python -m scripts.embedding_bench.long_chunk e5-large
"""

import sys
import time

from scripts.embedding_bench.bench import load_model
from scripts.embedding_bench.corpus_large import PASSAGES

CHUNK_TOKENS = 350
REPEATS = 8


def main(name: str) -> None:
    model, spec = load_model(name)
    tokenizer = model.model.tokenizer  # pyright: ignore[reportAttributeAccessIssue]
    tokenizer.no_padding()
    tokenizer.no_truncation()

    long_text = spec.passage_prefix + " ".join(PASSAGES.values())
    chunk = tokenizer.decode(tokenizer.encode(long_text).ids[:CHUNK_TOKENS])
    chunks = [chunk] * REPEATS

    list(model.embed(chunks[:1]))  # ısınma
    start = time.perf_counter()
    list(model.embed(chunks))
    per_chunk = (time.perf_counter() - start) / REPEATS

    tokens = len(tokenizer.encode(chunk).ids)
    print(f"{name}: {tokens}-token chunk -> {per_chunk * 1000:.0f} ms/chunk; 100 chunks ~ {per_chunk * 100:.0f} s")


if __name__ == "__main__":
    main(sys.argv[1])
