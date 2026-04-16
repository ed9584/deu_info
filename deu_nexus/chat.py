from typing import Any, Dict
from deu_nexus.rag import answer_with_rag

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
    
    try:
        return answer_with_rag(
            user_message,
            mid=mid,
            pages=pages,
            enrich_bodies=include_article_bodies,
        )
    except Exception as e:
        return {"error": str(e), "message": "Failed to generate an answer with sources."}