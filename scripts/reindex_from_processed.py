#!/usr/bin/env python3
"""
Rebuild the Qdrant index from the PROCESSED bucket — no Document AI required.

Why this exists
---------------
The PROCESSED bucket already holds the text Document AI extracted from every
document. Re-running the normal ingestion path (app/ingestion/processor.py)
would send all 100+ MB of PDFs back through Document AI, which is the expensive
step. This script skips it: it reads the already-extracted text, re-chunks it
locally (free), embeds it, and upserts to Qdrant.

Use it after losing a Qdrant cluster, or after changing the chunking strategy.

Safety
------
Read-only against GCS. The only writes are to Qdrant. --dry-run does the full
chunking pass and reports exactly what WOULD be embedded without making a
single paid call, so always dry-run first.

Re-running is safe: chunks for a document are deleted by source filter before
its new chunks are written, so you get replacement rather than duplication.
(That closes the "re-uploading adds stale chunks alongside new ones" gap noted
in CLAUDE.md §7.)

Usage
-----
    python scripts/reindex_from_processed.py --dry-run
    python scripts/reindex_from_processed.py --limit 3        # cheap live test
    python scripts/reindex_from_processed.py                  # full run
    python scripts/reindex_from_processed.py --recreate       # wipe first
"""

import argparse
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from google.cloud import storage
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.config import settings
from app.ingestion.chunking.splitters import chunk_text

VECTOR_SIZE = 768  # text-embedding-004


def build_plan(limit=None, source_type=None):
    """Read the PROCESSED bucket and re-chunk everything. Costs nothing."""
    client = storage.Client(project=settings.PROJECT_ID)
    plan = []

    for blob in client.list_blobs(settings.PROCESSED_BUCKET):
        if not blob.name.endswith(".json"):
            continue

        try:
            doc = json.loads(blob.download_as_bytes())
        except Exception as e:
            print(f"  ! skipping unreadable {blob.name}: {e}")
            continue

        stype = doc.get("source_type") or (blob.name.split("/")[0] if "/" in blob.name else "general")
        if source_type and stype != source_type:
            continue

        filename = doc.get("filename") or os.path.basename(blob.name).removesuffix(".json")
        old_chunks = doc.get("chunks", [])
        if not old_chunks:
            continue

        # Reconstruct the extracted text, then re-split with the current chunker.
        full_text = "\n\n".join(old_chunks)
        new_chunks = chunk_text(full_text)
        if not new_chunks:
            continue

        plan.append({"filename": filename, "source_type": stype, "chunks": new_chunks})
        if limit and len(plan) >= limit:
            break

    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only; makes no paid calls")
    ap.add_argument("--limit", type=int, help="only process the first N documents")
    ap.add_argument("--source-type", help="only process one source type, e.g. true / noisy")
    ap.add_argument("--recreate", action="store_true", help="DELETE and recreate the collection first")
    args = ap.parse_args()

    if not settings.QDRANT_URL:
        sys.exit("QDRANT_URL is unset — check the Qdrant endpoint variable in .env")

    print(f"collection : {settings.QDRANT_COLLECTION}")
    print(f"source     : gs://{settings.PROCESSED_BUCKET}\n")

    print("Re-chunking (free)...")
    plan = build_plan(limit=args.limit, source_type=args.source_type)

    total_chunks = sum(len(d["chunks"]) for d in plan)
    total_chars = sum(len(c) for d in plan for c in d["chunks"])
    biggest = max((len(c) for d in plan for c in d["chunks"]), default=0)

    print(f"\n  documents      {len(plan)}")
    print(f"  chunks         {total_chunks:,}")
    print(f"  characters     {total_chars:,}")
    print(f"  largest chunk  {biggest:,}")
    print(f"  est. tokens    {total_chars/4:,.0f}  (~4 chars/token)")

    if args.dry_run:
        print("\n--dry-run: nothing embedded, nothing written. No cost incurred.")
        return

    # Imported late so --dry-run never initialises Vertex.
    from app.services.retrieval.embedding import embed_texts

    qdrant = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY, timeout=60)

    if args.recreate and qdrant.collection_exists(settings.QDRANT_COLLECTION):
        print(f"\n!! deleting collection {settings.QDRANT_COLLECTION}")
        qdrant.delete_collection(settings.QDRANT_COLLECTION)

    if not qdrant.collection_exists(settings.QDRANT_COLLECTION):
        print(f"creating collection {settings.QDRANT_COLLECTION} ({VECTOR_SIZE}d, COSINE)")
        qdrant.create_collection(
            collection_name=settings.QDRANT_COLLECTION,
            vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE),
        )

    # Qdrant can only filter on an INDEXED payload field, and the replace-before-write
    # step below filters on "source". Creating this is idempotent in effect: if the
    # index already exists Qdrant complains, which is harmless.
    try:
        qdrant.create_payload_index(
            collection_name=settings.QDRANT_COLLECTION,
            field_name="source",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
        print('payload index ready on "source"')
    except Exception:
        pass

    print()
    done = 0
    for i, doc in enumerate(plan, 1):
        chunks = doc["chunks"]
        print(f"[{i}/{len(plan)}] {doc['filename'][:52]:<52} {len(chunks):>4} chunks", flush=True)

        # Replace rather than duplicate, so re-runs stay clean. Done BEFORE
        # embedding so a failure here cannot waste a paid embedding call.
        qdrant.delete(
            collection_name=settings.QDRANT_COLLECTION,
            points_selector=models.FilterSelector(
                filter=models.Filter(must=[
                    models.FieldCondition(key="source", match=models.MatchValue(value=doc["filename"]))
                ])
            ),
        )

        vectors = embed_texts(chunks)

        qdrant.upsert(
            collection_name=settings.QDRANT_COLLECTION,
            points=[
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vec,
                    payload={
                        "text": chunk,
                        "source": doc["filename"],
                        "source_type": doc["source_type"],
                        "raw_gcs_path": f"gs://{settings.RAW_BUCKET}/{doc['source_type']}/{doc['filename']}",
                    },
                )
                for chunk, vec in zip(chunks, vectors)
            ],
        )
        done += len(chunks)

    info = qdrant.get_collection(settings.QDRANT_COLLECTION)
    print(f"\ndone. upserted {done:,} chunks. collection now holds {info.points_count:,} points.")


if __name__ == "__main__":
    main()
