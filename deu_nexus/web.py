#!/usr/bin/env python3
"""DESS Nexus 로컬 웹 UI (공지 목록 + AI 채팅)."""

from __future__ import annotations

import os
import sys

from flask import Flask, jsonify, render_template_string, request

from deu_nexus import APP_NAME, APP_NAME_KO
from deu_nexus.chat import answer_with_sources
from deu_nexus.crawler import run_crawl

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
    form { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: flex-end; margin-bottom: 1rem; padding: 1rem; background: var(--card); border-radius: 10px; border: 1px solid var(--border); }
    label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.8rem; color: var(--muted); }
    input[type="text"], input[type="number"] { padding: 0.45rem 0.6rem; border-radius: 6px; border: 1px solid var(--border); background: #0d1218; color: var(--text); min-width: 8rem; }
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
  </style>
</head>
<body>
  <div class="layout">
    <div class="main">
      <h1>""" + APP_NAME_KO + """</h1>
      <p class="subtitle">DESS 공지 · SQLite · Chroma · LangChain RAG</p>
      <form method="get" action="{{ url_for('index') }}">
        <label>페이지 수
          <input type="number" name="pages" min="1" max="20" value="{{ pages }}">
        </label>
        <label>게시판 mid
          <input type="text" name="mid" value="{{ mid }}" placeholder="Notice">
        </label>
        <label>키워드 (공백 구분)
          <input type="text" name="keywords" value="{{ keywords }}" placeholder="캡스톤 디자인 협업" style="min-width:14rem;">
        </label>
        <label style="flex-direction:row; align-items:center; gap:0.4rem;">
          <input type="checkbox" name="no_filter" value="1" {% if no_filter %}checked{% endif %}>
          필터 끄기 (전체)
        </label>
        <label style="flex-direction:row; align-items:center; gap:0.4rem;">
          <input type="checkbox" name="match_all" value="1" {% if match_all %}checked{% endif %}>
          키워드 모두 포함
        </label>
        <button type="submit">목록 새로고침</button>
      </form>
      {% if error %}
      <p class="err">{{ error }}</p>
      {% endif %}
      {% if data %}
      <p class="meta">
        출처: {{ data.source.base }} · mid={{ data.source.mid }} ·
        목록 {{ data.count_total }}건 · 표시 {{ data.count_matched }}건
      </p>
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
        <tbody>
          {% for a in data.articles %}
          <tr>
            <td>{% if a.is_notice %}<span class="tag">공지</span>{% else %}{{ a.list_no }}{% endif %}</td>
            <td><a href="{{ a.url }}" target="_blank" rel="noopener">{{ a.title }}</a></td>
            <td>{{ a.author }}</td>
            <td>{{ a.posted }}</td>
            <td>{{ a.views }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% endif %}
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


def _parse_keywords(s: str) -> list[str]:
    parts = []
    for chunk in (s or "").replace(",", " ").split():
        t = chunk.strip()
        if t:
            parts.append(t)
    return parts


@app.route("/")
def index():
    pages = request.args.get("pages", default="3", type=str)
    mid = request.args.get("mid", default="Notice", type=str) or "Notice"
    keywords_raw = request.args.get("keywords", default="키스톤 캡스톤 디자인 협업", type=str)
    no_filter = request.args.get("no_filter") == "1"
    match_all = request.args.get("match_all") == "1"

    try:
        pages_n = max(1, min(20, int(pages)))
    except ValueError:
        pages_n = 3

    data = None
    error = None
    try:
        data = run_crawl(
            mid=mid.strip() or "Notice",
            pages=pages_n,
            delay=0.6,
            keywords=_parse_keywords(keywords_raw),
            match_all=match_all,
            no_filter=no_filter,
            fetch_body=False,
        )
    except Exception as e:
        error = str(e)

    return render_template_string(
        PAGE_TEMPLATE,
        data=data,
        error=error,
        pages=pages_n,
        mid=mid,
        keywords=keywords_raw,
        no_filter=no_filter,
        match_all=match_all,
    )


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
