"""
Regression tests for embedding batch construction.

WHY THIS FILE EXISTS
Vertex enforces two separate limits, and the code respected neither:

  per text     ~2048 tokens -- silently TRUNCATED, no error
  per request  20,000 tokens summed across the batch -- hard 400

The old code sent fixed batches of 50. On dense technical prose, which packs
closer to 2.8 chars/token than the usual 4, fifty 1,500-char chunks reached
~22,215 tokens and the whole ingestion run died partway through with an
InvalidArgument that named neither limit.

These tests are pure logic -- no network, no Vertex, no credentials -- so they
run in milliseconds and belong in CI.
"""

import pytest

from app.services.retrieval.embedding import (
    MAX_BATCH_CHARS,
    MAX_BATCH_ITEMS,
    _iter_batches,
)

# Pessimistic ratio for dense technical text. Real measurement was ~2.8; using a
# harsher number keeps a safety margin in the assertion itself.
CHARS_PER_TOKEN = 2.5
REQUEST_TOKEN_CAP = 20_000


def _batches(texts):
    return list(_iter_batches(texts))


def test_the_exact_batch_that_broke_ingestion():
    """42 chunks x 1500 chars hit ~22,215 tokens and failed with a 400."""
    batches = _batches(["x" * 1500] * 42)

    assert len(batches) > 1, "42 full-size chunks must not be sent as one request"
    for b in batches:
        chars = sum(len(t) for t in b)
        assert chars / CHARS_PER_TOKEN < REQUEST_TOKEN_CAP, (
            f"batch of {chars} chars could exceed the {REQUEST_TOKEN_CAP}-token request cap"
        )


def test_no_batch_exceeds_either_cap_across_the_whole_corpus():
    """3,846 chunks is the real corpus size."""
    for b in _batches(["x" * 1500] * 3846):
        assert len(b) <= MAX_BATCH_ITEMS
        assert sum(len(t) for t in b) <= MAX_BATCH_CHARS


def test_every_text_is_emitted_exactly_once_and_in_order():
    """Batching must not drop or reorder -- embeddings are zipped back to chunks."""
    texts = [f"chunk-{i}" for i in range(500)]
    flattened = [t for b in _batches(texts) for t in b]
    assert flattened == texts


def test_single_oversized_text_is_isolated_rather_than_poisoning_a_batch():
    """
    One text larger than the whole budget still has to go somewhere. It should
    travel alone so it cannot drag other chunks over the request cap with it.
    (Vertex will truncate it -- that is the per-text limit, handled upstream by
    the 1,500-char chunk ceiling.)
    """
    batches = _batches(["x" * 50_000])
    assert len(batches) == 1 and len(batches[0]) == 1


def test_many_tiny_texts_respect_the_item_cap():
    for b in _batches(["hi"] * 500):
        assert len(b) <= MAX_BATCH_ITEMS


@pytest.mark.parametrize("texts", [[], ["only one"]])
def test_degenerate_inputs(texts):
    flattened = [t for b in _batches(texts) for t in b]
    assert flattened == texts


def test_budget_leaves_headroom_below_the_hard_cap():
    """The character budget must imply fewer than 20k tokens even pessimistically."""
    assert MAX_BATCH_CHARS / CHARS_PER_TOKEN < REQUEST_TOKEN_CAP
