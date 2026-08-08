"""
Regression tests for the chunker.

WHY THIS FILE EXISTS
The original chunker only accumulated paragraphs and never split one that was
already too big. Document AI output from PDFs frequently has no blank lines, so
whole documents arrived as a single "paragraph" and passed through untouched:
median chunk 10,471 chars against a 1,500 target, largest 70,971.

Nothing failed. No exception, no warning, and the character count was correct.
But Vertex silently truncates past ~2048 tokens, so about 65% of the corpus was
indexed and unsearchable at the same time. It survived weeks because every check
in the project asked "did it run?" and none asked "how big are the chunks?".

The first test below would have caught it on day one.
"""

import pytest

from app.ingestion.chunking.splitters import chunk_text

SIZE = 1500


def test_no_chunk_exceeds_the_limit_even_without_paragraph_breaks():
    """The bug, reproduced exactly: one huge paragraph, no blank lines."""
    text = "word " * 20_000  # ~100k chars, zero paragraph breaks
    chunks = chunk_text(text, chunk_size=SIZE)

    assert chunks, "a large document must produce chunks"
    assert max(len(c) for c in chunks) <= SIZE, (
        f"largest chunk {max(len(c) for c in chunks)} exceeds the {SIZE} limit; "
        "an oversized chunk is silently truncated at embedding time"
    )


def test_size_limit_holds_for_prose_tables_and_code():
    """Different shapes of real document content, all bounded."""
    cases = {
        "prose": "This is a sentence. " * 900,
        "no_sentence_breaks": "x" * 12_000,          # forces the hard cut
        "table_like": "| col a | col b |\n" * 800,   # newlines, no blank lines
        "mixed": ("para one\n\n" + "y" * 9_000 + "\n\npara three"),
    }
    for name, text in cases.items():
        chunks = chunk_text(text, chunk_size=SIZE)
        assert max(len(c) for c in chunks) <= SIZE, f"{name} produced an oversized chunk"


def test_no_text_is_lost():
    """Splitting must not drop content -- only restructure it."""
    text = "\n\n".join(f"Paragraph {i} with some content in it." for i in range(200))
    chunks = chunk_text(text, chunk_size=SIZE)

    original_words = text.split()
    chunked_words = " ".join(chunks).split()
    assert chunked_words == original_words, "words were lost or reordered by chunking"


def test_paragraph_boundaries_are_preferred_when_they_fit():
    """Small paragraphs should pack together, not become one chunk each."""
    text = "\n\n".join(["Short paragraph."] * 40)
    chunks = chunk_text(text, chunk_size=SIZE)
    assert len(chunks) < 40, "small paragraphs should be packed, not emitted individually"


def test_oversized_paragraph_splits_on_sentence_boundaries_when_possible():
    """Prefer a clean sentence break over a hard character cut."""
    sentence = "This sentence is reasonably long and ends with a period. "
    chunks = chunk_text(sentence * 200, chunk_size=SIZE)

    # If splitting happened at sentence ends, most chunks finish with a period.
    ending_cleanly = sum(1 for c in chunks if c.rstrip().endswith("."))
    assert ending_cleanly >= len(chunks) * 0.8, (
        "expected most chunks to end at a sentence boundary"
    )


@pytest.mark.parametrize("text", ["", "   ", "\n\n\n"])
def test_empty_input_returns_no_chunks(text):
    assert chunk_text(text) == []


def test_single_short_document_stays_one_chunk():
    assert len(chunk_text("Just a short note.", chunk_size=SIZE)) == 1
