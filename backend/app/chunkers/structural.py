import re
import statistics

from .base import ChunkerBase

_ATX = re.compile(r"^\s{0,3}#{1,6}\s+\S")
# Longest heading we'll believe in a plain-text document, in words.
_BARE_HEADING_MAX_WORDS = 9
# A heading must be this much shorter than a typical line to count as one.
_BARE_HEADING_LENGTH_RATIO = 0.6


def _is_heading(line: str, median_len: float) -> bool:
    """Does this line open a new section?

    Markdown gives us `#` for free. PDFs do not: pypdf hands back a page as
    hard-wrapped lines with no blank lines and no markup, so a `#`-only rule
    collapses a well-structured PDF into a single topic-mixed chunk — the exact
    failure this chunker exists to prevent.

    So for unmarked text, three signals together: the line is short in absolute
    words, it is *substantially shorter than a typical line in this document*,
    and it doesn't end in sentence punctuation. The relative-length test is what
    makes this work on wrapped prose — body lines run to the full column width
    while a heading stops early — and it self-calibrates to the document instead
    of hard-coding a column width. The punctuation test rules out the other
    common short line, a paragraph's final one.

    False positives remain possible (a genuinely short, unpunctuated sentence).
    The cost is asymmetric and cheap: a spurious heading only adds a prefix and
    a split boundary, while a missed heading fuses two topics into one embedding
    that points at neither.
    """
    if _ATX.match(line):
        return True
    line = line.strip()
    if not line or line[-1] in ".,;:!?":
        return False
    if len(line.split()) > _BARE_HEADING_MAX_WORDS:
        return False
    return bool(median_len) and len(line) <= median_len * _BARE_HEADING_LENGTH_RATIO


class StructuralChunker(ChunkerBase):
    """Split on document structure first, size second.

    Why this exists: fixed-width word windows cut wherever the counter runs out,
    which routinely lands a chunk across two unrelated sections. The resulting
    embedding is the average of two topics and points at neither, so it matches
    many queries weakly and none strongly — the "grab-bag chunk" that wins
    searches it has no business winning.

    So: never merge across a heading, split paragraphs at blank lines, and pack
    consecutive paragraphs only up to `max_words`. A section longer than the cap
    is split into overlapping windows *within* the section, so oversized input
    degrades to the fixed-size behaviour rather than failing.

    Headings are prepended to each chunk they govern. A chunk reading "93 percent
    water recovery" is far more retrievable as "## Life support — 93 percent
    water recovery", and it gives the model the section name for free.
    """

    def __init__(self, max_words: int = 180, overlap_words: int = 30, min_words: int = 25):
        self.max_words = max_words
        self.overlap_words = overlap_words
        self.min_words = min_words

    def _sections(self, text: str) -> list[tuple[str, list[str]]]:
        """Group the document into (heading, [paragraphs]) pairs.

        Walks lines rather than blank-line-separated blocks, because PDF text
        extraction produces neither blank lines nor markup — the only structure
        left is line length, and that is only visible one line at a time.
        Blank lines still end a paragraph where they exist.
        """
        lines = text.split("\n")
        lengths = [len(ln.strip()) for ln in lines if ln.strip()]
        median_len = statistics.median(lengths) if lengths else 0.0

        sections: list[tuple[str, list[str]]] = []
        heading = ""
        paragraphs: list[str] = []
        current: list[str] = []

        def end_paragraph() -> None:
            if current:
                paragraphs.append(" ".join(current))
                current.clear()

        def end_section() -> None:
            nonlocal paragraphs
            end_paragraph()
            if paragraphs:
                sections.append((heading, paragraphs))
                paragraphs = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                end_paragraph()
                continue
            if _is_heading(line, median_len):
                # A heading closes the previous section outright; content never
                # crosses the boundary.
                end_section()
                heading = stripped.lstrip("#").strip()
                continue
            current.append(stripped)

        end_section()
        return sections

    def _windows(self, words: list[str]) -> list[list[str]]:
        """Overlapping windows, used only when one section exceeds max_words."""
        step = max(1, self.max_words - self.overlap_words)
        out = []
        start = 0
        while start < len(words):
            out.append(words[start:start + self.max_words])
            start += step
        return out

    def chunk(self, text: str, metadata: dict) -> list[dict]:
        page = metadata.get("page_number")
        pieces: list[str] = []

        for heading, paragraphs in self._sections(text):
            prefix = f"{heading} — " if heading else ""
            group: list[str] = []
            count = 0

            def flush(group: list[str]) -> None:
                if group:
                    pieces.append(prefix + " ".join(group))

            for para in paragraphs:
                words = para.split()
                if len(words) > self.max_words:
                    # Oversized single paragraph: emit what's buffered, then window it.
                    flush(group)
                    group, count = [], 0
                    for win in self._windows(words):
                        pieces.append(prefix + " ".join(win))
                    continue
                if count + len(words) > self.max_words:
                    flush(group)
                    group, count = [], 0
                group.append(para)
                count += len(words)

            flush(group)

        # Fold a runt into its neighbour rather than embedding a fragment too
        # short to carry meaning. The head case is common in extracted PDFs,
        # where the document title lands alone above the first real heading.
        if len(pieces) > 1 and len(pieces[-1].split()) < self.min_words:
            pieces[-2] = pieces[-2] + " " + pieces[-1]
            pieces.pop()
        if len(pieces) > 1 and len(pieces[0].split()) < self.min_words:
            pieces[1] = pieces[0] + " " + pieces[1]
            pieces.pop(0)

        if not pieces and text.strip():
            pieces = [text.strip()]

        return [
            {"text": t, "chunk_index": i, "page_number": page}
            for i, t in enumerate(pieces)
        ]
