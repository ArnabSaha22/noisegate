#!/usr/bin/env python3
"""
Retrieval evaluation for the NoiseGate corpus.

WHAT THIS MEASURES, AND WHY THOSE METRICS
-----------------------------------------
Retrieval here is two stages, so it needs two kinds of measurement:

  recall@15   Did the FAST stage (Qdrant vector search) surface a correct
              document anywhere in its 15 candidates? If it did not, the
              reranker cannot possibly recover -- it only reorders what it is
              given. This is the ceiling on the whole system.

  precision@5 Of the 5 chunks the reranker kept, how many came from a correct
              document? This is what actually reaches the LLM, and with a
              25,000-char context cap it is what the answer is built from.

  MRR@5       How high the FIRST correct chunk ranks. Rank 1 scores 1.0, rank 2
              scores 0.5, and so on. Precision alone cannot tell "correct chunk
              first" from "correct chunk last".

The headline comparison is stage 1 alone versus stage 1 + reranking. That is the
project's central claim -- a cross-encoder earns its cost by filtering noise --
and until now nothing measured it. The 48 distractor documents exist precisely
to make that number meaningful.

Out-of-domain questions (expect: []) are scored separately. Vector search always
returns its nearest neighbours, so the question is not "did it retrieve nothing"
but "was the reranker's top score low enough to tell the difference". That gap is
the evidence for a relevance floor.

COST
No LLM calls. One embedding per question (fractions of a cent), so this is cheap
enough to run on every change to chunking, top_n, or the embedding model.

USAGE
    python scripts/evaluate.py                    # full run
    python scripts/evaluate.py --no-rerank        # stage 1 only
    python scripts/evaluate.py --json out.json    # machine-readable
    python scripts/evaluate.py --limit 5          # quick smoke test
"""

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from dotenv import load_dotenv

load_dotenv()

from app.config import settings
from app.services.retrieval.embedding import embed_query
from app.services.retrieval.ranking_service import rerank_documents
from qdrant_client import QdrantClient

GOLDEN = Path(__file__).resolve().parent.parent / "eval" / "golden_set.yaml"

STAGE1_LIMIT = 15  # matches app/agents/nodes/retriever.py
TOP_N = 5


def load_questions(limit=None):
    data = yaml.safe_load(GOLDEN.read_text())
    qs = data["questions"]
    return qs[:limit] if limit else qs


def evaluate_one(client, q, use_rerank: bool):
    """Run one question through retrieval and score it."""
    expected = set(q.get("expect") or [])

    vector = embed_query(q["question"])
    points = client.query_points(
        collection_name=settings.QDRANT_COLLECTION,
        query=vector,
        limit=STAGE1_LIMIT,
        with_payload=True,
    ).points

    stage1_sources = [p.payload.get("source", "?") for p in points]
    texts = [p.payload.get("text", "") for p in points]

    if use_rerank and texts:
        kept = rerank_documents(q["question"], texts, top_n=TOP_N)
        # rerank_documents returns text, so map back to sources. Index by first
        # occurrence: identical chunk text from two documents is vanishingly
        # unlikely, and treating it as one is the conservative choice.
        lookup = {}
        for src, txt in zip(stage1_sources, texts):
            lookup.setdefault(txt, src)
        top_sources = [lookup.get(t, "?") for t in kept]
        top_score = _top_rerank_score(q["question"], texts)
    else:
        top_sources = stage1_sources[:TOP_N]
        top_score = points[0].score if points else 0.0

    hits = [s in expected for s in top_sources]

    # Out-of-domain questions have no correct document; they are scored on
    # whether the top score is low, not on hit rate.
    if not expected:
        return {
            "id": q["id"],
            "out_of_domain": True,
            "top_score": round(float(top_score), 4),
            "top_source": top_sources[0] if top_sources else None,
        }

    recall_at_15 = any(s in expected for s in stage1_sources)
    precision_at_5 = sum(hits) / max(1, len(top_sources))
    mrr = 0.0
    for i, hit in enumerate(hits, start=1):
        if hit:
            mrr = 1.0 / i
            break

    return {
        "id": q["id"],
        "out_of_domain": False,
        "expected": sorted(expected),
        "recall@15": recall_at_15,
        "precision@5": round(precision_at_5, 3),
        "mrr@5": round(mrr, 3),
        "top_source": top_sources[0] if top_sources else None,
        "top_score": round(float(top_score), 4),
    }


def _top_rerank_score(question, texts):
    """
    FlashRank's score for the best passage -- the relevance-floor signal.

    Deliberately reuses ranking_service._get_ranker() rather than constructing a
    Ranker here. Building one directly with cache_dir="/tmp/flashrank" fails
    outright when macOS (or a Cloud Run cold start) has purged /tmp:

        NO_SUCHFILE: Load model from /tmp/flashrank/...onnx failed

    ranking_service handles that by falling back to the default cache dir. Going
    through it means this measures the SAME ranker instance production uses,
    instead of silently scoring 0.0 for every question.
    """
    from flashrank import RerankRequest
    from app.services.retrieval.ranking_service import _get_ranker

    out = _get_ranker().rerank(
        RerankRequest(
            query=question,
            passages=[{"id": i, "text": t} for i, t in enumerate(texts)],
        )
    )
    return out[0]["score"] if out else 0.0


def summarize(results, label):
    scored = [r for r in results if not r["out_of_domain"]]
    ood = [r for r in results if r["out_of_domain"]]

    if not scored:
        return {}

    summary = {
        "label": label,
        "questions": len(scored),
        "recall@15": round(sum(r["recall@15"] for r in scored) / len(scored), 3),
        "precision@5": round(statistics.mean(r["precision@5"] for r in scored), 3),
        "mrr@5": round(statistics.mean(r["mrr@5"] for r in scored), 3),
        "top1_accuracy": round(
            sum(1 for r in scored if r["top_source"] in r["expected"]) / len(scored), 3
        ),
    }
    if ood:
        in_scores = [r["top_score"] for r in scored]
        ood_scores = [r["top_score"] for r in ood]
        summary["in_domain_top_score_median"] = round(statistics.median(in_scores), 4)
        summary["out_of_domain_top_score_median"] = round(statistics.median(ood_scores), 4)
        summary["separation"] = round(
            statistics.median(in_scores) - statistics.median(ood_scores), 4
        )
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-rerank", action="store_true", help="stage 1 only, skip the cross-encoder")
    ap.add_argument("--both", action="store_true", help="run with AND without rerank and compare")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args()

    questions = load_questions(args.limit)
    client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY, timeout=60)

    info = client.get_collection(settings.QDRANT_COLLECTION)
    print(f"collection : {settings.QDRANT_COLLECTION}  ({info.points_count:,} points)")
    print(f"questions  : {len(questions)}  "
          f"({sum(1 for q in questions if not q.get('expect'))} out-of-domain)\n")

    modes = [False, True] if args.both else [not args.no_rerank]
    all_summaries, all_results = [], {}

    for use_rerank in modes:
        label = "stage1 + rerank" if use_rerank else "stage1 only"
        print(f"--- {label} ---")
        t0 = time.time()
        results = []
        for q in questions:
            r = evaluate_one(client, q, use_rerank)
            results.append(r)
            if not r["out_of_domain"]:
                mark = "OK " if r["recall@15"] else "MISS"
                print(f"  {mark} {r['id']:<22} P@5={r['precision@5']:<5} MRR={r['mrr@5']:<5} top={r['top_source']}")
            else:
                print(f"  --  {r['id']:<22} top_score={r['top_score']:<8} top={r['top_source']}")

        s = summarize(results, label)
        s["seconds"] = round(time.time() - t0, 1)
        all_summaries.append(s)
        all_results[label] = results
        print()

    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    for s in all_summaries:
        print(f"\n{s['label']}  ({s['questions']} scored questions, {s['seconds']}s)")
        print(f"  recall@15      {s['recall@15']:.3f}   did stage 1 find it at all")
        print(f"  precision@5    {s['precision@5']:.3f}   of what reaches the LLM")
        print(f"  MRR@5          {s['mrr@5']:.3f}   how high the first hit ranks")
        print(f"  top-1 accuracy {s['top1_accuracy']:.3f}")
        if "separation" in s:
            print(f"  relevance signal: in-domain median {s['in_domain_top_score_median']}, "
                  f"out-of-domain median {s['out_of_domain_top_score_median']} "
                  f"(gap {s['separation']})")

    if len(all_summaries) == 2:
        a, b = all_summaries
        print("\n" + "-" * 72)
        print("DOES RERANKING EARN ITS KEEP?")
        for metric in ("precision@5", "mrr@5", "top1_accuracy"):
            delta = b[metric] - a[metric]
            arrow = "+" if delta > 0 else ""
            print(f"  {metric:<15} {a[metric]:.3f} -> {b[metric]:.3f}   ({arrow}{delta:.3f})")
        print("  recall@15 is identical by construction: reranking reorders, it cannot add.")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(
            {"summaries": all_summaries, "results": all_results}, indent=2))
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
