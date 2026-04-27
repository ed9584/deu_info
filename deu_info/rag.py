"""빠른 Q&A + (필요 시) 요약/근거: 공지 기반 답변 + 출처 URL 반환.

기본 목표:
- 날짜/최신/목록 요청은 임베딩 없이 즉시 처리
- '요약' 같은 요청에서만 본문 수집/모델 호출(느릴 수 있음)
- 너무 오래된 범위 요청(예: 2년 전 전체)은 예외 처리
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from langchain_openai import ChatOpenAI

from concurrent.futures import ThreadPoolExecutor

from deu_info.crawler import (
    DEFAULT_BASE,
    DEFAULT_DEU_NOTICE_URL,
    build_driver,
    fetch_article_body,
    run_crawl,
    run_deu_notice_crawl,
)

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# "너무 오래된 정보" 기준(기본 365일). 범위/목록 요청에서 이보다 과거는 거절.
MAX_AGE_DAYS = int(os.environ.get("DEU_MAX_AGE_DAYS", "365"))

# 크롤 캐시 (source, pages) -> (ts, articles)
_CACHE: dict[tuple[str, int], tuple[float, list[dict], dict]] = {}
_CACHE_TTL_SEC = float(os.environ.get("DEU_CRAWL_CACHE_TTL_SEC", "120"))


def _llm() -> ChatOpenAI:
    return ChatOpenAI(model=MODEL, temperature=0.2)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_posted(s: str) -> datetime | None:
    s = (s or "").strip()
    for fmt in ("%Y.%m.%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def _tokenize(s: str) -> list[str]:
    s = re.sub(r"[^\w\s가-힣]", " ", (s or "").lower())
    return [w for w in s.split() if len(w) >= 2]


def _score(query: str, title: str) -> int:
    q = set(_tokenize(query))
    t = set(_tokenize(title))
    return len(q & t)


def _is_too_old_request(msg: str) -> bool:
    m = (msg or "").lower()
    # 예: "2년 전", "3년전에"
    if re.search(r"(\d+)\s*년\s*전", m):
        try:
            n = int(re.search(r"(\d+)\s*년\s*전", m).group(1))
            return n >= 2
        except Exception:
            return True
    return False


def _extract_target_date(msg: str) -> datetime | None:
    """요청에서 특정 날짜를 뽑아냄. 없으면 None."""
    m = msg or ""
    # 2026-04-21 / 2026.04.21
    m1 = re.search(r"(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})", m)
    if m1:
        y, mo, d = map(int, m1.groups())
        try:
            return datetime(y, mo, d, tzinfo=timezone.utc)
        except Exception:
            return None
    # 4월 21일
    m2 = re.search(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", m)
    if m2:
        mo, d = map(int, m2.groups())
        y = _now().year
        try:
            return datetime(y, mo, d, tzinfo=timezone.utc)
        except Exception:
            return None
    # 21일 (이번 달로 가정)
    m3 = re.search(r"(\d{1,2})\s*일", m)
    if m3:
        d = int(m3.group(1))
        now = _now()
        try:
            return datetime(now.year, now.month, d, tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _wants_summary(msg: str) -> bool:
    m = msg or ""
    return any(k in m for k in ("요약", "정리", "핵심", "한줄", "한 줄"))


def _wants_list(msg: str) -> bool:
    m = msg or ""
    return any(k in m for k in ("알려", "목록", "리스트", "뭐 올라왔", "뭐야", "공지"))


def _message_suggests_notice_scope(msg: str) -> bool:
    """공지·학사 질문일 가능성이 있으면 True (일반 잡담·다른 주제 오탐 방지). '뭐야' 단독은 넣지 않음."""
    m = (msg or "").strip().lower()
    if len(m) < 2:
        return False
    if any(k in m for k in ("요약", "정리", "핵심", "한줄", "한 줄")):
        return True
    scope = (
        "알려", "목록", "리스트", "뭐 올라왔", "올라온", "올라왔", "공지", "게시", "안내", "학사",
        "등록", "수강", "졸업", "입학", "휴학", "복학", "장학", "장학금", "교내", "동의대", "deu",
        "dess", "학기", "수업", "시험", "기말", "중간", "계절", "납부", "분할", "증명서", "서류",
        "신청", "마감", "일정", "행사", "모집", "총장", "학과", "전공", "실습", "봉사", "비교과",
        "박물관", "도서관", "기숙사", "주차", "등교", "강의", "학점", "복수전공", "전과", "대학원",
        "캠퍼스", "교수", "출석", "성적", "졸업요건", "학적", "휴강", "보강", "수강신청",
    )
    if any(k in m for k in scope):
        return True
    if re.search(r"20\d{2}", m):
        return True
    if re.search(r"\d{1,2}\s*월", m) or re.search(r"\d{4}[.\-]\d", m):
        return True
    return False


def _max_article_match_score(user_message: str, arts: list[dict]) -> int:
    return max((_score(user_message, str(a.get("title") or "")) for a in arts), default=0)


def _is_likely_unrelated_to_notices(user_message: str, arts: list[dict]) -> bool:
    if _message_suggests_notice_scope(user_message):
        return False
    return _max_article_match_score(user_message, arts) == 0


def _normalize_rag_sources(sources: list[str] | None, mid: str | None) -> list[str]:
    if sources:
        out = sorted({str(s).strip() for s in sources if str(s).strip() in ("deu", "dess")}, key=lambda x: ("deu", "dess").index(x))
        if out:
            return out
    m = (mid or "deu").strip()
    if m in ("deu", "dess"):
        return [m]
    return ["deu"]


def _load_merged_articles(*, sources: list[str], pages: int, cancel_event=None) -> tuple[list[dict], dict]:
    """여러 소스 크롤 결과를 합치고 URL 기준 중복 제거. 각 글에 _origin('deu'|'dess') 부여."""
    pages = max(1, min(20, int(pages)))
    srcs = _normalize_rag_sources(sources, None)
    if not srcs:
        srcs = ["deu"]
    combined: list[dict] = []
    bases: list[str] = []
    if len(srcs) == 1:
        s0 = srcs[0]
        arts, meta = _load_articles(source=s0, pages=pages, cancel_event=cancel_event)
        bases.append(str(meta.get("base") or ""))
        for a in arts:
            a2 = dict(a)
            a2["_origin"] = s0
            combined.append(a2)
    else:
        order = {s: i for i, s in enumerate(("deu", "dess"))}
        pending: list[tuple[str, object]] = []
        with ThreadPoolExecutor(max_workers=min(2, len(srcs))) as ex:
            for s in srcs:
                pending.append((s, ex.submit(_load_articles, source=s, pages=pages, cancel_event=cancel_event)))
        for s, fut in sorted(pending, key=lambda x: order.get(x[0], 99)):
            arts, meta = fut.result()
            bases.append(str(meta.get("base") or ""))
            for a in arts:
                a2 = dict(a)
                a2["_origin"] = s
                combined.append(a2)
    seen: set[str] = set()
    deduped: list[dict] = []
    for a in combined:
        u = str(a.get("url") or "").strip()
        if u:
            if u in seen:
                continue
            seen.add(u)
        deduped.append(a)
    merged_meta = {
        "base": " · ".join(b for b in bases if b),
        "source": "+".join(srcs),
        "mid": "Notice",
    }
    if not merged_meta["base"]:
        merged_meta["base"] = DEFAULT_DEU_NOTICE_URL if "deu" in srcs else DEFAULT_BASE
    return deduped, merged_meta


def _load_articles(*, source: str, pages: int, cancel_event=None) -> tuple[list[dict], dict]:
    """
    source: 'deu' | 'dess'
    pages: 크롤 페이지 수
    """
    source = (source or "deu").strip()
    pages = max(1, min(20, int(pages)))
    key = (source, pages)
    ts = time.time()
    cached = _CACHE.get(key)
    if cached and ts - cached[0] < _CACHE_TTL_SEC:
        return cached[1], cached[2]

    if source == "deu":
        crawl = run_deu_notice_crawl(base_url=DEFAULT_DEU_NOTICE_URL, pages=pages, limit=10, cancel_event=cancel_event)
        crawl["source"]["source"] = "deu"
    else:
        crawl = run_crawl(base=DEFAULT_BASE, mid="Notice", pages=pages, no_filter=True, fetch_body=False, headless=True, delay=0.22, cancel_event=cancel_event)
        crawl["source"]["source"] = "dess"

    arts = list(crawl.get("articles") or [])
    _CACHE[key] = (ts, arts, crawl.get("source") or {})
    return arts, (crawl.get("source") or {})


def _filter_recent(arts: list[dict]) -> list[dict]:
    cutoff = _now() - timedelta(days=MAX_AGE_DAYS)
    out: list[dict] = []
    for a in arts:
        dt = _parse_posted(str(a.get("posted") or ""))
        if dt and dt >= cutoff:
            out.append(a)
    return out


def _format_sources(arts: list[dict]) -> list[dict]:
    sources: list[dict] = []
    idx = 1
    for a in arts:
        url = str(a.get("url") or "").strip()
        if not url:
            continue
        sources.append(
            {
                "index": idx,
                "title": str(a.get("title") or "").strip(),
                "url": url,
                "posted": a.get("posted", ""),
                "author": a.get("author", ""),
            }
        )
        idx += 1
    return sources


def answer_with_rag(
    user_message: str,
    *,
    mid: str = "deu",
    sources: list[str] | None = None,
    pages: int = 1,
    enrich_bodies: bool = False,
    cancel_event=None,
) -> dict[str, Any]:
    """빠른 응답(기본) + 필요 시 요약."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 환경변수를 설정하세요.")
    if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
        return {"reply": "요청이 취소되었습니다.", "sources": [], "ingest": None}

    # 너무 오래된 범위 요청은 거절
    if _is_too_old_request(user_message):
        return {
            "reply": f"요청하신 범위가 너무 오래되었습니다. 최근 {MAX_AGE_DAYS}일 이내 공지만 조회할 수 있어요.",
            "sources": [],
            "ingest": None,
        }

    src_list = _normalize_rag_sources(sources, mid)
    source_key = "+".join(src_list)

    arts, src_meta = _load_merged_articles(sources=src_list, pages=pages, cancel_event=cancel_event)
    arts = _filter_recent(arts)
    if not arts:
        return {"reply": "최근 공지 데이터가 없습니다.", "sources": [], "ingest": None}

    if _is_likely_unrelated_to_notices(user_message, arts):
        return {
            "reply": "이 질문은 동의대 공지·학사 안내와 연관이 적어 보입니다. 등록, 수강, 공지, 일정, 장학 등 학교 관련 내용으로 질문해 주세요.",
            "sources": [],
            "notice_unrelated": True,
            "crawl_summary": {"base": src_meta.get("base", ""), "source": source_key, "pages": pages},
            "ingest": None,
        }

    target_date = _extract_target_date(user_message)
    wants_summary = _wants_summary(user_message) or bool(enrich_bodies)

    # 1) 날짜/목록 요청: 즉시 필터링
    if target_date and _wants_list(user_message):
        cutoff = _now() - timedelta(days=MAX_AGE_DAYS)
        if target_date < cutoff:
            return {
                "reply": f"{target_date.strftime('%Y-%m-%d')}은(는) 너무 오래된 날짜라 조회하지 않습니다. 최근 {MAX_AGE_DAYS}일 이내만 가능해요.",
                "sources": [],
                "ingest": None,
            }
        matched = []
        for a in arts:
            dt = _parse_posted(str(a.get("posted") or ""))
            if dt and dt.date() == target_date.date():
                matched.append(a)
        matched.sort(key=lambda a: (_parse_posted(str(a.get("posted") or "")) or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
        if not matched:
            return {
                "reply": f"{target_date.strftime('%Y-%m-%d')}에 해당하는 공지를 최근 {MAX_AGE_DAYS}일 범위에서 찾지 못했습니다.",
                "sources": [],
                "crawl_summary": {"base": src_meta.get("base", ""), "source": source_key, "pages": pages},
                "ingest": None,
            }
        top = matched[:10]
        reply = f"{target_date.strftime('%Y-%m-%d')} 공지 {len(matched)}건을 찾았습니다. (상위 {len(top)}건)\n"
        for i, a in enumerate(top, start=1):
            reply += f"- [{i}] {a.get('title','')}\n"
        sources = _format_sources(top)
        # 요약 요청이면 본문 요약(느림)
        if wants_summary:
            return _summarize_selected(user_message, top, source=source_key, cancel_event=cancel_event, src_meta=src_meta, base_pages=pages)
        return {"reply": reply.strip(), "sources": sources, "crawl_summary": {"base": src_meta.get("base", ""), "source": source_key, "pages": pages}, "ingest": None}

    # 2) 일반 검색: 제목 기반 빠른 후보 추출
    scored = sorted(arts, key=lambda a: _score(user_message, str(a.get("title") or "")), reverse=True)
    scored = [a for a in scored if _score(user_message, str(a.get("title") or "")) > 0] or scored
    picked = scored[:6]
    if wants_summary:
        return _summarize_selected(user_message, picked, source=source_key, cancel_event=cancel_event, src_meta=src_meta, base_pages=pages)

    # 요약이 아니면 “관련 공지 후보”를 빠르게 제시
    reply = "관련 공지 후보를 찾았습니다. 아래 목록에서 원하는 항목을 말해주면 요약/정리해드릴게요.\n"
    for i, a in enumerate(picked, start=1):
        reply += f"- [{i}] {a.get('posted','')} · {a.get('title','')}\n"
    return {
        "reply": reply.strip(),
        "sources": _format_sources(picked),
        "crawl_summary": {"base": src_meta.get("base", ""), "source": source_key, "pages": pages},
        "ingest": None,
    }


def _summarize_selected(
    user_message: str,
    picked: list[dict],
    *,
    source: str,  # 표시용: "deu", "dess", "deu+dess" 등
    cancel_event=None,
    src_meta: dict | None = None,
    base_pages: int = 4,
) -> dict[str, Any]:
    """선택된 공지 몇 개만 본문을 가져와 요약(느림)."""
    src_meta = src_meta or {}
    if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
        return {"reply": "요청이 취소되었습니다.", "sources": [], "ingest": None}

    # 본문 수집: DESS 글만 Selenium으로 본문 수집. 대표 공지는 제목·메타 위주.
    bodies: list[str] = []
    if any(str(a.get("_origin") or "") == "dess" for a in picked):
        driver = build_driver(headless=True)
        try:
            for a in picked[:3]:
                if str(a.get("_origin") or "") != "dess":
                    continue
                if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                    break
                url = str(a.get("url") or "")
                if not url:
                    continue
                bodies.append(fetch_article_body(driver, url)[:3500])
        finally:
            driver.quit()

    prompt = (
        "아래 공지 내용을 바탕으로 사용자의 요청에 맞게 한국어로 요약/정리하세요.\n"
        "규칙: 없는 내용은 추측하지 말고 '공지에서 확인되지 않습니다'라고 말하세요.\n\n"
        f"사용자 요청:\n{user_message}\n\n"
        "공지 본문/정보:\n"
        + "\n\n---\n\n".join(bodies) if bodies else
        f"사용자 요청:\n{user_message}\n\n공지 제목/메타(본문은 수집되지 않았을 수 있음):\n"
        + "\n".join([f"- {a.get('posted','')} {a.get('title','')}" for a in picked[:6]])
    )
    llm = _llm()
    msg = llm.invoke(prompt)
    reply = str(getattr(msg, "content", msg) or "").strip()
    return {
        "reply": reply,
        "sources": _format_sources(picked[:6]),
        "crawl_summary": {"base": src_meta.get("base", ""), "source": source, "pages": base_pages},
        "ingest": None,
    }