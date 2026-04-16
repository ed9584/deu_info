"""Pandas로 크롤 결과를 정리하고 SQLite·ChromaDB에 저장."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from langchain_core.documents import Document

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DEU_DATA_DIR", _PROJECT_ROOT / "data"))
SQLITE_PATH = DATA_DIR / "deu_articles.sqlite"
CHROMA_DIR = DATA_DIR / "chroma_db"


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def crawl_to_dataframe(crawl: dict[str, Any]) -> pd.DataFrame:
    rows = list(crawl.get("articles") or [])
    if not rows:
        return pd.DataFrame(
            columns=[
                "url",
                "title",
                "author",
                "posted",
                "views",
                "list_no",
                "is_notice",
                "mid",
                "base",
                "body",
                "ingested_at",
            ]
        )
    src = crawl.get("source") or {}
    mid = src.get("mid", "")
    base = src.get("base", "")
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        r.setdefault("mid", mid)
        r.setdefault("base", base)
        r.setdefault("ingested_at", now)
        r.setdefault("body", "")
    df = pd.DataFrame(rows)
    if "body" not in df.columns:
        df["body"] = ""
    return df


def save_sqlite(df: pd.DataFrame, path: Path | None = None) -> Path:
    """크롤 결과를 SQLite에 저장 (같은 실행의 전체 스냅샷으로 교체)."""
    ensure_data_dir()
    p = path or SQLITE_PATH
    if df.empty:
        conn = sqlite3.connect(p)
        try:
            df.to_sql("articles", conn, if_exists="replace", index=False)
        finally:
            conn.close()
        return p
    df = df.copy()
    if "url" in df.columns:
        df = df.drop_duplicates(subset=["url"], keep="last")
    conn = sqlite3.connect(p)
    try:
        df.to_sql("articles", conn, if_exists="replace", index=False)
    finally:
        conn.close()
    return p


def dataframe_to_documents(df: pd.DataFrame) -> list[Document]:
    """Chroma/LangChain용 Document 리스트."""
    docs: list[Document] = []
    for _, row in df.iterrows():
        url = str(row.get("url") or "")
        title = str(row.get("title") or "")
        posted = str(row.get("posted") or "")
        author = str(row.get("author") or "")
        b = row.get("body")
        if b is None or (isinstance(b, float) and pd.isna(b)):
            body = ""
        else:
            body = str(b).strip()
        meta = {
            "url": url,
            "title": title,
            "posted": posted,
            "author": author,
            "mid": str(row.get("mid") or ""),
        }
        text = f"제목: {title}\n날짜: {posted}\n작성: {author}\n"
        if body:
            text += f"본문:\n{body}\n"
        else:
            text += "(본문 미수집 — 제목·날짜 기준)\n"
        docs.append(Document(page_content=text, metadata=meta))
    return docs
