from typing import Any, Dict, List, Optional

def answer_with_sources(
    user_message: str,
    *,
    mid: str = "deu",
    sources: Optional[List[str]] = None,
    pages: int = 1,
    include_article_bodies: bool = False,
) -> Dict[str, Any]:
    """
    Generate an answer with sources using RAG.

    Args:
        user_message (str): The user's query message.
        mid (str): 단일 소스 레거시 (default: "deu").
        sources: ['deu','dess'] 등 복수 소스(우선).
        pages (int): 게시판 페이지 수 (default: 1).
        include_article_bodies (bool): Whether to include article bodies in the response.

    Returns:
        Dict[str, Any]: The response containing the answer and sources.
    """
    if not user_message or not isinstance(user_message, str):
        raise ValueError("user_message must be a non-empty string.")
    
    # 지연 로딩: 서버 시작 시 pandas/numpy import 지연
    from deu_info.rag import answer_with_rag

    return answer_with_rag(
        user_message,
        mid=mid,
        sources=sources,
        pages=pages,
        enrich_bodies=include_article_bodies,
        cancel_event=None,
    )


def answer_with_sources_cancellable(
    user_message: str,
    *,
    mid: str = "deu",
    sources: Optional[List[str]] = None,
    pages: int = 1,
    include_article_bodies: bool = False,
    cancel_event=None,
) -> Dict[str, Any]:
    """서버 취소 토큰(cancel_event)을 받아 중단 가능한 응답 생성."""
    if not user_message or not isinstance(user_message, str):
        raise ValueError("user_message must be a non-empty string.")

    from deu_info.rag import answer_with_rag

    return answer_with_rag(
        user_message,
        mid=mid,
        sources=sources,
        pages=pages,
        enrich_bodies=include_article_bodies,
        cancel_event=cancel_event,
    )