"""웹 API용: RAG로 질의·출처 응답."""

from __future__ import annotations

from typing import Any

from deu_nexus.rag import answer_with_rag


def answer_with_sources(
    user_message: str,
    *,
    mid: str = "Notice",
    pages: int = 4,
    include_article_bodies: bool = False,
) -> dict[str, Any]:
    return answer_with_rag(
        user_message,
        mid=mid,
        pages=pages,
        enrich_bodies=include_article_bodies,
    )
