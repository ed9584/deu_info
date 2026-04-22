#!/usr/bin/env python3
"""DESS Nexus 로컬 웹 UI (공지 목록 + AI 채팅)."""

from __future__ import annotations

import os
import sys

from flask import Flask, jsonify, render_template_string, request

from deu_nexus import APP_NAME, APP_NAME_KO
from deu_nexus.chat import answer_with_sources
from deu_nexus.crawler import run_list_page

app = Flask(__name__)

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>""" + APP_NAME + """</title>
  <style>
    :root { --bg: #0f1419; --card: #1a2332; --text: #e7ecf3; --muted: #8b9aad; --accent: #5b9fd4; --border: #2d3a4d; --chat: #121820; }
    * { box-sizing: border-box; }
    body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; margin: 0; background: var(--bg); color: var(--text); line-height: 1.5; }
    .layout { display: grid; grid-template-columns: 1fr minmax(280px, 380px); gap: 0; min-height: 100vh; }
    @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } .chat-panel { border-left: none; border-top: 1px solid var(--border); max-height: none; } }
    .main { padding: 1.25rem; overflow: auto; }
    .chat-panel { border-left: 1px solid var(--border); background: var(--chat); display: flex; flex-direction: column; max-height: 100vh; position: sticky; top: 0; }
    h1 { font-size: 1.2rem; font-weight: 600; margin: 0 0 0.25rem; }
    .subtitle { font-size: 0.8rem; color: var(--muted); margin: 0 0 1rem; }
    h2 { font-size: 0.95rem; color: var(--muted); margin: 0 0 0.5rem; font-weight: 600; }
    form { display: flex; gap: 0.6rem; align-items: center; margin-bottom: 1rem; padding: 0.9rem; background: var(--card); border-radius: 10px; border: 1px solid var(--border); }
    label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.8rem; color: var(--muted); }
    input[type="text"] { padding: 0.55rem 0.65rem; border-radius: 8px; border: 1px solid var(--border); background: #0d1218; color: var(--text); min-width: 18rem; flex: 1; }
    .spacer { flex: 1; }
    input[type="checkbox"] { width: 1rem; height: 1rem; }
    button, .btn { padding: 0.5rem 1rem; border-radius: 8px; border: none; background: var(--accent); color: #0a0e12; font-weight: 600; cursor: pointer; font-size: 0.9rem; }
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
    .bubble.user { align-self: flex-end; background: #243044; }
    .bubble.ai { align-self: stretch; background: #1a2332; border: 1px solid var(--border); }
    .bubble .src { margin-top: 0.6rem; padding-top: 0.6rem; border-top: 1px solid var(--border); font-size: 0.8rem; color: var(--muted); }
    .bubble .src a { display: block; margin: 0.2rem 0; }
    .chat-input { padding: 0.75rem 1rem 1rem; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 0.5rem; }
    textarea { width: 100%; min-height: 4.5rem; resize: vertical; padding: 0.55rem 0.65rem; border-radius: 8px; border: 1px solid var(--border); background: #0d1218; color: var(--text); font-family: inherit; font-size: 0.9rem; }
    .row { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
    .pill { font-size: 0.72rem; color: var(--muted); }
    .pager { display:flex; gap:0.35rem; justify-content:center; padding: 0.9rem 0; }
    .pg { background: transparent; border: 1px solid var(--border); color: var(--text); padding: 0.35rem 0.65rem; border-radius: 8px; cursor: pointer; }
    .pg.on { background: rgba(91,159,212,0.18); border-color: rgba(91,159,212,0.55); }
    .loading { color: var(--muted); font-size: 0.85rem; }
  </style>
</head>
<body>
  <div class="layout">
    <div class="main">
      <h1>""" + APP_NAME_KO + """</h1>
      <p class="subtitle">DESS 공지 · SQLite · Chroma · LangChain RAG</p>
      <form id="searchForm">
        <input id="kw" type="text" placeholder="검색어를 입력하세요 (예: 키스톤, 캡스톤, 복학)" autocomplete="off">
        <button type="submit">검색</button>
        <button type="button" class="pg" id="clearBtn">초기화</button>
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
        <p class="chat-hint">질문마다 Selenium으로 공지를 받아 Pandas·SQLite에 저장하고 ChromaDB로 검색한 뒤 LangChain RAG로 답합니다. <code>OPENAI_API_KEY</code>는 서버에만 두세요.</p>
        <div class="row">
          <label class="pill">AI용 페이지
            <input type="number" id="aiPages" min="1" max="20" value="4" style="width:4rem;">
          </label>
          <label class="pill" style="flex-direction:row;align-items:center;gap:0.35rem;">
            <input type="checkbox" id="aiDeep"> 본문까지 참고 (느림)
          </label>
        </div>
      </div>
      <div class="msgs" id="msgs"></div>
      <div class="chat-input">
        <textarea id="q" placeholder="예: 2025학년도 2학기 복학 일정이 뭐야?"></textarea>
        <button type="button" id="send">보내기</button>
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
  const PAGE_NAV = 3; // 하단 1 2 3
  let currentPage = 1;

  function esc(s){ return (s||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'); }

  function renderPager() {
    pager.innerHTML = '';
    for (let p = 1; p <= PAGE_NAV; p++) {
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
    renderPager();
    loading.style.display = 'block';
    metaLine.textContent = '';
    try {
      const q = (kw.value || '').trim();
      const url = new URL('/api/list', window.location.origin);
      url.searchParams.set('page', String(p));
      if (q) url.searchParams.set('q', q);
      const r = await fetch(url.toString(), { method: 'GET' });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
      renderRows(j.articles || []);
      const src = j.source || {};
      metaLine.textContent = `출처: ${src.base || ''} · mid=${src.mid || ''} · page=${src.page || p} · 목록 ${j.count_total || 0}건 · 표시 ${j.count_matched || 0}건`;
    } catch (e) {
      listBody.innerHTML = '<tr><td colspan="5" class="err">오류: ' + esc(e.message) + '</td></tr>';
    } finally {
      loading.style.display = 'none';
    }
  }

  searchForm.addEventListener('submit', (e) => { e.preventDefault(); loadPage(1); });
  clearBtn.addEventListener('click', () => { kw.value=''; loadPage(1); });
  renderPager();
  loadPage(1);

  const msgs = document.getElementById('msgs');
  const q = document.getElementById('q');
  const send = document.getElementById('send');
  const statusEl = document.getElementById('chatStatus');
  const aiPages = document.getElementById('aiPages');
  const aiDeep = document.getElementById('aiDeep');

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
    if (sources && sources.length) {
      const s = document.createElement('div');
      s.className = 'src';
      s.appendChild(document.createTextNode('출처:'));
      sources.forEach(function (x) {
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

  async function doSend() {
    const text = (q.value || '').trim();
    if (!text) return;
    addBubble(text, 'user');
    q.value = '';
    send.disabled = true;
    statusEl.textContent = '응답 중…';
    try {
      const mid = new URLSearchParams(window.location.search).get('mid') || 'Notice';
      const r = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          mid: mid,
          pages: parseInt(aiPages.value, 10) || 4,
          deep: !!aiDeep.checked
        })
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
      addAiBubble(j.reply || '', j.sources || []);
    } catch (e) {
      addBubble('오류: ' + e.message, 'ai');
    } finally {
      send.disabled = false;
      statusEl.textContent = '';
    }
  }

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
    mid = (request.args.get("mid") or "Notice").strip() or "Notice"
    try:
        page = int(request.args.get("page") or "1")
    except ValueError:
        page = 1
    page = max(1, min(50, page))
    q = (request.args.get("q") or "").strip()
    keywords = [q] if q else []
    no_filter = not bool(q)

    try:
        data = run_list_page(
            mid=mid,
            page=page,
            keywords=keywords,
            match_all=False,
            no_filter=no_filter,
            fetch_body=False,
            headless=True,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify(data)


@app.post("/api/chat")
def api_chat():
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

    try:
        out = answer_with_sources(
            msg,
            mid=mid,
            pages=pages,
            include_article_bodies=deep,
        )
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(
        {
            "reply": out.get("reply", ""),
            "sources": out.get("sources") or [],
            "crawl_summary": out.get("crawl_summary"),
            "ingest": out.get("ingest"),
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
