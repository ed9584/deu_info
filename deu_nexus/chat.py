from typing import Any, Dict

def answer_with_sources(
    user_message: str,
    *,
    mid: str = "Notice",
    pages: int = 4,
    include_article_bodies: bool = False,
) -> Dict[str, Any]:
    """
    Generate an answer with sources using RAG.

    Args:
        user_message (str): The user's query message.
        mid (str): The module ID to query (default: "Notice").
        pages (int): The number of pages to search (default: 4).
        include_article_bodies (bool): Whether to include article bodies in the response.

    Returns:
        Dict[str, Any]: The response containing the answer and sources.
    """
    if not user_message or not isinstance(user_message, str):
        raise ValueError("user_message must be a non-empty string.")
    
    # 지연 로딩: 서버 시작 시 pandas/numpy import 지연
    from deu_nexus.rag import answer_with_rag

    return answer_with_rag(
        user_message,
        mid=mid,
        pages=pages,
        enrich_bodies=include_article_bodies,
        cancel_event=None,
    )


def answer_with_sources_cancellable(
    user_message: str,
    *,
    mid: str = "Notice",
    pages: int = 4,
    include_article_bodies: bool = False,
    cancel_event=None,
) -> Dict[str, Any]:
    """서버 취소 토큰(cancel_event)을 받아 중단 가능한 응답 생성."""
    if not user_message or not isinstance(user_message, str):
        raise ValueError("user_message must be a non-empty string.")

    from deu_nexus.rag import answer_with_rag

    return answer_with_rag(
        user_message,
        mid=mid,
        pages=pages,
        enrich_bodies=include_article_bodies,
        cancel_event=cancel_event,
    )