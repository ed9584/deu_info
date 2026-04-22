#!/usr/bin/env python3
"""DESS Nexus 로컬 웹 UI (공지 목록 + AI 채팅)."""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime

from flask import Flask, jsonify, render_template_string, request

from deu_nexus import APP_NAME, APP_NAME_KO
from deu_nexus.crawler import DEFAULT_BASE, DEFAULT_DEU_NOTICE_URL, run_crawl, run_deu_notice_crawl

app = Flask(__name__)

# ----- chat jobs (server-side cancel) -----
import threading
import uuid

_CHAT_JOBS: dict[str, dict] = {}
_CHAT_LOCK = threading.Lock()


def _new_job_id() -> str:
    return uuid.uuid4().hex

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>""" + APP_NAME + """</title>
  <style>
    :root { --bg: #0f1419; --card: #1a2332; --text: #e7ecf3; --muted: #8b9aad; --accent: #5b9fd4; --border: #2d3a4d; --chat: #121820; }
    html[data-theme="light"] { --bg: #f6f7fb; --card: #ffffff; --text: #0f172a; --muted: #475569; --accent: #2563eb; --border: #e2e8f0; --chat: #f1f5f9; }
    * { box-sizing: border-box; }
    body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; margin: 0; background: var(--bg); color: var(--text); line-height: 1.5; }
    .layout { display: grid; grid-template-columns: 1fr minmax(280px, 380px); gap: 0; min-height: 100vh; transition: grid-template-columns .15s ease; }
    @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } .chat-panel { border-left: none; border-top: 1px solid var(--border); max-height: none; } }
    .main { padding: 1.25rem; overflow: auto; }
    .chat-panel { border-left: 1px solid var(--border); background: var(--chat); display: flex; flex-direction: column; max-height: 100vh; position: sticky; top: 0; }
    h1 { font-size: 1.2rem; font-weight: 600; margin: 0 0 0.25rem; }
    .subtitle { font-size: 0.8rem; color: var(--muted); margin: 0 0 1rem; }
    h2 { font-size: 0.95rem; color: var(--muted); margin: 0 0 0.5rem; font-weight: 600; }
    form { display: flex; gap: 0.6rem; align-items: center; margin-bottom: 1rem; padding: 0.9rem; background: var(--card); border-radius: 10px; border: 1px solid var(--border); }
    label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.8rem; color: var(--muted); }
    input[type="text"], select { padding: 0.55rem 0.65rem; border-radius: 8px; border: 1px solid var(--border); background: var(--bg); color: var(--text); }
    html[data-theme="light"] input[type="text"], html[data-theme="light"] select { background: #ffffff; }
    input[type="text"] { min-width: 18rem; flex: 1; }
    .spacer { flex: 1; }
    input[type="checkbox"] { width: 1rem; height: 1rem; }
    button, .btn { padding: 0.5rem 1rem; border-radius: 8px; border: none; background: var(--accent); color: #ffffff; font-weight: 600; cursor: pointer; font-size: 0.9rem; }
    .btn-ghost { background: transparent; border: 1px solid var(--border); color: var(--text); }
    button:hover, .btn:hover { filter: brightness(1.08); }
    button:disabled { opacity: 0.55; cursor: not-allowed; }
    .meta { color: var(--muted); font-size: 0.85rem; margin-bottom: 0.75rem; }
    table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
    th, td { text-align: left; padding: 0.5rem 0.4rem; border-bottom: 1px solid var(--border); vertical-align: top; }
    th { color: var(--muted); font-weight: 500; }
    tr:hover td { background: rgba(91, 159, 212, 0.06); }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .tag { display: inline-block; padding: 0.12rem 0.4rem; border-radius: 4px; font-size: 0.72rem; background: #243044; color: #c5d4e8; }
    .err { color: #f08080; margin-bottom: 0.75rem; font-size: 0.9rem; }
    .chat-head { padding: 1rem 1rem 0.5rem; border-bottom: 1px solid var(--border); }
    .chat-hint { font-size: 0.75rem; color: var(--muted); margin-top: 0.35rem; }
    .msgs { flex: 1; overflow: auto; padding: 0.75rem 1rem; display: flex; flex-direction: column; gap: 0.75rem; }
    .bubble { padding: 0.65rem 0.75rem; border-radius: 10px; font-size: 0.88rem; max-width: 100%; white-space: pre-wrap; word-break: break-word; }
    .bubble.user { align-self: flex-end; background: color-mix(in srgb, var(--accent) 18%, var(--card) 82%); }
    .bubble.ai { align-self: stretch; background: var(--card); border: 1px solid var(--border); }
    .bubble .src { margin-top: 0.6rem; padding-top: 0.6rem; border-top: 1px solid var(--border); font-size: 0.8rem; color: var(--muted); }
    .bubble .src a { display: block; margin: 0.2rem 0; }
    .chat-input { padding: 0.75rem 1rem 1rem; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 0.5rem; }
    textarea { width: 100%; min-height: 4.5rem; resize: vertical; padding: 0.55rem 0.65rem; border-radius: 8px; border: 1px solid var(--border); background: var(--bg); color: var(--text); font-family: inherit; font-size: 0.9rem; }
    .row { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
    .pill { font-size: 0.72rem; color: var(--muted); }
    .pager { display:flex; gap:0.35rem; justify-content:center; padding: 0.9rem 0; }
    .pg { background: transparent; border: 1px solid var(--border); color: var(--text); padding: 0.35rem 0.65rem; border-radius: 8px; cursor: pointer; }
    .pg.on { background: rgba(91,159,212,0.18); border-color: rgba(91,159,212,0.55); }
    .loading { color: var(--muted); font-size: 0.85rem; }
    .topbar { display:flex; align-items:flex-end; justify-content:space-between; gap: 0.75rem; margin-bottom: 0.75rem; }
    .top-actions { display:flex; gap:0.5rem; align-items:center; }
    .chat-hidden .layout { grid-template-columns: 1fr 0px; }
    .chat-hidden .chat-panel { display:none; }
  </style>
</head>
<body>
  <div class="layout">
    <div class="main">
      <div class="topbar">
        <div>
          <h1>""" + APP_NAME_KO + """</h1>
          <p class="subtitle">대표 공지(기본) · DESS(옵션) · 검색 · RAG</p>
        </div>
        <div class="top-actions">
          <button type="button" class="btn-ghost" id="themeBtn">테마</button>
          <button type="button" class="btn-ghost" id="chatToggleBtn">AI 챗</button>
        </div>
      </div>
      <form id="searchForm">
        <select id="sourceSel" title="소스 선택">
          <option value="deu">대표 공지</option>
          <option value="dess">학생서비스센터(DESS)</option>
        </select>
        <input id="kw" type="text" placeholder="검색어를 입력하세요 (예: 일정, 복학, 졸업)" autocomplete="off">
        <button type="submit">검색</button>
        <button type="button" class="btn-ghost" id="clearBtn">초기화</button>
      </form>
      <p class="meta" id="metaLine"></p>
      <p class="loading" id="loading" style="display:none;">불러오는 중…</p>
      <table>
        <thead>
          <tr>
            <th>번호</th>
            <th>제목</th>
            <th>글쓴이</th>
            <th>날짜</th>
            <th>조회</th>
          </tr>
        </thead>
        <tbody id="listBody"></tbody>
      </table>
      <div class="pager" id="pager"></div>
    </div>
    <aside class="chat-panel">
      <div class="chat-head">
        <h2>AI 질문</h2>
        <p class="chat-hint">공지 내용을 바탕으로 답하고, 아래에 출처 링크를 함께 보여줍니다. (API 키는 서버에만 설정)</p>
        <div class="row">
          <label class="pill">공지 범위(페이지)
            <input type="number" id="aiPages" min="1" max="20" value="4" style="width:4rem;">
          </label>
          <label class="pill" style="flex-direction:row;align-items:center;gap:0.35rem;">
            <input type="checkbox" id="aiDeep"> 본문까지 포함
          </label>
        </div>
      </div>
      <div class="msgs" id="msgs"></div>
      <div class="chat-input">
        <textarea id="q" placeholder="예: 2026학년도 2학기 복학 일정이 뭐야?"></textarea>
        <div class="row" style="justify-content: space-between;">
          <button type="button" id="send">보내기</button>
          <button type="button" class="btn-ghost" id="cancelBtn" style="display:none;">정지</button>
        </div>
        <span class="pill" id="chatStatus"></span>
      </div>
    </aside>
  </div>
  <script>
  // ----- list (검색 + 페이지네이션) -----
  const listBody = document.getElementById('listBody');
  const pager = document.getElementById('pager');
  const kw = document.getElementById('kw');
  const metaLine = document.getElementById('metaLine');
  const loading = document.getElementById('loading');
  const clearBtn = document.getElementById('clearBtn');
  const searchForm = document.getElementById('searchForm');
  const sourceSel = document.getElementById('sourceSel');
  const PAGE_SIZE = 20;
  const SCAN_PAGES = 3; // 소스에서 몇 페이지까지 긁어서 검색 풀을 만들지
  let currentPage = 1;

  function esc(s){ return (s||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'); }

  function renderPager(totalPages) {
    pager.innerHTML = '';
    const n = Math.max(1, totalPages || 1);
    for (let p = 1; p <= n; p++) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'pg' + (p === currentPage ? ' on' : '');
      b.textContent = String(p);
      b.addEventListener('click', () => loadPage(p));
      pager.appendChild(b);
    }
  }

  function renderRows(rows) {
    if (!rows || rows.length === 0) {
      listBody.innerHTML = '<tr><td colspan="5" class="loading">결과가 없습니다.</td></tr>';
      return;
    }
    listBody.innerHTML = rows.map(a => {
      const no = a.is_notice ? '<span class="tag">공지</span>' : esc(a.list_no);
      const title = '<a href=\"' + esc(a.url) + '\" target=\"_blank\" rel=\"noopener\">' + esc(a.title) + '</a>';
      return '<tr>' +
        '<td>' + no + '</td>' +
        '<td>' + title + '</td>' +
        '<td>' + esc(a.author) + '</td>' +
        '<td>' + esc(a.posted) + '</td>' +
        '<td>' + esc(a.views) + '</td>' +
      '</tr>';
    }).join('');
  }

  async function loadPage(p) {
    currentPage = p;
    renderPager(1);
    loading.style.display = 'block';
    metaLine.textContent = '';
    try {
      const q = (kw.value || '').trim();
      const src = (sourceSel.value || 'deu');
      const url = new URL('/api/list', window.location.origin);
      url.searchParams.set('page', String(p));
      url.searchParams.set('scan_pages', String(SCAN_PAGES));
      url.searchParams.set('page_size', String(PAGE_SIZE));
      url.searchParams.set('source', src);
      if (q) url.searchParams.set('q', q);
      const r = await fetch(url.toString(), { method: 'GET' });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
      renderRows(j.articles || []);
      renderPager(j.total_pages || 1);
      const ss = j.source || {};
      metaLine.textContent = `출처: ${ss.base || ''} · 소스=${ss.source || ''} · (스캔 ${ss.pages_scanned || SCAN_PAGES}p) · 결과 ${j.count_all || 0}건 · 페이지 ${j.page || p}/${j.total_pages || 1}`;
    } catch (e) {
      listBody.innerHTML = '<tr><td colspan="5" class="err">오류: ' + esc(e.message) + '</td></tr>';
    } finally {
      loading.style.display = 'none';
    }
  }

  searchForm.addEventListener('submit', (e) => { e.preventDefault(); loadPage(1); });
  clearBtn.addEventListener('click', () => { kw.value=''; loadPage(1); });
  sourceSel.addEventListener('change', () => { loadPage(1); });
  renderPager(1);
  loadPage(1);

  // ----- theme + chat toggle -----
  const themeBtn = document.getElementById('themeBtn');
  const chatToggleBtn = document.getElementById('chatToggleBtn');
  function setTheme(t) {
    document.documentElement.dataset.theme = t;
    localStorage.setItem('theme', t);
  }
  const savedTheme = localStorage.getItem('theme');
  if (savedTheme) setTheme(savedTheme);
  else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) setTheme('light');
  themeBtn.addEventListener('click', () => {
    const cur = document.documentElement.dataset.theme || 'dark';
    setTheme(cur === 'light' ? 'dark' : 'light');
  });

  function setChatVisible(v){
    document.body.classList.toggle('chat-hidden', !v);
    localStorage.setItem('chat_visible', v ? '1' : '0');
  }
  const chatSaved = localStorage.getItem('chat_visible');
  setChatVisible(chatSaved === null ? false : chatSaved === '1'); // 기본은 숨김
  chatToggleBtn.addEventListener('click', () => {
    setChatVisible(document.body.classList.contains('chat-hidden'));
  });

  const msgs = document.getElementById('msgs');
  const q = document.getElementById('q');
  const send = document.getElementById('send');
  const cancelBtn = document.getElementById('cancelBtn');
  const statusEl = document.getElementById('chatStatus');
  const aiPages = document.getElementById('aiPages');
  const aiDeep = document.getElementById('aiDeep');
  let chatAbort = null;
  let chatTypingEl = null;
  let chatJobId = null;

  function addBubble(text, who) {
    const d = document.createElement('div');
    d.className = 'bubble ' + who;
    d.textContent = text;
    msgs.appendChild(d);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function addAiBubble(reply, sources) {
    const d = document.createElement('div');
    d.className = 'bubble ai';
    const t = document.createElement('div');
    t.textContent = reply;
    d.appendChild(t);
    const cleanSources = (sources || []).filter(x => x && typeof x === 'object' && x.url);
    if (cleanSources.length) {
      const s = document.createElement('div');
      s.className = 'src';
      s.appendChild(document.createTextNode('출처:'));
      cleanSources.forEach(function (x) {
        const a = document.createElement('a');
        a.href = x.url;
        a.target = '_blank';
        a.rel = 'noopener';
        a.textContent = '[' + (x.index || '') + '] ' + (x.title || x.url);
        s.appendChild(a);
      });
      d.appendChild(s);
    }
    msgs.appendChild(d);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function addTypingBubble() {
    const d = document.createElement('div');
    d.className = 'bubble ai';
    d.dataset.typing = '1';
    d.textContent = '답변 생성 중…';
    msgs.appendChild(d);
    msgs.scrollTop = msgs.scrollHeight;
    return d;
  }

  function resetChatUi(prevBtnText) {
    send.disabled = false;
    send.textContent = prevBtnText || '보내기';
    statusEl.textContent = '';
    cancelBtn.style.display = 'none';
    chatAbort = null;
    if (chatTypingEl && chatTypingEl.parentNode) chatTypingEl.parentNode.removeChild(chatTypingEl);
    chatTypingEl = null;
  }

  async function doSend() {
    const text = (q.value || '').trim();
    if (!text) return;
    if (chatAbort) return; // 이미 처리 중이면 무시
    addBubble(text, 'user');
    q.value = '';
    send.disabled = true;
    const prevBtnText = send.textContent;
    send.textContent = '처리 중…';
    statusEl.textContent = 'AI가 답변을 만드는 중입니다…';
    chatTypingEl = addTypingBubble();
    cancelBtn.style.display = 'inline-block';
    chatAbort = new AbortController();
    try {
      const mid = (sourceSel && sourceSel.value) ? sourceSel.value : 'deu';
      // 1) 서버에 job 생성 요청
      const r = await fetch('/api/chat/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: chatAbort.signal,
        body: JSON.stringify({
          message: text,
          mid: mid,
          pages: parseInt(aiPages.value, 10) || 4,
          deep: !!aiDeep.checked
        })
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
      chatJobId = j.job_id;

      // 2) 완료될 때까지 폴링
      while (true) {
        await new Promise(res => setTimeout(res, 700));
        const s = await fetch('/api/chat/status?job_id=' + encodeURIComponent(chatJobId), { signal: chatAbort.signal });
        const sj = await s.json();
        if (!s.ok) throw new Error(sj.error || ('HTTP ' + s.status));
        if (sj.status === 'running') continue;
        if (sj.status === 'cancelled') {
          addBubble('요청을 정지했습니다.', 'ai');
          break;
        }
        if (sj.status === 'error') {
          throw new Error(sj.error || '서버 오류');
        }
        if (sj.status === 'done') {
          addAiBubble(sj.reply || '', sj.sources || []);
          break;
        }
        throw new Error('알 수 없는 상태: ' + sj.status);
      }
    } catch (e) {
      if (e && e.name === 'AbortError') {
        addBubble('요청을 정지했습니다.', 'ai');
      } else {
        addBubble('오류: ' + e.message, 'ai');
      }
    } finally {
      resetChatUi(prevBtnText);
    }
  }

  cancelBtn.addEventListener('click', () => {
    // 서버 취소 요청 + 클라이언트 요청 중단
    if (chatJobId) {
      fetch('/api/chat/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: chatJobId })
      }).catch(()=>{});
    }
    if (chatAbort) chatAbort.abort();
  });

  send.addEventListener('click', doSend);
  q.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSend(); }
  });
  </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(PAGE_TEMPLATE)


@app.get("/api/list")
def api_list():
    source = (request.args.get("source") or "deu").strip()
    try:
        page = int(request.args.get("page") or "1")
    except ValueError:
        page = 1
    page = max(1, min(200, page))
    q = (request.args.get("q") or "").strip()
    try:
        scan_pages = int(request.args.get("scan_pages") or "3")
    except ValueError:
        scan_pages = 3
    scan_pages = max(1, min(20, scan_pages))
    try:
        page_size = int(request.args.get("page_size") or "20")
    except ValueError:
        page_size = 20
    page_size = max(5, min(50, page_size))

    try:
        data = _search_aggregated(mid=source, q=q, result_page=page, scan_pages=scan_pages, page_size=page_size)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify(data)


_CACHE: dict[tuple[str, int], dict] = {}
_CACHE_TTL_SEC = 25.0


def _parse_posted(s: str) -> float:
    s = (s or "").strip()
    # DESS: YYYY.MM.DD, 대표 공지: YYYY-MM-DD
    try:
        dt = datetime.strptime(s, "%Y.%m.%d")
        return dt.timestamp()
    except Exception:
        pass
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        return dt.timestamp()
    except Exception:
        return 0.0


def _search_aggregated(*, mid: str, q: str, result_page: int, scan_pages: int, page_size: int) -> dict:
    """
    게시판 1..scan_pages를 긁어서 하나로 합친 뒤
    - 최신순 정렬
    - q가 있으면 제목에 포함된 것만 필터
    - 결과를 page_size로 페이지네이션
    """
    source = (mid or "").strip() or "Notice"
    # source 구분: 대표 공지(deu) / DESS(dess)
    # mid 파라미터는 DESS에만 의미가 있어 기본 Notice로 둠
    if source not in ("deu", "dess"):
        source = "deu"

    key = (source, scan_pages)
    now = time.time()
    cached = _CACHE.get(key)
    if cached and (now - float(cached.get("_ts", 0.0)) < _CACHE_TTL_SEC):
        crawl = cached["crawl"]
    else:
        if source == "deu":
            crawl = run_deu_notice_crawl(base_url=DEFAULT_DEU_NOTICE_URL, pages=scan_pages, limit=10)
            crawl["source"]["source"] = "deu"
        else:
            crawl = run_crawl(base=DEFAULT_BASE, mid="Notice", pages=scan_pages, no_filter=True, fetch_body=False, headless=True, delay=0.35)
            crawl["source"]["source"] = "dess"
        _CACHE[key] = {"_ts": now, "crawl": crawl}

    arts: list[dict] = list(crawl.get("articles") or [])
    qq = (q or "").strip().lower()
    if qq:
        arts = [a for a in arts if qq in str(a.get("title", "")).lower()]

    # 최신순(날짜 DESC), 같은 날짜면 공지 먼저/제목
    arts.sort(
        key=lambda a: (
            _parse_posted(str(a.get("posted") or "")),
            1 if a.get("is_notice") else 0,
            str(a.get("title") or ""),
        ),
        reverse=True,
    )

    count_all = len(arts)
    total_pages = max(1, (count_all + page_size - 1) // page_size)
    rp = max(1, min(total_pages, int(result_page)))
    start = (rp - 1) * page_size
    page_items = arts[start : start + page_size]

    return {
        "source": {
            "base": crawl.get("source", {}).get("base", ""),
            "source": crawl.get("source", {}).get("source", ""),
            "mid": crawl.get("source", {}).get("mid", ""),
            "pages_scanned": scan_pages,
        },
        "q": q,
        "page": rp,
        "page_size": page_size,
        "total_pages": total_pages,
        "count_all": count_all,
        "articles": page_items,
        "count_total": count_all,
        "count_matched": len(page_items),
    }


@app.post("/api/chat/start")
def api_chat_start():
    body = request.get_json(silent=True) or {}
    msg = (body.get("message") or "").strip()
    if not msg:
        return jsonify({"error": "message이 비었습니다."}), 400

    mid = (body.get("mid") or "Notice").strip() or "Notice"
    try:
        pages = int(body.get("pages", 4))
    except (TypeError, ValueError):
        pages = 4
    pages = max(1, min(20, pages))
    deep = bool(body.get("deep"))

    job_id = _new_job_id()
    cancel_event = threading.Event()
    with _CHAT_LOCK:
        _CHAT_JOBS[job_id] = {
            "status": "running",
            "cancel": cancel_event,
            "result": None,
            "error": None,
        }

    def _run() -> None:
        try:
            # 지연 로딩: 서버 시작 시 RAG/pandas/numpy import 지연
            from deu_nexus.chat import answer_with_sources_cancellable

            out = answer_with_sources_cancellable(
                msg,
                mid=mid,
                pages=pages,
                include_article_bodies=deep,
                cancel_event=cancel_event,
            )
            with _CHAT_LOCK:
                if cancel_event.is_set():
                    _CHAT_JOBS[job_id]["status"] = "cancelled"
                else:
                    _CHAT_JOBS[job_id]["status"] = "done"
                    _CHAT_JOBS[job_id]["result"] = out
        except Exception as e:
            with _CHAT_LOCK:
                if cancel_event.is_set():
                    _CHAT_JOBS[job_id]["status"] = "cancelled"
                else:
                    _CHAT_JOBS[job_id]["status"] = "error"
                    _CHAT_JOBS[job_id]["error"] = str(e)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"job_id": job_id})


@app.get("/api/chat/status")
def api_chat_status():
    job_id = (request.args.get("job_id") or "").strip()
    if not job_id:
        return jsonify({"error": "job_id가 필요합니다."}), 400
    with _CHAT_LOCK:
        job = _CHAT_JOBS.get(job_id)
        if not job:
            return jsonify({"error": "job_id를 찾을 수 없습니다."}), 404
        status = job["status"]
        if status == "done":
            out = job.get("result") or {}
            return jsonify(
                {
                    "status": "done",
                    "reply": out.get("reply", ""),
                    "sources": out.get("sources") or [],
                    "crawl_summary": out.get("crawl_summary"),
                    "ingest": out.get("ingest"),
                }
            )
        if status == "error":
            return jsonify({"status": "error", "error": job.get("error") or "서버 오류"}), 500
        if status == "cancelled":
            return jsonify({"status": "cancelled"})
        return jsonify({"status": "running"})


@app.post("/api/chat/cancel")
def api_chat_cancel():
    body = request.get_json(silent=True) or {}
    job_id = (body.get("job_id") or "").strip()
    if not job_id:
        return jsonify({"error": "job_id가 필요합니다."}), 400
    with _CHAT_LOCK:
        job = _CHAT_JOBS.get(job_id)
        if not job:
            return jsonify({"error": "job_id를 찾을 수 없습니다."}), 404
        job["cancel"].set()
        job["status"] = "cancelled"
    return jsonify({"status": "cancelled"})


@app.get("/api/debug/env")
def api_debug_env():
    """로컬 디버그용: 서버가 환경변수를 보는지 확인(키 원문은 절대 반환하지 않음)."""
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    prefix = ""
    if key:
        prefix = key[:7] + "…"  # 예: sk-proj…
    return jsonify(
        {
            "openai_api_key": {
                "set": bool(key),
                "prefix": prefix,
                "length": len(key),
            }
        }
    )


def main() -> None:
    port = int(os.environ.get("PORT", "5050"))
    host = os.environ.get("HOST", "127.0.0.1")
    open_b = os.environ.get("OPEN_BROWSER", "1").strip() not in ("0", "false", "no")
    if open_b:
        import threading
        import time
        import webbrowser

        def _open() -> None:
            time.sleep(0.6)
            webbrowser.open(f"http://{host}:{port}/")

        threading.Thread(target=_open, daemon=True).start()

    print(f"{APP_NAME} — http://{host}:{port}/  (종료: Ctrl+C)", file=sys.stderr)
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
