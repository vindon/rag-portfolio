from __future__ import annotations

from model_gateway.types import Role

from gateway.domains.hr_policy.prompts import build_prompt
from gateway.domains.hr_policy.retrieval import Chunk


def test_build_prompt_has_system_and_user_messages() -> None:
    messages = build_prompt("How much leave do I get?", [])

    assert len(messages) == 2
    assert messages[0].role == Role.SYSTEM
    assert messages[1].role == Role.USER


def test_build_prompt_includes_question_and_chunk_headers_and_text() -> None:
    chunks = [
        (Chunk(header="1.1 Entitlement", text="20 days per year."), 0.9),
        (Chunk(header="1.2 Carry-Over", text="Up to 5 days carry over."), 0.8),
    ]

    messages = build_prompt("How much leave do I get?", chunks)

    user_content = messages[1].content
    assert "How much leave do I get?" in user_content
    assert "1.1 Entitlement" in user_content
    assert "20 days per year." in user_content
    assert "1.2 Carry-Over" in user_content
    assert "Up to 5 days carry over." in user_content


def test_build_prompt_system_message_mentions_citation_requirement() -> None:
    messages = build_prompt("q", [])

    assert "cite" in messages[0].content.lower()
