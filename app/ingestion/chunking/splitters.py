import re
from typing import List

import logfire

# Sentence boundary: a period/question/exclamation mark followed by whitespace.
# Used as the preferred place to break a paragraph that is too big on its own.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _split_oversized(paragraph: str, chunk_size: int) -> List[str]:
    """
    Break a single paragraph that is ALREADY larger than chunk_size.

    This is the case the original chunker missed. Document AI often returns a
    whole PDF page (or a whole document) as one block with no blank lines, so
    paragraph splitting alone left chunks of 70k+ characters. Those exceed the
    embedding model's input limit, and Vertex truncates silently rather than
    erroring - so the tail of the text was indexed as if it existed but was
    never actually searchable.

    Prefer sentence boundaries. Fall back to a hard character cut for text with
    no sentence structure at all (tables, code listings, OCR runs).
    """
    pieces: List[str] = []

    for sentence in _SENTENCE_END.split(paragraph):
        if not sentence.strip():
            continue
        if len(sentence) <= chunk_size:
            pieces.append(sentence)
        else:
            for i in range(0, len(sentence), chunk_size):
                piece = sentence[i:i + chunk_size]
                if piece.strip():
                    pieces.append(piece)

    return pieces


def chunk_text(text: str, chunk_size: int = 1500) -> List[str]:
    """
    Split text into chunks of at most chunk_size characters, preferring
    paragraph boundaries, then sentence boundaries, then a hard cut.

    The size ceiling is a hard guarantee, not a target: every returned chunk is
    <= chunk_size. That matters because an oversized chunk is not just untidy,
    it is silently unsearchable.
    """
    with logfire.span("Text chunking", text_length=len(text)):
        if not text.strip():
            return []

        # Pass 1: build units that are each guaranteed to fit in a chunk.
        units: List[str] = []
        for paragraph in text.split("\n\n"):
            if not paragraph.strip():
                continue
            if len(paragraph) <= chunk_size:
                units.append(paragraph)
            else:
                units.extend(_split_oversized(paragraph, chunk_size))

        # Pass 2: greedily pack units together so we don't emit lots of tiny
        # chunks when the source has many short paragraphs.
        chunks: List[str] = []
        current = ""
        for unit in units:
            if current and len(current) + len(unit) + 2 > chunk_size:
                chunks.append(current.strip())
                current = unit + "\n\n"
            else:
                current += unit + "\n\n"

        if current.strip():
            chunks.append(current.strip())

        valid_chunks = [c for c in chunks if c.strip()]
        logfire.info(f"generated {len(valid_chunks)} chunks")
        return valid_chunks
