"""
Regression tests for the HTML loader.

WHY THIS FILE EXISTS
The whitespace-cleanup step split lines on a SINGLE space and rejoined with
newlines, so every word landed on its own line:

    "A\\nHands-On\\nGuide\\nto\\nKubernetes\\nHorizontal\\n&\\nVertical..."

Two of the six signal documents were indexed that way. As with the chunker, the
failure was invisible: no exception, and the character count was identical --
only the line structure was destroyed. It was found by measuring average line
length (5.4 chars, against 29-55 for correctly parsed formats), not by anything
breaking.

One character: split(" ") should have been split("  ").
"""

import pytest

from app.ingestion.loaders.html import parse_html

# Average characters per line below which text is structurally mangled. Correctly
# parsed documents in this corpus sit at 29-55; the broken ones sat at 5.4-5.8.
MIN_AVG_LINE_LEN = 15


def _avg_line_length(text: str) -> float:
    lines = [l for l in text.split("\n") if l.strip()]
    return sum(len(l) for l in lines) / max(1, len(lines))


@pytest.fixture
def html_file(tmp_path):
    def _write(body: str) -> str:
        p = tmp_path / "page.html"
        p.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
        return str(p)
    return _write


def test_words_stay_on_the_same_line(html_file):
    """The exact bug: prose must not become one word per line."""
    path = html_file("<p>A Hands-On Guide to Kubernetes Horizontal and Vertical Pod Autoscalers</p>")
    text = parse_html(path)

    assert "Hands-On Guide to Kubernetes" in text, "words were split onto separate lines"
    assert _avg_line_length(text) >= MIN_AVG_LINE_LEN


def test_multi_paragraph_document_keeps_sentence_structure(html_file):
    path = html_file(
        "<h1>Automate job creation and management</h1>"
        "<p>This article shows you how to get started with developer tools "
        "to automate the creation and management of jobs.</p>"
        "<p>It introduces the CLI, the SDKs, and the REST API.</p>"
    )
    text = parse_html(path)

    assert _avg_line_length(text) >= MIN_AVG_LINE_LEN
    assert "This article shows you how to get started" in text


def test_scripts_styles_and_metadata_are_stripped(html_file):
    path = html_file(
        "<script>var secret = 'do not index me';</script>"
        "<style>.cls { color: red; }</style>"
        "<noscript>enable javascript</noscript>"
        "<p>Real readable content.</p>"
    )
    text = parse_html(path)

    assert "Real readable content." in text
    for junk in ("do not index me", "color: red", "enable javascript"):
        assert junk not in text


def test_code_blocks_keep_their_tokens_together(html_file):
    """job_management.html contains JSON that the bug shredded character by line."""
    path = html_file('<pre>{"job_id": 478701692316314, "format": "MULTI_TASK"}</pre>')
    text = parse_html(path)
    assert '"job_id": 478701692316314' in text


def test_runs_of_whitespace_are_collapsed(html_file):
    """The cleanup should still do its actual job: kill HTML's padding."""
    path = html_file("<p>Text     with        wide      gaps</p>")
    text = parse_html(path)
    assert "     " not in text, "long whitespace runs should be collapsed"


def test_empty_document_does_not_raise(html_file):
    assert parse_html(html_file("")).strip() == ""
