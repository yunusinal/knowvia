"""Ölçüm sonuçlarını karşılaştırır: soru türüne göre Hit@1, bootstrap güven aralığı, eşik analizi.

Çalıştırma (repo kökünden):
    uv run python -m scripts.embedding_bench.analyze corpus_large
"""

import json
import random
import sys
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).resolve().parent / "results"
NAMES = ["e5-small", "e5-base", "e5-large", "qwen3-0.6b"]
BOOTSTRAP_SAMPLES = 10_000


def load(corpus_name: str) -> dict[str, dict[str, Any]]:
    folder = RESULTS_DIR / corpus_name
    return {n: json.loads((folder / f"{n}.json").read_text(encoding="utf-8")) for n in NAMES}


def print_by_kind(results: dict[str, dict[str, Any]]) -> None:
    print("== Hit@1 per question type (correct/total)")
    kinds = sorted({q["kind"] for q in results[NAMES[0]]["questions"]})
    print(f"{'type':34}" + "".join(f"{n:>12}" for n in NAMES))
    for kind in kinds:
        cells = []
        for n in NAMES:
            qs = [q for q in results[n]["questions"] if q["kind"] == kind]
            cells.append(f"{sum(q['rank'] == 1 for q in qs)}/{len(qs)}")
        print(f"{kind:34}" + "".join(f"{c:>12}" for c in cells))


def bootstrap_ci(a: list[bool], b: list[bool]) -> tuple[float, float]:
    """a - b Hit@1 farkının %95 güven aralığı; sorular yerine koyarak yeniden örneklenir."""
    n = len(a)
    diffs = []
    for _ in range(BOOTSTRAP_SAMPLES):
        idx = [random.randrange(n) for _ in range(n)]
        diffs.append(sum(a[i] - b[i] for i in idx) / n)
    diffs.sort()
    return diffs[int(BOOTSTRAP_SAMPLES * 0.025)], diffs[int(BOOTSTRAP_SAMPLES * 0.975)]


def print_bootstrap(results: dict[str, dict[str, Any]]) -> None:
    print(f"\n== Bootstrap: 95% CI of the Hit@1 difference ({BOOTSTRAP_SAMPLES} resamples)")
    random.seed(0)
    hits = {n: [q["rank"] == 1 for q in results[n]["questions"]] for n in NAMES}
    pairs = [("e5-large", "qwen3-0.6b"), ("e5-large", "e5-base"), ("e5-base", "e5-small"), ("qwen3-0.6b", "e5-base")]
    for a, b in pairs:
        observed = (sum(hits[a]) - sum(hits[b])) / len(hits[a])
        lo, hi = bootstrap_ci(hits[a], hits[b])
        verdict = "significant" if lo > 0 or hi < 0 else "could be chance"
        print(f"{a} - {b}: {observed:+.1%}  [{lo:+.1%}, {hi:+.1%}]  -> {verdict}")


def print_threshold(results: dict[str, dict[str, Any]]) -> None:
    print("\n== Threshold: how well does a similarity cut-off separate unanswerable questions?")
    for n in NAMES:
        correct = sorted(q["expected_score"] for q in results[n]["questions"] if q["rank"] == 1)
        no_answer = sorted(x["top1_score"] for x in results[n]["no_answer"])
        lost_if_reject_all = sum(s <= no_answer[-1] for s in correct) / len(correct)
        cut_at_10pct = correct[int(len(correct) * 0.10)]
        caught_at_10pct = sum(s < cut_at_10pct for s in no_answer) / len(no_answer)
        print(
            f"{n:12} unanswerable {no_answer[0]:.3f}-{no_answer[-1]:.3f} | correct {correct[0]:.3f}-{correct[-1]:.3f} | "
            f"reject all unanswerable -> lose {lost_if_reject_all:.0%} of correct | "
            f"lose 10% of correct -> catch {caught_at_10pct:.0%} of unanswerable"
        )


if __name__ == "__main__":
    data = load(sys.argv[1] if len(sys.argv) > 1 else "corpus_large")
    print_by_kind(data)
    print_bootstrap(data)
    print_threshold(data)
