from __future__ import annotations

from model_gateway.types import ChatMessage, Role

from gateway.domains.hr_policy.retrieval import Chunk

_SYSTEM_PROMPT = (
    "You are a knowledgeable HR assistant for Acme Corp employees. Answer the "
    "question accurately and concisely based only on the provided HR policy "
    "context below. If the policy is silent on a topic, say so clearly rather "
    "than guessing. Always cite the specific policy section by name."
)


def build_prompt(question: str, retrieved: list[tuple[Chunk, float]]) -> list[ChatMessage]:
    context_blocks = "\n\n".join(f"[{chunk.header}]\n{chunk.text}" for chunk, _score in retrieved)
    user_content = (
        f"Policy context:\n{context_blocks}\n\n"
        f"Employee question: {question}\n\n"
        "Answer (include section reference):"
    )
    return [
        ChatMessage(role=Role.SYSTEM, content=_SYSTEM_PROMPT),
        ChatMessage(role=Role.USER, content=user_content),
    ]
