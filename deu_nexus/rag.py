"""LangChain + ChromaDB RAG: 크롤 데이터를 근거로 답하고 출처 URL을 반환."""

from __future__ import annotations

import os
import shutil
import time as time_mod
from typing import Any

from langchain_classic.chains import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.vectorstores import Chroma
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from deu_nexus.crawler import build_driver, fetch_article_body, run_crawl
from deu_nexus.pipeline import CHROMA_DIR, crawl_to_dataframe, dataframe_to_documents, save_sqlite

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small")


def _embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=EMBED_MODEL)


def _llm() -> ChatOpenAI:
    return ChatOpenAI(model=MODEL, temperature=0.2)


def ingest_crawl_to_stores(
    crawl: dict[str, Any],
    *,
    enrich_bodies: bool = False,
    body_top: int = 6,
    body_chars: int = 4000,
) -> dict[str, Any]:
    """
    크롤 dict → Pandas → SQLite + Chroma 재색인.
    enrich_bodies=True면 앞쪽 몇 개 글의 본문을 Selenium으로 채움.
    """
    df = crawl_to_dataframe(crawl)
    if enrich_bodies and not df.empty and "url" in df.columns:
        if "body" not in df.columns:
            df["body"] = ""
        driver = build_driver(headless=True)
        try:
            n = min(body_top, len(df))
            for pos in range(n):
                url = df.iloc[pos].get("url")
                cur = str(df.iloc[pos].get("body") or "").strip()
                if not url or cur:
                    continue
                time_mod.sleep(0.3)
                ix = df.index[pos]
                df.at[ix, "body"] = (fetch_article_body(driver, str(url)) or "")[:body_chars]
        finally:
            driver.quit()

    path = save_sqlite(df)
    docs = dataframe_to_documents(df)
    if not docs:
        return {"sqlite": str(path), "chroma_docs": 0}

    CHROMA_DIR.parent.mkdir(parents=True, exist_ok=True)
    if CHROMA_DIR.exists():
        shutil.rmtree(CHROMA_DIR)
    Chroma.from_documents(
        documents=docs,
        embedding=_embeddings(),
        persist_directory=str(CHROMA_DIR),
    )
    return {"sqlite": str(path), "chroma_docs": len(docs), "rows": len(df)}


def answer_with_rag(
    user_message: str,
    *,
    mid: str = "Notice",
    pages: int = 4,
    enrich_bodies: bool = False,
    k_retrieve: int = 6,
) -> dict[str, Any]:
    """최신 크롤 → 저장소 반영 → LangChain RAG 답변."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 환경변수를 설정하세요.")

    crawl = run_crawl(
        mid=mid,
        pages=max(1, min(20, pages)),
        delay=0.5,
        no_filter=True,
        fetch_body=False,
        headless=True,
    )
    arts = list(crawl.get("articles") or [])
    if not arts:
        return {
            "reply": "불러온 공지가 없습니다. 게시판 설정·페이지 수를 확인해 주세요.",
            "sources": [],
            "crawl_summary": {
                "base": crawl["source"]["base"],
                "mid": crawl["source"]["mid"],
                "count_total": crawl["count_total"],
            },
            "ingest": None,
        }

    ingest = ingest_crawl_to_stores(crawl, enrich_bodies=enrich_bodies)

    vs = Chroma(
        persist_directory=str(CHROMA_DIR),
        embedding_function=_embeddings(),
    )
    retriever = vs.as_retriever(search_kwargs={"k": k_retrieve})

    prompt = ChatPromptTemplate.from_template(
        "당신은 동의대학교 학생서비스센터(DESS) 공지만 근거로 답하는 도우미입니다.\n"
        "규칙:\n"
        "1) 아래 참고 공지에 없는 내용은 추측하지 말고 모른다고 합니다.\n"
        "2) 답변 마지막에 '출처'를 적고, 사용한 공지의 제목과 URL을 나열합니다.\n"
        "3) URL은 참고 공지에 있는 것만 사용합니다.\n\n"
        "참고 공지:\n{context}\n\n"
        "질문: {input}"
    )

    combine = create_stuff_documents_chain(_llm(), prompt)
    chain = create_retrieval_chain(retriever, combine)
    out = chain.invoke({"input": user_message})

    answer = str(out.get("answer") or "").strip()
    ctx = out.get("context") or []
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for d in ctx:
        meta = getattr(d, "metadata", None) or {}
        url = meta.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        sources.append(
            {
                "title": meta.get("title", ""),
                "url": url,
                "posted": meta.get("posted", ""),
                "author": meta.get("author", ""),
            }
        )

    return {
        "reply": answer,
        "sources": sources,
        "crawl_summary": {
            "base": crawl["source"]["base"],
            "mid": crawl["source"]["mid"],
            "count_total": crawl["count_total"],
        },
        "ingest": ingest,
    }
