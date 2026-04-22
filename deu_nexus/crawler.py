"""Selenium + BeautifulSoup — DESS XE 게시판 목록·본문 수집."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

DEFAULT_BASE = "https://dess.deu.ac.kr/"
DEFAULT_DEU_NOTICE_URL = "https://www.deu.ac.kr/www/deu-notice.do"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class ArticleRow:
    list_no: str
    title: str
    url: str
    document_srl: str | None
    author: str
    posted: str
    views: str
    is_notice: bool


def build_driver(*, headless: bool = True) -> WebDriver:
    """Chrome 드라이버 (Selenium Manager가 chromedriver를 맞춤)."""
    from selenium import webdriver

    opts = ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument(f"--user-agent={DEFAULT_USER_AGENT}")
    opts.add_argument("--lang=ko-KR")
    return webdriver.Chrome(options=opts)


def _wait_page(driver: WebDriver, css: str, timeout: float = 20.0) -> None:
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, css))
    )


def fetch_page_html(driver: WebDriver, url: str, *, wait_css: str = "body") -> str:
    """한 URL을 열고 로딩 후 page_source 반환."""
    driver.get(url)
    _wait_page(driver, wait_css)
    time.sleep(0.15)
    return driver.page_source


def _text(el) -> str:
    return " ".join((el.get_text() or "").split())


def _extract_document_srl(href: str) -> str | None:
    if not href:
        return None
    q = parse_qs(urlparse(href).query)
    srl = q.get("document_srl", [None])[0]
    return str(srl) if srl else None


def parse_list_page(html: str, list_url: str) -> list[ArticleRow]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.bd_tb_lst.bd_tb") or soup.select_one("table.bd_tb_lst")
    if not table:
        return []

    rows: list[ArticleRow] = []
    for tr in table.select("tbody tr"):
        title_td = tr.select_one("td.title")
        if not title_td:
            continue
        a = title_td.select_one("a[href]")
        if not a:
            continue
        href = a.get("href") or ""
        abs_url = urljoin(list_url, href)
        no_td = tr.select_one("td.no")
        author_td = tr.select_one("td.author")
        time_td = tr.select_one("td.time")
        view_td = tr.select_one("td.m_no")
        rows.append(
            ArticleRow(
                list_no=_text(no_td) if no_td else "",
                title=_text(a),
                url=abs_url,
                document_srl=_extract_document_srl(abs_url),
                author=_text(author_td) if author_td else "",
                posted=_text(time_td) if time_td else "",
                views=_text(view_td) if view_td else "",
                is_notice="notice" in (tr.get("class") or []),
            )
        )
    return rows


def fetch_url_html(url: str) -> str:
    """간단 GET (대표 홈페이지 공지처럼 정적 페이지용)."""
    req = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with urlopen(req, timeout=30) as r:  # nosec - controlled URL
        data = r.read()
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return data.decode(errors="replace")


def parse_deu_notice_list_page(html: str, base_url: str) -> list[ArticleRow]:
    """
    동의대 대표 홈페이지 공지 목록 파싱.
    - URL 예: https://www.deu.ac.kr/www/deu-notice.do
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table")
    if not table:
        return []

    rows: list[ArticleRow] = []
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        no = _text(tds[0])
        title_a = tds[1].select_one("a[href]")
        title = _text(title_a) if title_a else _text(tds[1])
        href = title_a.get("href") if title_a else ""
        abs_url = urljoin(base_url, href)
        author = _text(tds[2])
        posted = _text(tds[3])
        views = _text(tds[-1])
        rows.append(
            ArticleRow(
                list_no=no,
                title=title,
                url=abs_url,
                document_srl=_extract_document_srl(abs_url),
                author=author,
                posted=posted,
                views=views,
                is_notice=False,
            )
        )
    return rows


def run_deu_notice_crawl(
    *,
    base_url: str = DEFAULT_DEU_NOTICE_URL,
    pages: int = 3,
    limit: int = 10,
) -> dict:
    """
    대표 홈페이지 공지 목록을 pages만큼 수집.
    deu-notice는 offset/limit 기반이라 page=1..N을 offset으로 변환.
    """
    pages = max(1, min(50, int(pages)))
    limit = max(5, min(50, int(limit)))
    all_rows: list[ArticleRow] = []
    for p in range(1, pages + 1):
        offset = (p - 1) * limit
        url = f"{base_url}?article.offset={offset}&articleLimit={limit}"
        html = fetch_url_html(url)
        rows = parse_deu_notice_list_page(html, base_url)
        if not rows:
            break
        all_rows.extend(rows)

    out = [asdict(r) for r in all_rows]
    return {
        "source": {"base": base_url, "mid": "deu-notice", "pages_scanned": pages},
        "count_total": len(all_rows),
        "count_matched": len(out),
        "articles": out,
    }


def fetch_list(
    driver: WebDriver,
    *,
    base: str,
    mid: str,
    page: int,
) -> tuple[str, str]:
    base = base.rstrip("/") + "/"
    list_url = f"{base}?mid={mid}&page={page}"
    html = fetch_page_html(driver, list_url, wait_css="table.bd_tb_lst")
    return html, list_url


def fetch_article_body(driver: WebDriver, url: str) -> str:
    driver.get(url)
    try:
        WebDriverWait(driver, 18).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.rd_body, article, #content"))
        )
    except Exception:
        WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
    time.sleep(0.12)
    html = driver.page_source
    soup = BeautifulSoup(html, "lxml")
    doc = soup.select_one("div.rd_body") or soup.select_one("article") or soup.select_one("#content")
    if not doc:
        return ""
    for tag in doc.select("script, style"):
        tag.decompose()
    text = doc.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def keyword_match(
    title: str,
    keywords: Iterable[str],
    *,
    match_all: bool,
) -> bool:
    t = title.lower()
    ks = [k.strip().lower() for k in keywords if k.strip()]
    if not ks:
        return True
    if match_all:
        return all(k in t for k in ks)
    return any(k in t for k in ks)


def run_crawl(
    *,
    base: str = DEFAULT_BASE,
    mid: str = "Notice",
    pages: int = 3,
    delay: float = 0.8,
    keywords: list[str] | None = None,
    match_all: bool = False,
    no_filter: bool = False,
    fetch_body: bool = False,
    headless: bool = True,
) -> dict:
    """크롤 실행 후 JSON 직렬화 가능한 dict 반환."""
    driver = build_driver(headless=headless)
    try:
        all_rows: list[ArticleRow] = []
        for page in range(1, max(1, pages) + 1):
            html, list_url = fetch_list(driver, base=base, mid=mid, page=page)
            rows = parse_list_page(html, list_url)
            if not rows:
                break
            all_rows.extend(rows)
            if page < pages:
                time.sleep(max(0.0, delay))

        kw = [] if no_filter else (keywords or ["키스톤", "캡스톤", "디자인", "협업"])
        matched = [r for r in all_rows if keyword_match(r.title, kw, match_all=match_all)]

        out: list[dict] = []
        for r in matched:
            d = asdict(r)
            if fetch_body:
                time.sleep(max(0.0, delay))
                d["body"] = fetch_article_body(driver, r.url)
            out.append(d)

        return {
            "source": {"base": base, "mid": mid, "pages_scanned": pages},
            "count_total": len(all_rows),
            "count_matched": len(matched),
            "articles": out,
        }
    finally:
        driver.quit()


def run_list_page(
    *,
    base: str = DEFAULT_BASE,
    mid: str = "Notice",
    page: int = 1,
    keywords: list[str] | None = None,
    match_all: bool = False,
    no_filter: bool = True,
    fetch_body: bool = False,
    headless: bool = True,
) -> dict:
    """게시판 특정 페이지 1장을 가져와(필요 시) 필터링해서 반환."""
    driver = build_driver(headless=headless)
    try:
        html, list_url = fetch_list(driver, base=base, mid=mid, page=max(1, int(page)))
        rows = parse_list_page(html, list_url)
        kw = [] if no_filter else (keywords or [])
        matched = [r for r in rows if keyword_match(r.title, kw, match_all=match_all)]
        out: list[dict] = []
        for r in matched:
            d = asdict(r)
            if fetch_body:
                d["body"] = fetch_article_body(driver, r.url)
            out.append(d)
        return {
            "source": {"base": base, "mid": mid, "page": max(1, int(page))},
            "count_total": len(rows),
            "count_matched": len(out),
            "articles": out,
        }
    finally:
        driver.quit()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="동의대 DESS 등 XE 게시판 공지 목록 수집 (Selenium + 키워드 필터)",
    )
    p.add_argument("--base", default=DEFAULT_BASE, help=f"사이트 베이스 URL (기본: {DEFAULT_BASE})")
    p.add_argument("--mid", default="Notice", help="XE 게시판 mid (기본: Notice)")
    p.add_argument("--pages", type=int, default=3, help="읽을 목록 페이지 수 (기본: 3)")
    p.add_argument("--delay", type=float, default=0.8, help="요청 간 초 단위 딜레이 (기본: 0.8)")
    p.add_argument(
        "--keywords",
        nargs="*",
        default=["키스톤", "캡스톤", "디자인", "협업"],
        help="제목에 포함할 키워드 (하나라도 포함 시 매칭)",
    )
    p.add_argument("--match-all", action="store_true", help="키워드를 제목에 모두 포함할 때만 매칭")
    p.add_argument("--no-filter", action="store_true", help="키워드 필터 없이 전체 목록 수집")
    p.add_argument("--fetch-body", action="store_true", help="매칭 글 본문까지 Selenium으로 방문")
    p.add_argument("--no-headless", action="store_true", help="브라우저 창 표시 (디버그)")
    p.add_argument("-o", "--output", help="JSON 저장 경로 (미지정 시 표준 출력)")
    args = p.parse_args(argv)

    payload = run_crawl(
        base=args.base,
        mid=args.mid,
        pages=args.pages,
        delay=args.delay,
        keywords=list(args.keywords),
        match_all=args.match_all,
        no_filter=args.no_filter,
        fetch_body=args.fetch_body,
        headless=not args.no_headless,
    )

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_BASE",
    "DEFAULT_DEU_NOTICE_URL",
    "DEFAULT_USER_AGENT",
    "ArticleRow",
    "build_driver",
    "fetch_page_html",
    "fetch_url_html",
    "fetch_list",
    "fetch_article_body",
    "parse_deu_notice_list_page",
    "parse_list_page",
    "run_crawl",
    "run_list_page",
    "run_deu_notice_crawl",
]