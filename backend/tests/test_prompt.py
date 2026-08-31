"""Prompt construction.

The system prompt was "You are a helpful assistant. Use the provided context to
answer questions accurately." Nothing told the model to stay inside the context
or to admit when the context doesn't cover the question — so a retrieval miss
came back as a confident answer from training data, which in a RAG product is
the failure mode that matters most. Chunks were also concatenated anonymously,
leaving the answer with nothing to cite even though the UI shows chunk cards.
"""

from app.services.llm import build_prompt

CHUNKS = [
    {"chunk_id": "a1", "text": "Water recovery runs at 93 percent.", "page_number": 4},
    {"chunk_id": "b2", "text": "Solar arrays generate 84 kilowatts.", "page_number": None},
]


class TestGrounding:
    def test_the_model_is_told_to_stay_inside_the_context(self):
        system, _ = build_prompt("q", CHUNKS)
        assert "context" in system.lower()
        assert "don't know" in system.lower() or "do not know" in system.lower()

    def test_no_context_is_stated_rather_than_left_blank(self):
        """An empty context block reads as 'nothing relevant', not 'no retrieval ran'."""
        system, user = build_prompt("What is the altitude?", [])
        assert "no context" in (system + user).lower()
        assert "What is the altitude?" in user


class TestCitations:
    def test_chunks_are_numbered_so_the_answer_can_cite_them(self):
        _, user = build_prompt("q", CHUNKS)
        assert "[1]" in user and "[2]" in user

    def test_chunk_text_is_included_verbatim(self):
        _, user = build_prompt("q", CHUNKS)
        for chunk in CHUNKS:
            assert chunk["text"] in user

    def test_page_numbers_are_passed_through_when_known(self):
        _, user = build_prompt("q", CHUNKS)
        assert "p. 4" in user

    def test_a_missing_page_number_is_omitted_not_printed_as_none(self):
        _, user = build_prompt("q", CHUNKS)
        assert "None" not in user

    def test_the_question_comes_after_the_context(self):
        """Context first, question last — the model answers what it read last."""
        _, user = build_prompt("How much water?", CHUNKS)
        assert user.index("Water recovery") < user.index("How much water?")
