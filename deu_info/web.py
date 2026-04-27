#!/usr/bin/env python3
"""deu_info 로컬 웹 UI (공지 목록 + AI 채팅)."""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template_string, request

from deu_info import APP_NAME, APP_NAME_KO
from deu_info.academic_calendar_data import (
    ACADEMIC_EVENTS,
    CALENDAR_NOTE,
    OFFICIAL_NOTICE_URL,
    OFFICIAL_SCHEDULE_URL,
)
from deu_info.pin_board import API_MAX_CONTENT_LENGTH, add_post as pin_add_post, list_posts as pin_list_posts
from deu_info.crawler import DEFAULT_BASE, DEFAULT_DEU_NOTICE_URL, run_crawl, run_deu_notice_crawl

app = Flask(__name__)


@app.after_request
def _security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


# ----- chat jobs (server-side cancel) -----
import threading
import uuid

_CHAT_JOBS: dict[str, dict] = {}
_CHAT_LOCK = threading.Lock()
_CHAT_JOB_MAX = 400
_CHAT_JOB_TTL_SEC = 1800
_CHAT_START_TIMES: dict[str, list[float]] = {}
_CHAT_RATE_LOCK = threading.Lock()
_CHAT_START_WINDOW_SEC = 60.0
_CHAT_START_MAX_PER_WINDOW = 24


def _new_job_id() -> str:
    return uuid.uuid4().hex


def _purge_chat_jobs_unlocked(now: float) -> None:
    """종료된 채팅 job TTL·개수 상한 — 메모리 고갈·남용 완화."""
    for jid in list(_CHAT_JOBS.keys()):
        job = _CHAT_JOBS.get(jid)
        if not job:
            continue
        st = job.get("status")
        if st in ("done", "error", "cancelled"):
            ft = job.get("finished_at")
            if ft is not None and now - float(ft) > _CHAT_JOB_TTL_SEC:
                _CHAT_JOBS.pop(jid, None)
    while len(_CHAT_JOBS) > _CHAT_JOB_MAX:
        finished = [
            (jid, j)
            for jid, j in _CHAT_JOBS.items()
            if j.get("status") in ("done", "error", "cancelled")
        ]
        if not finished:
            break
        finished.sort(key=lambda x: float(x[1].get("finished_at") or x[1].get("created_at") or 0))
        _CHAT_JOBS.pop(finished[0][0], None)


def _chat_start_rate_allow(ip: str) -> bool:
    now = time.time()
    with _CHAT_RATE_LOCK:
        lst = _CHAT_START_TIMES.setdefault(ip, [])
        lst[:] = [t for t in lst if now - t < _CHAT_START_WINDOW_SEC]
        if len(lst) >= _CHAT_START_MAX_PER_WINDOW:
            return False
        lst.append(now)
        return True


def _is_trusted_notice_url(url: str) -> bool:
    """채팅 출처 링크: https + 동의대 계열 호스트만."""
    u = (url or "").strip()
    if not u or len(u) > 2048:
        return False
    try:
        p = urlparse(u)
    except Exception:
        return False
    if p.scheme != "https":
        return False
    if p.username is not None or p.password is not None:
        return False
    host = (p.hostname or "").lower()
    if not host:
        return False
    return host == "deu.ac.kr" or host.endswith(".deu.ac.kr")


def _sanitize_chat_sources(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        url = s.get("url")
        if not isinstance(url, str) or not _is_trusted_notice_url(url):
            continue
        entry: dict = {"url": url.strip()[:2048]}
        t = s.get("title")
        if isinstance(t, str):
            entry["title"] = t[:2000]
        idx = s.get("index")
        if isinstance(idx, (int, str, float)) and not isinstance(idx, bool):
            entry["index"] = idx
        out.append(entry)
    return out

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#0c0f14" media="(prefers-color-scheme: dark)">
  <meta name="theme-color" content="#e8ecf4" media="(prefers-color-scheme: light)">
  <title>""" + APP_NAME + """</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0c0f14;
      --bg-elevated: #12171f;
      --surface: rgba(22, 28, 38, 0.72);
      --card: #161c26;
      --text: #eef2f7;
      --muted: #8b98ab;
      --accent: #5eb0e8;
      --accent-dim: rgba(94, 176, 232, 0.14);
      --border: rgba(255, 255, 255, 0.08);
      --chat: #0f1319;
      --radius: 14px;
      --radius-sm: 10px;
      --shadow: 0 4px 24px rgba(0, 0, 0, 0.35);
      --font: "Noto Sans KR", system-ui, -apple-system, sans-serif;
    }
    html[data-theme="light"] {
      --bg: #e8ecf4;
      --bg-elevated: #f4f6fb;
      --surface: rgba(255, 255, 255, 0.82);
      --card: #ffffff;
      --text: #0f172a;
      --muted: #64748b;
      --accent: #2563eb;
      --accent-dim: rgba(37, 99, 235, 0.1);
      --border: rgba(15, 23, 42, 0.1);
      --chat: #f8fafc;
      --shadow: 0 4px 24px rgba(15, 23, 42, 0.08);
    }
    * { box-sizing: border-box; }
    html {
      scroll-behavior: smooth;
      color-scheme: dark light;
    }
    html[data-theme="light"] { color-scheme: light; }
    @media (prefers-reduced-motion: no-preference) {
      ::view-transition-old(root),
      ::view-transition-new(root) {
        animation-duration: 0.42s;
        animation-timing-function: cubic-bezier(0.22, 1, 0.36, 1);
      }
    }
    @media (prefers-reduced-motion: reduce) {
      html { scroll-behavior: auto; }
      *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
      ::view-transition-group(*),
      ::view-transition-old(*),
      ::view-transition-new(*) {
        animation: none !important;
      }
    }
    body {
      font-family: var(--font);
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      line-height: 1.55;
      background: var(--bg);
      background-image:
        radial-gradient(ellipse 120% 80% at 20% -20%, rgba(94, 176, 232, 0.18), transparent 50%),
        radial-gradient(ellipse 90% 60% at 100% 0%, rgba(139, 92, 246, 0.1), transparent 45%),
        radial-gradient(ellipse 70% 50% at 50% 100%, rgba(94, 176, 232, 0.06), transparent 50%);
    }
    html[data-theme="light"] body {
      background-image:
        radial-gradient(ellipse 100% 70% at 10% 0%, rgba(37, 99, 235, 0.12), transparent 50%),
        radial-gradient(ellipse 80% 50% at 100% 10%, rgba(99, 102, 241, 0.08), transparent 45%);
    }
    .layout {
      max-width: 1540px;
      margin: 0 auto;
      min-height: 100vh;
      min-height: 100dvh;
      padding-top: max(1.25rem, env(safe-area-inset-top, 0px));
      padding-right: max(1.25rem, env(safe-area-inset-right, 0px));
      padding-bottom: max(5.5rem, calc(5.5rem + env(safe-area-inset-bottom, 0px)));
      padding-left: max(1.25rem, env(safe-area-inset-left, 0px));
      display: grid;
      grid-template-columns: minmax(0, 272px) minmax(0, 1fr) minmax(0, 272px);
      gap: 1rem;
      align-items: start;
    }
    @media (max-width: 1180px) {
      .layout {
        grid-template-columns: 1fr;
      }
      .rail-left { order: 2; }
      .main { order: 1; }
      .rail-right { order: 3; }
    }
    @media (max-width: 900px) {
      .layout {
        padding-top: max(1rem, env(safe-area-inset-top, 0px));
        padding-right: max(1rem, env(safe-area-inset-right, 0px));
        padding-bottom: max(5.25rem, calc(5.25rem + env(safe-area-inset-bottom, 0px)));
        padding-left: max(1rem, env(safe-area-inset-left, 0px));
      }
    }
    .main {
      padding: 0;
      overflow: visible;
      min-width: 0;
    }
    .main-card {
      background: var(--surface);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 1.35rem 1.4rem 1.25rem;
    }
    /* 다크: 카드 가장자리 은은한 야광(시안) */
    html:not([data-theme="light"]) .main-card {
      border-color: rgba(125, 211, 252, 0.22);
      box-shadow:
        var(--shadow),
        0 0 0 1px rgba(94, 176, 232, 0.14),
        0 0 22px rgba(56, 189, 248, 0.11),
        0 0 44px rgba(56, 189, 248, 0.06),
        inset 0 0 0 1px rgba(186, 230, 253, 0.06);
    }
    .rail {
      display: flex;
      flex-direction: column;
      gap: 1rem;
      min-width: 0;
    }
    @media (prefers-reduced-motion: no-preference) {
      .main-card,
      .rail-card,
      .icon-btn,
      .filter-bar,
      #searchForm,
      .pager,
      .meta-row {
        transition:
          background-color 0.38s cubic-bezier(0.22, 1, 0.36, 1),
          border-color 0.38s cubic-bezier(0.22, 1, 0.36, 1),
          box-shadow 0.38s cubic-bezier(0.22, 1, 0.36, 1),
          color 0.28s ease;
      }
      .data-table th,
      .data-table td {
        transition: background-color 0.32s ease, color 0.28s ease, border-color 0.32s ease;
      }
    }
    .rail-card {
      background: var(--surface);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 1rem 1rem 0.95rem;
    }
    html:not([data-theme="light"]) .rail-card {
      border-color: rgba(125, 211, 252, 0.18);
      box-shadow:
        var(--shadow),
        0 0 0 1px rgba(94, 176, 232, 0.1),
        0 0 18px rgba(56, 189, 248, 0.07);
    }
    .rail-h {
      font-size: 0.95rem;
      margin: 0 0 0.35rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }
    .rail-note, .rail-sub, .rail-foot {
      font-size: 0.72rem;
      color: var(--muted);
      margin: 0 0 0.5rem;
      line-height: 1.45;
    }
    .rail-link {
      font-size: 0.72rem;
      display: inline-block;
      margin-top: 0.55rem;
      color: var(--accent);
      word-break: keep-all;
    }
    .rail-link:hover { text-decoration: underline; }
    .cal-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
      margin: 0.45rem 0 0.35rem;
    }
    .cal-title { font-size: 0.85rem; font-weight: 600; }
    .cal-nav {
      padding: 0.25rem 0.55rem;
      min-width: auto;
      line-height: 1.2;
      border-radius: var(--radius-sm);
    }
    .cal-weekdays, .cal-grid {
      display: grid;
      grid-template-columns: repeat(7, 1fr);
      gap: 3px;
    }
    .cal-weekdays span {
      font-size: 0.62rem;
      color: var(--muted);
      text-align: center;
      font-weight: 600;
    }
    .cal-cell {
      min-height: 1.85rem;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.72rem;
      border-radius: 6px;
      cursor: default;
    }
    .cal-cell.dim { opacity: 0.38; }
    .cal-cell.today {
      box-shadow: 0 0 0 1px var(--accent);
      font-weight: 700;
    }
    .cal-cell.has-ev {
      background: var(--accent-dim);
      font-weight: 600;
    }
    .cal-cell.sun { color: #f87171; }
    html[data-theme="light"] .cal-cell.sun { color: #dc2626; }
    .cal-cell.sat { color: #7dd3fc; }
    html[data-theme="light"] .cal-cell.sat { color: #0284c7; }
    #pinInput {
      width: 100%;
      margin-top: 0.35rem;
      resize: vertical;
      max-height: 9rem;
      min-height: 4.5rem;
      padding: 0.55rem 0.65rem;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
      background: var(--bg-elevated);
      color: var(--text);
      font-family: var(--font);
      font-size: 0.82rem;
      line-height: 1.45;
    }
    html[data-theme="light"] #pinInput { background: #fff; }
    .pin-actions {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.45rem;
      margin-top: 0.5rem;
    }
    .pin-actions button { font-size: 0.82rem; padding: 0.45rem 0.85rem; }
    .pin-list {
      list-style: none;
      margin: 0.65rem 0 0;
      padding: 0;
      max-height: 240px;
      overflow-y: auto;
      -webkit-overflow-scrolling: touch;
    }
    .pin-list li {
      font-size: 0.78rem;
      padding: 0.5rem 0;
      border-top: 1px solid var(--border);
      color: var(--text);
      word-break: break-word;
    }
    .pin-list .pin-meta {
      font-size: 0.66rem;
      color: var(--muted);
      margin-bottom: 0.2rem;
    }
    .upcoming-list {
      list-style: none;
      margin: 0;
      padding: 0;
    }
    .upcoming-list li {
      font-size: 0.76rem;
      padding: 0.45rem 0;
      border-bottom: 1px solid var(--border);
      line-height: 1.4;
    }
    .upcoming-list li:last-child { border-bottom: none; }
    .upcoming-list time {
      color: var(--accent);
      font-weight: 600;
      display: block;
      font-size: 0.68rem;
      margin-bottom: 0.15rem;
    }
    .topbar {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 1rem;
      margin-bottom: 1.15rem;
    }
    .brand {
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
      flex: 1;
      min-width: 0;
    }
    .brand-badge {
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      font-size: 0.72rem;
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--accent);
      background: var(--accent-dim);
      padding: 0.25rem 0.55rem;
      border-radius: 999px;
      width: fit-content;
    }
    .brand-badge .brand-lockup {
      text-transform: none;
      letter-spacing: -0.02em;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
      /* 배지는 accent 글자색인데, 로고만 본문색으로 분리해야 글로우·입이 보임 */
      color: var(--text);
    }
    .brand-mid {
      display: inline;
      position: relative;
    }
    .brand-eye {
      display: inline-block;
      opacity: 1;
      transition: transform 0.2s ease, text-shadow 0.2s ease;
      /* color-mix 미지원 브라우저 대비 rgba 고정 */
      text-shadow:
        0 0 8px rgba(94, 176, 232, 0.55),
        0 0 16px rgba(94, 176, 232, 0.28);
    }
    html[data-theme="light"] .brand-eye {
      text-shadow:
        0 0 6px rgba(37, 99, 235, 0.5),
        0 0 14px rgba(37, 99, 235, 0.25);
    }
    .brand-mouth {
      display: inline-block;
      color: var(--accent);
      opacity: 0.88;
      font-weight: 600;
      line-height: 1;
      margin: 0 0.02em;
      transform: scale(0.9, 0.62) translateY(0.12em);
      transition: transform 0.2s ease, opacity 0.2s ease;
    }
    @media (prefers-reduced-motion: no-preference) {
      .brand-mouth {
        animation: brand-mouth-breathe 3.4s ease-in-out infinite;
      }
    }
    @keyframes brand-mouth-breathe {
      0%, 100% { transform: scale(0.9, 0.58) translateY(0.13em); opacity: 0.75; }
      50% { transform: scale(0.92, 0.7) translateY(0.09em); opacity: 1; }
    }
    .brand-badge:hover .brand-eye {
      transform: translateY(-2px);
      text-shadow:
        0 0 12px rgba(94, 176, 232, 0.65),
        0 0 22px rgba(94, 176, 232, 0.35);
    }
    html[data-theme="light"] .brand-badge:hover .brand-eye {
      text-shadow:
        0 0 10px rgba(37, 99, 235, 0.6),
        0 0 20px rgba(37, 99, 235, 0.3);
    }
    .brand-badge:hover .brand-mouth {
      opacity: 1;
      transform: scale(0.93, 0.72) translateY(0.08em);
      animation: none;
    }
    h1,
    h1.h1-title {
      font-size: clamp(1.35rem, 2.5vw, 1.65rem);
      font-weight: 700;
      margin: 0;
      letter-spacing: -0.02em;
      line-height: 1.25;
    }
    h1 .h1-lockup {
      font-weight: 700;
      letter-spacing: -0.03em;
      white-space: nowrap;
    }
    h1 .h1-mid { display: inline; }
    h1 .h1-eye {
      display: inline-block;
      transition: color 0.2s ease;
    }
    /* 다크: 하늘색 계열 (u 밝게 / i 살짝 더 연하게) */
    h1 .h1-eye-u { color: #7dd3fc; }
    h1 .h1-eye-i { color: #bae6fd; }
    /* 라이트: 가독 좋은 조합 — u 청록(teal) · i 보라(violet) */
    html[data-theme="light"] h1 .h1-eye-u { color: #0d9488; }
    html[data-theme="light"] h1 .h1-eye-i { color: #6d28d9; }
    h1 .h1-mouth {
      display: inline-block;
      color: var(--accent);
      opacity: 0.92;
      font-weight: 600;
      line-height: 1;
      margin: 0 0.02em;
      transform: scale(0.9, 0.62) translateY(0.08em);
    }
    /* max-width 제거: h1보다 좁아져 ‘다.’만 다음 줄로 떨어지는 현상 방지 */
    .subtitle {
      font-size: 0.875rem;
      color: var(--muted);
      margin: 0;
      max-width: 100%;
      text-wrap: pretty;
    }
    .top-actions { display: flex; gap: 0.45rem; align-items: center; flex-shrink: 0; }
    .icon-btn {
      width: 2.55rem;
      height: 2.55rem;
      padding: 0;
      border-radius: 50%;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: var(--card);
      border: 1px solid var(--border);
      box-shadow: none;
      color: var(--text);
      cursor: pointer;
      transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
    }
    .icon-btn:hover {
      background: var(--accent-dim);
      border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
      transform: translateY(-1px);
    }
    .icon-btn svg {
      width: 1.2rem;
      height: 1.2rem;
      stroke: currentColor;
      fill: none;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .icon-btn svg.i-moon {
      fill: currentColor;
      stroke: none;
    }
    .icon-btn .i-sun { display: block; }
    .icon-btn .i-moon { display: none; }
    html[data-theme="light"] .icon-btn#themeBtn .i-sun { display: none; }
    html[data-theme="light"] .icon-btn#themeBtn .i-moon { display: block; }
    .icon-btn.is-active {
      background: var(--accent-dim);
      border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
      color: var(--accent);
    }
    button, .btn {
      font-family: var(--font);
      padding: 0.55rem 1rem;
      border-radius: var(--radius-sm);
      border: none;
      background: linear-gradient(165deg, var(--accent), color-mix(in srgb, var(--accent) 75%, #3b82f6));
      color: #fff;
      font-weight: 600;
      cursor: pointer;
      font-size: 0.875rem;
      box-shadow: 0 2px 12px rgba(94, 176, 232, 0.25);
      transition: transform 0.15s ease, box-shadow 0.15s ease, filter 0.15s ease;
    }
    html[data-theme="light"] button, html[data-theme="light"] .btn {
      box-shadow: 0 2px 10px rgba(37, 99, 235, 0.2);
    }
    button:hover, .btn:hover {
      filter: brightness(1.06);
      transform: translateY(-1px);
      box-shadow: 0 4px 16px rgba(94, 176, 232, 0.32);
    }
    button:active, .btn:active { transform: translateY(0); }
    button:disabled { opacity: 0.5; cursor: not-allowed; transform: none; box-shadow: none; }
    .btn-ghost {
      background: var(--card);
      color: var(--text);
      border: 1px solid var(--border);
      box-shadow: none;
    }
    .btn-ghost:hover {
      background: var(--accent-dim);
      border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
      box-shadow: none;
    }
    #searchForm {
      display: flex;
      flex-wrap: wrap;
      gap: 0.65rem;
      align-items: stretch;
      margin-bottom: 1rem;
      padding: 0.85rem;
      background: var(--card);
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
    }
    .filter-bar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.65rem 0.85rem;
      margin-bottom: 0.85rem;
      padding: 0.75rem 0.9rem;
      background: var(--card);
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
    }
    .btn-apply { font-size: 0.8125rem; padding: 0.48rem 0.9rem; }
    .source-checks {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.65rem 1.1rem;
      flex: 1;
      min-width: 12rem;
    }
    .source-checks label {
      flex-direction: row;
      align-items: center;
      gap: 0.4rem;
      cursor: pointer;
      font-size: 0.8125rem;
      color: var(--text);
      font-weight: 500;
      margin: 0;
      user-select: none;
    }
    .source-checks input { width: 1.05rem; height: 1.05rem; accent-color: var(--accent); }
    label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.8rem; color: var(--muted); }
    input[type="text"], select {
      font-family: var(--font);
      padding: 0.6rem 0.75rem;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
      background: var(--bg-elevated);
      color: var(--text);
      font-size: 0.875rem;
      transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    html[data-theme="light"] input[type="text"], html[data-theme="light"] select {
      background: #fff;
    }
    input[type="text"]:focus, select:focus, textarea:focus {
      outline: none;
      border-color: color-mix(in srgb, var(--accent) 55%, var(--border));
      box-shadow: 0 0 0 3px var(--accent-dim);
    }
    input[type="text"] { min-width: min(100%, 16rem); flex: 1; }
    input[type="checkbox"] { width: 1.05rem; height: 1.05rem; accent-color: var(--accent); }
    .meta-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.5rem;
      margin-bottom: 0.85rem;
      min-height: 1.5rem;
    }
    .meta { color: var(--muted); font-size: 0.8125rem; margin: 0; line-height: 1.45; }
    .loading-banner {
      display: none;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.8125rem;
      color: var(--accent);
      font-weight: 500;
      padding: 0.35rem 0.65rem;
      background: var(--accent-dim);
      border-radius: 999px;
      width: fit-content;
    }
    .loading-banner.on { display: inline-flex; }
    .spinner {
      width: 0.9rem;
      height: 0.9rem;
      border: 2px solid var(--border);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .table-wrap {
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
      overflow: hidden;
      background: var(--card);
      -webkit-overflow-scrolling: touch;
    }
    table.data-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.8125rem;
    }
    .data-table thead {
      background: var(--accent-dim);
    }
    .data-table th {
      text-align: left;
      padding: 0.65rem 0.75rem;
      color: var(--muted);
      font-weight: 600;
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      border-bottom: 1px solid var(--border);
    }
    .data-table td {
      padding: 0.65rem 0.75rem;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }
    .data-table tbody tr:last-child td { border-bottom: none; }
    .data-table tbody tr {
      transition: background 0.12s ease;
    }
    .data-table tbody tr:hover td {
      background: var(--accent-dim);
    }
    a {
      color: var(--accent);
      text-decoration: none;
      font-weight: 500;
      border-bottom: 1px solid transparent;
      transition: border-color 0.12s ease, color 0.12s ease;
    }
    a:hover { border-bottom-color: color-mix(in srgb, var(--accent) 50%, transparent); }
    .tag {
      display: inline-block;
      padding: 0.2rem 0.45rem;
      border-radius: 6px;
      font-size: 0.68rem;
      font-weight: 600;
      background: var(--accent-dim);
      color: var(--accent);
    }
    .cell-empty, .cell-err {
      text-align: center;
      padding: 2rem 1rem !important;
      color: var(--muted);
    }
    .cell-err { color: #f87171; }
    .pager {
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem;
      justify-content: center;
      padding: 1.1rem 0 0.25rem;
    }
    .pg {
      font-family: var(--font);
      min-width: 2.35rem;
      padding: 0.4rem 0.55rem;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
      background: var(--card);
      color: var(--text);
      cursor: pointer;
      font-size: 0.8125rem;
      font-weight: 500;
      transition: background 0.12s ease, border-color 0.12s ease, transform 0.12s ease;
    }
    .pg:hover { background: var(--accent-dim); border-color: color-mix(in srgb, var(--accent) 40%, var(--border)); }
    .pg.on {
      background: linear-gradient(165deg, var(--accent), color-mix(in srgb, var(--accent) 80%, #6366f1));
      border-color: transparent;
      color: #fff;
    }
    .chat-fab-panel {
      position: fixed;
      right: 1.1rem;
      bottom: 1.1rem;
      width: min(372px, calc(100vw - 2.2rem));
      height: min(448px, calc(100vh - 5.5rem));
      min-width: 268px;
      min-height: 220px;
      max-width: min(720px, calc(100vw - 1rem));
      max-height: min(92vh, calc(100vh - 2.5rem));
      display: flex;
      flex-direction: column;
      z-index: 1000;
      border-radius: 18px;
      border: 1px solid var(--border);
      background: color-mix(in srgb, var(--card) 80%, transparent);
      backdrop-filter: blur(18px);
      -webkit-backdrop-filter: blur(18px);
      box-shadow: 0 14px 44px rgba(0, 0, 0, 0.32);
      overflow: hidden;
    }
    html[data-theme="light"] .chat-fab-panel {
      background: color-mix(in srgb, var(--card) 86%, transparent);
      box-shadow: 0 14px 40px rgba(15, 23, 42, 0.14);
    }
    body.chat-hidden .chat-fab-panel {
      display: none;
    }
    .chat-fab-top {
      display: grid;
      grid-template-columns: auto 1fr auto;
      align-items: flex-start;
      gap: 0.45rem 0.5rem;
      padding: 0.65rem 0.75rem 0.6rem 0.55rem;
      border-bottom: 1px solid var(--border);
      background: linear-gradient(180deg, var(--accent-dim), transparent);
    }
    .chat-fab-titleblock {
      min-width: 0;
    }
    .chat-resize-handle {
      width: 2.1rem;
      height: 2.1rem;
      margin: -0.2rem 0 0 -0.15rem;
      padding: 0;
      border: none;
      border-radius: 12px;
      background: transparent;
      color: var(--muted);
      cursor: nw-resize;
      flex-shrink: 0;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      touch-action: none;
      transition: background 0.12s ease, color 0.12s ease;
    }
    .chat-resize-handle:hover {
      background: var(--accent-dim);
      color: var(--accent);
    }
    .chat-resize-handle:active { background: color-mix(in srgb, var(--accent-dim) 70%, var(--card)); }
    .chat-resize-handle svg {
      width: 1rem;
      height: 1rem;
      stroke: currentColor;
      fill: none;
      stroke-width: 2;
      stroke-linecap: round;
    }
    .chat-fab-top h2 {
      font-size: 0.92rem;
      font-weight: 700;
      margin: 0;
      letter-spacing: -0.02em;
      color: var(--text);
    }
    .chat-hint {
      font-size: 0.72rem;
      color: var(--muted);
      margin: 0.35rem 0 0;
      line-height: 1.45;
    }
    .chat-fab-close {
      width: 2rem;
      height: 2rem;
      padding: 0;
      border-radius: 50%;
      border: none;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      transition: background 0.12s ease, color 0.12s ease;
    }
    .chat-fab-close:hover { background: var(--accent-dim); color: var(--text); }
    .chat-fab-close svg { width: 1.1rem; height: 1.1rem; stroke: currentColor; fill: none; stroke-width: 2; stroke-linecap: round; }
    .chat-tools {
      display: flex;
      flex-wrap: wrap;
      gap: 0.55rem 0.85rem;
      align-items: flex-end;
      padding: 0.65rem 0.85rem;
      border-bottom: 1px solid var(--border);
      background: var(--chat);
    }
    .field-select label {
      font-size: 0.7rem;
      color: var(--muted);
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 0.25rem;
      display: block;
    }
    .field-select select {
      min-width: 11.5rem;
      font-size: 0.8rem;
      padding: 0.45rem 0.55rem;
    }
    .check-row {
      display: flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.76rem;
      color: var(--muted);
      cursor: pointer;
      user-select: none;
      margin: 0;
    }
    .msgs {
      flex: 1;
      min-height: 0;
      overflow: auto;
      padding: 0.75rem 0.85rem;
      display: flex;
      flex-direction: column;
      gap: 0.65rem;
      background: color-mix(in srgb, var(--chat) 92%, transparent);
      min-height: 120px;
    }
    .bubble {
      padding: 0.75rem 0.9rem;
      border-radius: 16px;
      font-size: 0.875rem;
      max-width: 92%;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.55;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
    }
    html[data-theme="light"] .bubble { box-shadow: 0 1px 4px rgba(15, 23, 42, 0.06); }
    .bubble.user {
      align-self: flex-end;
      background: linear-gradient(145deg, color-mix(in srgb, var(--accent) 88%, #fff), var(--accent));
      color: #fff;
      border-bottom-right-radius: 6px;
    }
    .bubble.ai {
      align-self: stretch;
      max-width: 100%;
      background: var(--card);
      border: 1px solid var(--border);
      border-bottom-left-radius: 6px;
      box-shadow: none;
    }
    .bubble .src {
      margin-top: 0.65rem;
      padding-top: 0.65rem;
      border-top: 1px solid var(--border);
      font-size: 0.78rem;
      color: var(--muted);
    }
    .bubble .src a { display: block; margin: 0.3rem 0; font-weight: 500; }
    .bubble[data-typing="1"] {
      color: var(--muted);
      font-style: italic;
      animation: pulse-soft 1.2s ease-in-out infinite;
    }
    @keyframes pulse-soft { 50% { opacity: 0.72; } }
    .chat-scope-warn {
      align-self: stretch;
      flex-shrink: 0;
      margin: 0;
      padding: 0.65rem 0.85rem;
      border-radius: var(--radius-sm);
      font-size: 0.78rem;
      line-height: 1.5;
      font-weight: 500;
      border: 1px solid color-mix(in srgb, #f87171 45%, var(--border));
      background: color-mix(in srgb, rgba(248, 113, 113, 0.14) 50%, var(--card));
      color: #fecaca;
      box-shadow: 0 0 0 1px rgba(248, 113, 113, 0.08);
    }
    html[data-theme="light"] .chat-scope-warn {
      background: #fef2f2;
      border-color: #f87171;
      color: #991b1b;
      box-shadow: none;
    }
    .chat-input {
      padding: 0.65rem 0.85rem 0.8rem;
      border-top: 1px solid var(--border);
      background: color-mix(in srgb, var(--card) 90%, transparent);
      display: flex;
      flex-direction: column;
      gap: 0.45rem;
    }
    textarea {
      width: 100%;
      min-height: 3.75rem;
      resize: vertical;
      padding: 0.65rem 0.8rem;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
      background: var(--bg-elevated);
      color: var(--text);
      font-family: var(--font);
      font-size: 0.875rem;
      line-height: 1.5;
    }
    html[data-theme="light"] textarea { background: #fff; }
    .chat-actions { display: flex; flex-wrap: wrap; gap: 0.5rem; justify-content: space-between; align-items: center; }
    .chat-actions .row-left { display: flex; gap: 0.5rem; flex-wrap: wrap; }
    .pill { font-size: 0.72rem; color: var(--muted); }
    .row { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }

    @media (hover: none) and (pointer: coarse) {
      .icon-btn, .chat-fab-close, .chat-resize-handle, .pg, .btn-apply,
      #searchForm button, .chat-actions button, .cal-nav, #pinSend {
        min-height: 44px;
      }
      .icon-btn { min-width: 44px; }
      .cal-nav { min-width: 44px; }
    }
    @media (hover: none) {
      .data-table tbody tr:active td { background: var(--accent-dim); }
    }

    @media (max-width: 720px) {
      .main-card {
        padding: 1rem 0.9rem;
        border-radius: 12px;
      }
      .topbar {
        flex-wrap: wrap;
        gap: 0.75rem;
      }
      .brand {
        flex: 1 1 auto;
        min-width: 0;
        max-width: calc(100% - 6.5rem);
      }
      .top-actions {
        flex-shrink: 0;
        margin-left: auto;
      }
      h1 {
        font-size: clamp(1.15rem, 4.8vw, 1.5rem);
        word-break: keep-all;
      }
      .subtitle {
        font-size: 0.84rem;
        line-height: 1.5;
      }
      .icon-btn {
        width: 2.75rem;
        height: 2.75rem;
        min-width: 44px;
        min-height: 44px;
      }
      .filter-bar {
        flex-direction: column;
        align-items: stretch;
        padding: 0.85rem;
      }
      .source-checks {
        flex-direction: column;
        align-items: flex-start;
        gap: 0.5rem;
        min-width: 0;
        width: 100%;
      }
      .source-checks label {
        min-height: 44px;
        display: inline-flex;
        align-items: center;
        padding: 0.2rem 0;
      }
      .source-checks input {
        width: 1.2rem;
        height: 1.2rem;
        min-width: 22px;
        min-height: 22px;
      }
      .btn-apply {
        width: 100%;
        min-height: 44px;
      }
      #searchForm {
        flex-direction: column;
        align-items: stretch;
        padding: 0.85rem;
      }
      #searchForm input[type="text"] {
        width: 100%;
        min-width: 0;
        font-size: 16px;
      }
      #searchForm button[type="submit"],
      #searchForm #clearBtn {
        width: 100%;
        min-height: 44px;
      }
      .meta {
        font-size: 0.78rem;
        word-break: keep-all;
      }
      .table-wrap {
        overflow-x: auto;
        overscroll-behavior-x: contain;
        border-radius: 10px;
      }
      table.data-table {
        min-width: 520px;
        font-size: 0.78rem;
      }
      .data-table th,
      .data-table td {
        padding: 0.55rem 0.5rem;
      }
      .pg {
        min-width: 44px;
        min-height: 44px;
        padding: 0.45rem 0.5rem;
      }
      .pager {
        gap: 0.35rem;
        padding-bottom: 0.25rem;
      }
      .chat-fab-panel {
        right: max(0.5rem, env(safe-area-inset-right, 0px));
        bottom: max(0.55rem, env(safe-area-inset-bottom, 0px));
        width: min(400px, calc(100vw - max(1rem, env(safe-area-inset-left, 0px) + env(safe-area-inset-right, 0px))));
        min-width: min(268px, calc(100vw - 1rem));
        height: min(50vh, calc(100dvh - max(5rem, env(safe-area-inset-top, 0px) + env(safe-area-inset-bottom, 0px))));
        max-height: min(520px, calc(100dvh - env(safe-area-inset-top, 0px) - env(safe-area-inset-bottom, 0px) - 4.5rem));
      }
      .chat-resize-handle {
        width: 2.5rem;
        height: 2.5rem;
        min-width: 44px;
        min-height: 44px;
      }
      .chat-fab-close {
        width: 2.5rem;
        height: 2.5rem;
        min-width: 44px;
        min-height: 44px;
      }
      .field-select {
        width: 100%;
      }
      .field-select select {
        width: 100%;
        min-width: 0;
        max-width: 100%;
        font-size: 16px;
      }
      .check-row {
        min-height: 44px;
        align-items: center;
      }
      textarea#q {
        font-size: 16px;
      }
      .chat-actions #send,
      .chat-actions #cancelBtn {
        min-height: 44px;
        padding-left: 1.1rem;
        padding-right: 1.1rem;
      }
    }

    @media (max-width: 480px) {
      .topbar {
        flex-direction: column;
        align-items: stretch;
      }
      .brand {
        max-width: 100%;
      }
      .top-actions {
        margin-left: 0;
        justify-content: flex-end;
      }
    }

    @media (max-width: 380px) {
      .brand-badge {
        font-size: 0.65rem;
        padding: 0.3rem 0.5rem;
        max-width: 100%;
      }
    }
  </style>
</head>
<body class="chat-hidden">
  <div class="layout">
    <aside class="rail rail-left" aria-label="학사일정과 간단게시판">
      <div class="rail-card cal-rail">
        <h2 class="rail-h">학사일정</h2>
        <p class="rail-note" id="calNoteShort">참고용 일정입니다.</p>
        <div class="cal-head">
          <button type="button" class="btn-ghost cal-nav" id="calPrev" aria-label="이전 달">‹</button>
          <span class="cal-title" id="calTitle" aria-live="polite"></span>
          <button type="button" class="btn-ghost cal-nav" id="calNext" aria-label="다음 달">›</button>
        </div>
        <div class="cal-weekdays" aria-hidden="true">
          <span>일</span><span>월</span><span>화</span><span>수</span><span>목</span><span>금</span><span>토</span>
        </div>
        <div class="cal-grid" id="calGrid"></div>
        <a class="rail-link" id="calOfficial" href=\"""" + OFFICIAL_SCHEDULE_URL + """\" target="_blank" rel="noopener noreferrer">학교 공지에서 정확한 일정 확인 →</a>
      </div>
      <div class="rail-card pin-rail">
        <h2 class="rail-h">간단게시판</h2>
        <p class="rail-sub">제목 없이 내용만 적고 올리면 끝입니다. 서버에만 저장되며 수정·삭제는 불가능합니다. 같은 내용 반복·짧은 시간 다중 작성은 막습니다. 첨부·HTML 불가.</p>
        <textarea id="pinInput" maxlength="400" rows="4" placeholder="짧은 글 (400자, HTML·꺾쇠괄호 불가)" autocomplete="off" aria-label="게시 내용"></textarea>
        <div class="pin-actions">
          <button type="button" id="pinSend">올리기</button>
          <span class="pill" id="pinStatus" aria-live="polite"></span>
        </div>
        <ul class="pin-list" id="pinList" aria-label="최근 게시"></ul>
      </div>
    </aside>
    <div class="main">
      <div class="main-card">
        <div class="topbar">
          <div class="brand">
            <span class="brand-badge">동의대 · <span class="brand-lockup" aria-label="deu_info" title="deu_info">de<span class="brand-mid"><span class="brand-eye">u</span><span class="brand-mouth">‿</span><span class="brand-eye">i</span></span>nfo</span></span>
            <h1 class="h1-title">""" + APP_NAME_KO.replace("deu_info", "").strip() + """ <span class="h1-lockup" translate="no" aria-label="deu_info">de<span class="h1-mid"><span class="h1-eye h1-eye-u">u</span><span class="h1-mouth">‿</span><span class="h1-eye h1-eye-i">i</span></span>nfo</span></h1>
            <p class="subtitle">대표 공지와 DESS를 한곳에서 검색하고, AI로 요약·질문할 수 있습니다. 소스는 적용 후 목록이 바뀝니다.</p>
          </div>
          <div class="top-actions">
            <button type="button" class="icon-btn" id="themeBtn" aria-label="테마 전환" title="테마 전환">
              <svg class="i-sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>
              <svg class="i-moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
            </button>
            <button type="button" class="icon-btn" id="chatToggleBtn" aria-label="AI 채팅 열기" title="AI 채팅">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            </button>
          </div>
        </div>
        <div class="filter-bar">
          <div class="source-checks" role="group" aria-label="공지 소스">
            <label><input type="checkbox" id="srcDeu" value="deu" checked> 대표 공지</label>
            <label><input type="checkbox" id="srcDess" value="dess"> 학생서비스센터 (DESS)</label>
          </div>
          <button type="button" class="btn-ghost btn-apply" id="applySourcesBtn" title="선택한 소스로 목록 새로고침">적용</button>
        </div>
        <form id="searchForm">
          <input id="kw" type="text" placeholder="검색어 (예: 일정, 복학, 졸업, 장학)" autocomplete="off" aria-label="검색어">
          <button type="submit">검색</button>
          <button type="button" class="btn-ghost" id="clearBtn">초기화</button>
        </form>
        <div class="meta-row">
          <p class="meta" id="metaLine"></p>
          <div class="loading-banner" id="loadingBanner" aria-live="polite"><span class="spinner" aria-hidden="true"></span> 불러오는 중…</div>
        </div>
        <div class="table-wrap">
          <table class="data-table">
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
        </div>
        <div class="pager" id="pager"></div>
      </div>
    </div>
    <aside class="rail rail-right" aria-label="다가오는 학사일정">
      <div class="rail-card upcoming-rail">
        <h2 class="rail-h">다가오는 일정</h2>
        <ul class="upcoming-list" id="upcomingList"></ul>
        <p class="rail-foot" id="upcomingFoot"></p>
      </div>
    </aside>
  </div>
  <aside class="chat-fab-panel" id="chatPanel" aria-label="AI 채팅">
    <div class="chat-fab-top">
      <button type="button" class="chat-resize-handle" id="chatResizeHandle" aria-label="패널 크기 조절" title="왼쪽 위를 누른 채 드래그해 크기 조절">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5v6M5 5h6M19 19v-6M19 19h-6"/></svg>
      </button>
      <div class="chat-fab-titleblock">
        <h2>AI 질문</h2>
        <p class="chat-hint">목록과 같은 소스·아래 깊이로 답합니다. 왼쪽 위 모서리 버튼을 누른 채 드래그하면 크기를 바꿀 수 있어요.</p>
      </div>
      <button type="button" class="chat-fab-close" id="chatCloseBtn" aria-label="채팅 닫기" title="닫기">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6L6 18M6 6l12 12"/></svg>
      </button>
    </div>
    <div class="chat-tools">
      <div class="field-select">
        <label for="aiDepth">참고할 공지 깊이</label>
        <select id="aiDepth" title="게시판에서 몇 페이지까지 가져올지">
          <option value="1" selected>최신 1페이지 — 가장 빠름 (기본)</option>
          <option value="2">최신 2페이지</option>
          <option value="3">최신 3페이지</option>
          <option value="5">최신 5페이지</option>
          <option value="10">최신 10페이지 — 느릴 수 있음</option>
        </select>
      </div>
      <label class="check-row">
        <input type="checkbox" id="aiDeep"> 본문까지 (DESS만 해당, 느림)
      </label>
    </div>
    <div class="msgs" id="msgs"></div>
    <div class="chat-input">
      <textarea id="q" placeholder="예: 2026학년도 2학기 복학 일정 알려줘 (Shift+Enter 줄바꿈)"></textarea>
      <div class="chat-actions">
        <div class="row-left">
          <button type="button" id="send">보내기</button>
          <button type="button" class="btn-ghost" id="cancelBtn" style="display:none;">정지</button>
        </div>
        <span class="pill" id="chatStatus"></span>
      </div>
    </div>
  </aside>
  <script>
  // ----- list (검색 + 페이지네이션) -----
  const listBody = document.getElementById('listBody');
  const pager = document.getElementById('pager');
  const kw = document.getElementById('kw');
  const metaLine = document.getElementById('metaLine');
  const loadingBanner = document.getElementById('loadingBanner');
  const clearBtn = document.getElementById('clearBtn');
  const searchForm = document.getElementById('searchForm');
  const srcDeu = document.getElementById('srcDeu');
  const srcDess = document.getElementById('srcDess');
  const PAGE_SIZE = 20;
  const SCAN_PAGES = 2; // 목록 API: 소스당 스캔 페이지 (작을수록 빠름)
  let currentPage = 1;

  function esc(s){ return (s||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'); }

  function getSelectedSources() {
    const out = [];
    if (srcDeu && srcDeu.checked) out.push('deu');
    if (srcDess && srcDess.checked) out.push('dess');
    return out.length ? out : ['deu'];
  }

  function ensureSourceChecks() {
    if (!srcDeu.checked && !srcDess.checked) srcDeu.checked = true;
  }

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
      listBody.innerHTML = '<tr><td colspan="5" class="cell-empty">조건에 맞는 공지가 없습니다. 검색어나 소스를 바꿔 보세요.</td></tr>';
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
    loadingBanner.classList.add('on');
    metaLine.textContent = '';
    try {
      const q = (kw.value || '').trim();
      const url = new URL('/api/list', window.location.origin);
      url.searchParams.set('page', String(p));
      url.searchParams.set('scan_pages', String(SCAN_PAGES));
      url.searchParams.set('page_size', String(PAGE_SIZE));
      url.searchParams.set('sources', getSelectedSources().join(','));
      if (q) url.searchParams.set('q', q);
      const r = await fetch(url.toString(), { method: 'GET' });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
      renderRows(j.articles || []);
      renderPager(j.total_pages || 1);
      const ss = j.source || {};
      metaLine.textContent = `출처: ${ss.base || ''} · 소스=${ss.source || ''} · (스캔 ${ss.pages_scanned || SCAN_PAGES}p) · 결과 ${j.count_all || 0}건 · 페이지 ${j.page || p}/${j.total_pages || 1}`;
    } catch (e) {
      listBody.innerHTML = '<tr><td colspan="5" class="cell-err">오류: ' + esc(e.message) + '</td></tr>';
    } finally {
      loadingBanner.classList.remove('on');
    }
  }

  searchForm.addEventListener('submit', (e) => { e.preventDefault(); ensureSourceChecks(); loadPage(1); });
  clearBtn.addEventListener('click', () => { kw.value=''; loadPage(1); });
  const applySourcesBtn = document.getElementById('applySourcesBtn');
  if (applySourcesBtn) applySourcesBtn.addEventListener('click', () => { ensureSourceChecks(); loadPage(1); });
  renderPager(1);
  loadPage(1);

  (function chatPanelResizeFromTopLeft() {
    const panel = document.getElementById('chatPanel');
    const handle = document.getElementById('chatResizeHandle');
    if (!panel || !handle) return;

    const minW = 268;
    const minH = 220;
    function vvW() {
      return (window.visualViewport && window.visualViewport.width) ? window.visualViewport.width : window.innerWidth;
    }
    function vvH() {
      return (window.visualViewport && window.visualViewport.height) ? window.visualViewport.height : window.innerHeight;
    }
    function maxDims() {
      const vw = vvW();
      const vh = vvH();
      return {
        w: Math.min(720, Math.max(minW, vw - 16)),
        h: Math.min(Math.floor(vh * 0.92), Math.max(minH, vh - 48)),
      };
    }
    function clamp(v, a, b) {
      return Math.max(a, Math.min(b, v));
    }

    const sw = localStorage.getItem('chat_panel_w');
    const sh = localStorage.getItem('chat_panel_h');
    const iw = sw ? parseInt(sw, 10) : 0;
    const ih = sh ? parseInt(sh, 10) : 0;
    const md0 = maxDims();
    if (iw >= minW && iw <= md0.w) panel.style.width = iw + 'px';
    if (ih >= minH && ih <= md0.h) panel.style.height = ih + 'px';

    let resizing = false;
    let startX = 0;
    let startY = 0;
    let startW = 0;
    let startH = 0;

    function onMove(clientX, clientY) {
      if (!resizing) return;
      const dx = clientX - startX;
      const dy = clientY - startY;
      const md = maxDims();
      let w = startW - dx;
      let h = startH - dy;
      w = clamp(w, minW, md.w);
      h = clamp(h, minH, md.h);
      panel.style.width = w + 'px';
      panel.style.height = h + 'px';
    }

    function endResize() {
      if (!resizing) return;
      resizing = false;
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
      localStorage.setItem('chat_panel_w', String(panel.offsetWidth));
      localStorage.setItem('chat_panel_h', String(panel.offsetHeight));
    }

    function onDown(clientX, clientY) {
      resizing = true;
      startX = clientX;
      startY = clientY;
      startW = panel.offsetWidth;
      startH = panel.offsetHeight;
      document.body.style.userSelect = 'none';
      document.body.style.cursor = 'nw-resize';
    }

    handle.addEventListener('mousedown', function (e) {
      e.preventDefault();
      e.stopPropagation();
      onDown(e.clientX, e.clientY);
    });
    window.addEventListener('mousemove', function (e) {
      onMove(e.clientX, e.clientY);
    });
    window.addEventListener('mouseup', endResize);

    handle.addEventListener('touchstart', function (e) {
      if (e.touches.length !== 1) return;
      e.preventDefault();
      const t = e.touches[0];
      onDown(t.clientX, t.clientY);
    }, { passive: false });
    window.addEventListener('touchmove', function (e) {
      if (!resizing || e.touches.length !== 1) return;
      e.preventDefault();
      const t = e.touches[0];
      onMove(t.clientX, t.clientY);
    }, { passive: false });
    window.addEventListener('touchend', endResize);
    window.addEventListener('touchcancel', endResize);
  })();

  // ----- theme + chat toggle -----
  const themeBtn = document.getElementById('themeBtn');
  const chatToggleBtn = document.getElementById('chatToggleBtn');
  function setTheme(t) {
    document.documentElement.dataset.theme = t;
    localStorage.setItem('theme', t);
    syncThemeBtn();
  }
  function syncThemeBtn() {
    const isLight = document.documentElement.dataset.theme === 'light';
    themeBtn.title = isLight ? '어두운 테마로 전환' : '밝은 테마로 전환';
    themeBtn.setAttribute('aria-label', themeBtn.title);
  }
  const savedTheme = localStorage.getItem('theme');
  if (savedTheme === 'light' || savedTheme === 'dark') setTheme(savedTheme);
  else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) setTheme('light');
  else setTheme('dark');
  themeBtn.addEventListener('click', () => {
    const cur = document.documentElement.dataset.theme || 'dark';
    const next = cur === 'light' ? 'dark' : 'light';
    const apply = function () { setTheme(next); };
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      apply();
      return;
    }
    if (typeof document.startViewTransition === 'function') {
      document.startViewTransition(apply);
    } else {
      apply();
    }
  });

  function syncChatToggle() {
    const open = !document.body.classList.contains('chat-hidden');
    chatToggleBtn.title = open ? '채팅 닫기' : 'AI 채팅 열기';
    chatToggleBtn.setAttribute('aria-label', open ? 'AI 채팅 닫기' : 'AI 채팅 열기');
    chatToggleBtn.classList.toggle('is-active', open);
  }
  function setChatVisible(v){
    document.body.classList.toggle('chat-hidden', !v);
    localStorage.setItem('chat_visible', v ? '1' : '0');
    syncChatToggle();
  }
  const chatSaved = localStorage.getItem('chat_visible');
  setChatVisible(chatSaved === null ? false : chatSaved === '1'); // 기본은 숨김
  chatToggleBtn.addEventListener('click', () => {
    setChatVisible(document.body.classList.contains('chat-hidden'));
  });
  const chatCloseBtn = document.getElementById('chatCloseBtn');
  if (chatCloseBtn) chatCloseBtn.addEventListener('click', () => setChatVisible(false));

  const msgs = document.getElementById('msgs');
  const q = document.getElementById('q');
  const send = document.getElementById('send');
  const cancelBtn = document.getElementById('cancelBtn');
  const statusEl = document.getElementById('chatStatus');
  const aiDepth = document.getElementById('aiDepth');
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

  function safeNoticeUrl(u) {
    try {
      const x = new URL(u);
      if (x.protocol !== 'https:') return null;
      const h = x.hostname.toLowerCase();
      if (h === 'deu.ac.kr' || h.endsWith('.deu.ac.kr')) return x.href;
    } catch (err) {}
    return null;
  }

  function addAiBubble(reply, sources) {
    const d = document.createElement('div');
    d.className = 'bubble ai';
    const t = document.createElement('div');
    t.textContent = reply;
    d.appendChild(t);
    const cleanSources = (sources || []).filter(x => x && typeof x === 'object' && x.url);
    const valid = [];
    cleanSources.forEach(function (x) {
      const href = safeNoticeUrl(x.url);
      if (href) valid.push({ href: href, item: x });
    });
    if (valid.length) {
      const s = document.createElement('div');
      s.className = 'src';
      s.appendChild(document.createTextNode('출처:'));
      valid.forEach(function (o) {
        const a = document.createElement('a');
        a.href = o.href;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        const x = o.item;
        a.textContent = '[' + (x.index || '') + '] ' + (x.title || o.href);
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

  function removeNoticeScopeWarn() {
    if (!msgs) return;
    msgs.querySelectorAll('.chat-scope-warn').forEach(function (el) { el.remove(); });
  }

  function addNoticeScopeWarn() {
    if (!msgs) return;
    removeNoticeScopeWarn();
    const b = document.createElement('div');
    b.className = 'chat-scope-warn';
    b.setAttribute('role', 'status');
    b.setAttribute('aria-live', 'polite');
    b.textContent = '지금은 동의대 공지·학사 안내와 직접 관련된 질문만 도와드릴 수 있습니다. 등록, 일정, 장학, 공지 내용 등 학교 안내 위주로 물어봐 주세요.';
    msgs.appendChild(b);
    msgs.scrollTop = msgs.scrollHeight;
  }

  async function doSend() {
    const text = (q.value || '').trim();
    if (!text) return;
    if (chatAbort) return; // 이미 처리 중이면 무시
    removeNoticeScopeWarn();
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
      ensureSourceChecks();
      const r = await fetch('/api/chat/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: chatAbort.signal,
        body: JSON.stringify({
          message: text,
          mid: 'deu',
          sources: getSelectedSources(),
          pages: parseInt(aiDepth && aiDepth.value, 10) || 1,
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
          if (sj.notice_unrelated) addNoticeScopeWarn();
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

  // ----- 학사일정 · 간단게시판 -----
  let calEvents = [];
  const calView = new Date();

  function pad2(n) { return String(n).padStart(2, '0'); }
  function ymd(y, m, d) { return y + '-' + pad2(m) + '-' + pad2(d); }

  function renderCal() {
    const y = calView.getFullYear();
    const m = calView.getMonth() + 1;
    const title = document.getElementById('calTitle');
    if (title) title.textContent = y + '년 ' + m + '월';
    const grid = document.getElementById('calGrid');
    if (!grid) return;
    grid.innerHTML = '';
    const first = new Date(y, m - 1, 1);
    const lastDay = new Date(y, m, 0).getDate();
    const startPad = first.getDay();
    const prevLast = new Date(y, m - 1, 0).getDate();
    const totalCells = Math.ceil((startPad + lastDay) / 7) * 7;
    const t = new Date();
    const todayY = t.getFullYear();
    const todayM = t.getMonth() + 1;
    const todayD = t.getDate();
    for (let i = 0; i < totalCells; i++) {
      const cell = document.createElement('div');
      cell.className = 'cal-cell';
      if (i < startPad) {
        cell.classList.add('dim');
        cell.textContent = String(prevLast - startPad + i + 1);
      } else if (i >= startPad + lastDay) {
        cell.classList.add('dim');
        cell.textContent = String(i - (startPad + lastDay) + 1);
      } else {
        const d = i - startPad + 1;
        cell.textContent = String(d);
        if (calEvents.some(function (ev) { return ev.date === ymd(y, m, d); })) cell.classList.add('has-ev');
        if (y === todayY && m === todayM && d === todayD) cell.classList.add('today');
        const wd = new Date(y, m - 1, d).getDay();
        if (wd === 0) cell.classList.add('sun');
        if (wd === 6) cell.classList.add('sat');
      }
      grid.appendChild(cell);
    }
  }

  function renderUpcoming() {
    const ul = document.getElementById('upcomingList');
    if (!ul) return;
    const t = new Date();
    const todayStr = ymd(t.getFullYear(), t.getMonth() + 1, t.getDate());
    const upcoming = calEvents
      .filter(function (ev) { return ev.date >= todayStr; })
      .sort(function (a, b) { return a.date.localeCompare(b.date); })
      .slice(0, 8);
    if (!upcoming.length) {
      ul.innerHTML = '<li>예정된 참고 일정이 없습니다.</li>';
      return;
    }
    ul.innerHTML = upcoming.map(function (ev) {
      return '<li><time>' + esc(ev.date) + '</time>' + esc(ev.label) + '</li>';
    }).join('');
  }

  async function loadCalendarData() {
    try {
      const r = await fetch('/api/calendar');
      const j = await r.json();
      if (!r.ok) throw new Error('calendar');
      calEvents = j.events || [];
      const shortEl = document.getElementById('calNoteShort');
      if (shortEl && j.note) shortEl.textContent = j.note;
      const foot = document.getElementById('upcomingFoot');
      if (foot && j.note) foot.textContent = j.note;
      const calLink = document.getElementById('calOfficial');
      if (calLink && j.schedule_url) calLink.setAttribute('href', j.schedule_url);
      renderCal();
      renderUpcoming();
    } catch (e) {
      console.warn(e);
    }
  }

  const calPrev = document.getElementById('calPrev');
  const calNext = document.getElementById('calNext');
  if (calPrev) calPrev.addEventListener('click', function () {
    calView.setMonth(calView.getMonth() - 1);
    renderCal();
  });
  if (calNext) calNext.addEventListener('click', function () {
    calView.setMonth(calView.getMonth() + 1);
    renderCal();
  });

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState !== 'visible') return;
    renderCal();
    renderUpcoming();
  });

  function formatPinCreatedSeoul(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      if (isNaN(d.getTime())) return esc(String(iso));
      const s = d.toLocaleString('ko-KR', {
        timeZone: 'Asia/Seoul',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
      });
      return esc(s) + ' · Asia/Seoul';
    } catch (e) {
      return esc(String(iso));
    }
  }

  const PIN_ERR = {
    empty: '내용을 입력해 주세요.',
    too_long: '400자 이내로 적어 주세요.',
    invalid: '보낼 수 없는 내용입니다.',
    no_html: '꺾쇠괄호(HTML)는 사용할 수 없습니다.',
    rate_limit: '조금 쉬었다가 다시 올려 주세요.',
    duplicate: '같은 내용은 바로 반복해서 올릴 수 없습니다.',
    payload_too_large: '요청이 너무 큽니다.',
    json_only: 'JSON만 허용됩니다.',
    invalid_json: 'JSON 형식이 올바르지 않습니다.',
    invalid_body: '요청 본문이 올바르지 않습니다.',
    only_body_field: '허용되지 않은 필드입니다.',
    body_must_be_string: '본문 형식이 올바르지 않습니다.',
    server: '저장에 실패했습니다.'
  };

  async function loadPins() {
    const ul = document.getElementById('pinList');
    if (!ul) return;
    try {
      const r = await fetch('/api/pins?limit=40');
      const j = await r.json();
      if (!r.ok) throw new Error('pins');
      const posts = j.posts || [];
      if (!posts.length) {
        ul.innerHTML = '<li class="pin-empty" style="color:var(--muted);border:none">아직 글이 없습니다.</li>';
        return;
      }
      ul.innerHTML = posts.map(function (p) {
        const meta = formatPinCreatedSeoul(p.created);
        return '<li><div class="pin-meta">' + meta + '</div>' + esc(p.body || '') + '</li>';
      }).join('');
    } catch (e) {
      ul.innerHTML = '<li>게시판을 불러오지 못했습니다.</li>';
    }
  }

  const pinInput = document.getElementById('pinInput');
  const pinSend = document.getElementById('pinSend');
  const pinStatus = document.getElementById('pinStatus');
  if (pinSend && pinInput) {
    pinSend.addEventListener('click', async function () {
      const text = (pinInput.value || '').trim();
      if (!text) {
        if (pinStatus) pinStatus.textContent = PIN_ERR.empty;
        return;
      }
      if (pinStatus) pinStatus.textContent = '';
      pinSend.disabled = true;
      try {
        const r = await fetch('/api/pins', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ body: pinInput.value })
        });
        let j = {};
        try { j = await r.json(); } catch (e2) { j = {}; }
        if (!r.ok) {
          const code = j.error || 'invalid';
          if (pinStatus) pinStatus.textContent = PIN_ERR[code] || ('오류: ' + esc(String(code)));
          return;
        }
        pinInput.value = '';
        if (pinStatus) pinStatus.textContent = '올렸습니다.';
        await loadPins();
      } catch (e) {
        if (pinStatus) pinStatus.textContent = '네트워크 오류.';
      } finally {
        pinSend.disabled = false;
      }
    });
  }

  loadCalendarData();
  loadPins();

  send.addEventListener('click', doSend);
  q.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSend(); }
  });
  </script>
</body>
</html>
"""


def _client_ip() -> str:
    """
    기본: request.remote_addr만 사용 (X-Forwarded-For 스푸핑 방지).
    리버스 프록시 뒤에서 실제 IP가 필요하면 TRUST_PROXY=1 과 함께 프록시에서 XFF를 덮어쓰기 불가하게 설정하세요.
    """
    if (os.environ.get("TRUST_PROXY") or "").strip().lower() in ("1", "true", "yes", "on"):
        xff = (request.headers.get("X-Forwarded-For") or "").strip()
        if xff:
            hop = xff.split(",")[0].strip()[:45]
            if hop:
                return hop
    return ((request.remote_addr or "0.0.0.0").strip() or "0.0.0.0")[:45]


@app.route("/")
def index():
    return render_template_string(PAGE_TEMPLATE)


@app.get("/api/calendar")
def api_calendar():
    return jsonify(
        {
            "events": ACADEMIC_EVENTS,
            "note": CALENDAR_NOTE,
            "official_url": OFFICIAL_NOTICE_URL,
            "schedule_url": OFFICIAL_SCHEDULE_URL,
        }
    )


@app.get("/api/pins")
def api_pins_get():
    try:
        n = int(request.args.get("limit") or "40")
    except ValueError:
        n = 40
    return jsonify({"posts": pin_list_posts(n)})


@app.post("/api/pins")
def api_pins_post():
    ct = (request.content_type or "").lower()
    if "multipart/form-data" in ct:
        return jsonify({"error": "json_only"}), 415
    if request.content_length is not None and request.content_length > API_MAX_CONTENT_LENGTH:
        return jsonify({"error": "payload_too_large"}), 413
    if not request.is_json:
        return jsonify({"error": "json_only"}), 415
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "invalid_json"}), 400
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid_body"}), 400
    if any(k != "body" for k in payload):
        return jsonify({"error": "only_body_field"}), 400
    body = payload.get("body")
    if body is not None and not isinstance(body, str):
        return jsonify({"error": "body_must_be_string"}), 400
    ok, code, rec = pin_add_post(body=body if isinstance(body, str) else "", client_ip=_client_ip())
    if not ok:
        status = 400
        if code == "rate_limit":
            status = 429
        elif code == "duplicate":
            status = 409
        elif code == "server":
            status = 500
        return jsonify({"error": code}), status
    return jsonify({"post": rec})


def _parse_sources_from_request() -> list[str]:
    raw = (request.args.get("sources") or "").strip()
    if raw:
        parts = [p.strip() for p in raw.split(",") if p.strip() in ("deu", "dess")]
        if parts:
            return sorted(set(parts), key=lambda x: ("deu", "dess").index(x))
    leg = (request.args.get("source") or "deu").strip()
    if leg in ("deu", "dess"):
        return [leg]
    return ["deu"]


@app.get("/api/list")
def api_list():
    sources_list = _parse_sources_from_request()
    try:
        page = int(request.args.get("page") or "1")
    except ValueError:
        page = 1
    page = max(1, min(200, page))
    q = (request.args.get("q") or "").strip()
    try:
        scan_pages = int(request.args.get("scan_pages") or "2")
    except ValueError:
        scan_pages = 2
    scan_pages = max(1, min(20, scan_pages))
    try:
        page_size = int(request.args.get("page_size") or "20")
    except ValueError:
        page_size = 20
    page_size = max(5, min(50, page_size))

    try:
        data = _search_aggregated(sources=sources_list, q=q, result_page=page, scan_pages=scan_pages, page_size=page_size)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify(data)


_CACHE: dict[tuple[str, int], dict] = {}
_CACHE_TTL_SEC = 45.0


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


def _run_list_crawl(s: str, scan_pages: int) -> tuple[str, dict]:
    if s == "deu":
        one = run_deu_notice_crawl(base_url=DEFAULT_DEU_NOTICE_URL, pages=scan_pages, limit=10)
        one["source"]["source"] = "deu"
    else:
        one = run_crawl(
            base=DEFAULT_BASE,
            mid="Notice",
            pages=scan_pages,
            no_filter=True,
            fetch_body=False,
            headless=True,
            delay=0.22,
        )
        one["source"]["source"] = "dess"
    return s, one


def _search_aggregated(*, sources: list[str], q: str, result_page: int, scan_pages: int, page_size: int) -> dict:
    """
    선택한 소스(대표 공지·DESS) 각각 scan_pages만큼 긁어 합친 뒤
    - URL 중복 제거
    - 최신순 정렬
    - q가 있으면 제목 필터
    - 페이지네이션
    """
    srcs = sorted({s for s in sources if s in ("deu", "dess")}, key=lambda x: ("deu", "dess").index(x))
    if not srcs:
        srcs = ["deu"]

    key = (",".join(srcs), scan_pages)
    now = time.time()
    cached = _CACHE.get(key)
    if cached and (now - float(cached.get("_ts", 0.0)) < _CACHE_TTL_SEC):
        crawl = cached["crawl"]
    else:
        merged_articles: list[dict] = []
        bases: list[str] = []
        if len(srcs) == 1:
            s0, one = _run_list_crawl(srcs[0], scan_pages)
            bases.append(str(one.get("source", {}).get("base", "")))
            for a in one.get("articles") or []:
                row = dict(a)
                row["_origin"] = s0
                merged_articles.append(row)
        else:
            with ThreadPoolExecutor(max_workers=len(srcs)) as ex:
                futs = [ex.submit(_run_list_crawl, s, scan_pages) for s in srcs]
                results = [f.result() for f in futs]
            for s, one in sorted(results, key=lambda x: ("deu", "dess").index(x[0])):
                bases.append(str(one.get("source", {}).get("base", "")))
                for a in one.get("articles") or []:
                    row = dict(a)
                    row["_origin"] = s
                    merged_articles.append(row)
        seen: set[str] = set()
        arts_dedup: list[dict] = []
        for a in merged_articles:
            u = str(a.get("url") or "").strip()
            if u:
                if u in seen:
                    continue
                seen.add(u)
            arts_dedup.append(a)
        crawl = {
            "articles": arts_dedup,
            "source": {
                "base": " · ".join(b for b in bases if b),
                "source": "+".join(srcs),
                "mid": "Notice",
                "pages_scanned": scan_pages,
            },
        }
        if not crawl["source"]["base"]:
            crawl["source"]["base"] = DEFAULT_DEU_NOTICE_URL if "deu" in srcs else DEFAULT_BASE
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
    if not _chat_start_rate_allow(_client_ip()):
        return jsonify({"error": "chat_rate_limit"}), 429

    body = request.get_json(silent=True) or {}
    msg = (body.get("message") or "").strip()
    if not msg:
        return jsonify({"error": "message이 비었습니다."}), 400
    if len(msg) > 12000:
        return jsonify({"error": "message_too_long"}), 400

    mid = (body.get("mid") or "deu").strip() or "deu"
    if mid != "deu":
        mid = "deu"
    raw_sources = body.get("sources")
    sources_list: list[str] | None = None
    if isinstance(raw_sources, list):
        sources_list = sorted(
            {str(s).strip() for s in raw_sources if str(s).strip() in ("deu", "dess")},
            key=lambda x: ("deu", "dess").index(x),
        )
        if not sources_list:
            sources_list = None
    try:
        pages = int(body.get("pages", 1))
    except (TypeError, ValueError):
        pages = 1
    pages = max(1, min(20, pages))
    deep = bool(body.get("deep"))

    job_id = _new_job_id()
    cancel_event = threading.Event()
    now = time.time()
    with _CHAT_LOCK:
        _purge_chat_jobs_unlocked(now)
        _CHAT_JOBS[job_id] = {
            "status": "running",
            "cancel": cancel_event,
            "result": None,
            "error": None,
            "created_at": now,
            "finished_at": None,
        }

    def _run() -> None:
        try:
            # 지연 로딩: 서버 시작 시 RAG/pandas/numpy import 지연
            from deu_info.chat import answer_with_sources_cancellable

            out = answer_with_sources_cancellable(
                msg,
                mid=mid,
                sources=sources_list,
                pages=pages,
                include_article_bodies=deep,
                cancel_event=cancel_event,
            )
            with _CHAT_LOCK:
                if cancel_event.is_set():
                    _CHAT_JOBS[job_id]["status"] = "cancelled"
                else:
                    _CHAT_JOBS[job_id]["status"] = "done"
                    if isinstance(out, dict):
                        out_store = dict(out)
                        out_store["sources"] = _sanitize_chat_sources(out_store.get("sources"))
                        _CHAT_JOBS[job_id]["result"] = out_store
                    else:
                        _CHAT_JOBS[job_id]["result"] = out
                _CHAT_JOBS[job_id]["finished_at"] = time.time()
        except Exception as e:
            with _CHAT_LOCK:
                if cancel_event.is_set():
                    _CHAT_JOBS[job_id]["status"] = "cancelled"
                else:
                    _CHAT_JOBS[job_id]["status"] = "error"
                    _CHAT_JOBS[job_id]["error"] = str(e)
                _CHAT_JOBS[job_id]["finished_at"] = time.time()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"job_id": job_id})


@app.get("/api/chat/status")
def api_chat_status():
    job_id = (request.args.get("job_id") or "").strip()
    if not job_id:
        return jsonify({"error": "job_id가 필요합니다."}), 400
    with _CHAT_LOCK:
        _purge_chat_jobs_unlocked(time.time())
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
                    "sources": _sanitize_chat_sources(out.get("sources")),
                    "crawl_summary": out.get("crawl_summary"),
                    "ingest": out.get("ingest"),
                    "notice_unrelated": bool(out.get("notice_unrelated")),
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
        job["finished_at"] = time.time()
    return jsonify({"status": "cancelled"})


@app.get("/api/debug/env")
def api_debug_env():
    """로컬 디버그 전용. 운영·외부 노출 시 정보 유출이 되므로 DEU_DEV=1 일 때만 허용."""
    if (os.environ.get("DEU_DEV") or "").strip().lower() not in ("1", "true", "yes", "on"):
        return jsonify({"error": "forbidden"}), 403
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


def _is_loopback_host(host: str) -> bool:
    h = (host or "").strip().lower().strip("[]")
    return h in ("127.0.0.1", "localhost", "::1")


def main() -> None:
    port = int(os.environ.get("PORT", "5050"))
    host = os.environ.get("HOST", "127.0.0.1")
    open_b = os.environ.get("OPEN_BROWSER", "1").strip() not in ("0", "false", "no")

    # -------------------------------------------------------------------------
    # 자동 재시작(리로더): 루프백(127.0.0.1 등)에서는 기본 ON → .py 저장 시 프로세스
    # 가 다시 뜨므로 브라우저 새로고침만 하면 됨. 끄려면 DEU_NO_RELOAD=1.
    # 0.0.0.0 등 외부 바인딩에서는 기본 OFF(실수로 이중 프로세스·노출 방지).
    #   외부에서도 리로드 쓰려면 DEU_RELOAD=1 (개발용).
    # 디버그 툴바/인터랙티브 트레이스는 DEU_DEV=1 일 때만 (보안상 외부 바인딩 비권장).
    # -------------------------------------------------------------------------
    dev = (os.environ.get("DEU_DEV") or "").strip().lower() in ("1", "true", "yes", "on")
    no_reload = (os.environ.get("DEU_NO_RELOAD") or "").strip().lower() in ("1", "true", "yes", "on")
    force_reload = (os.environ.get("DEU_RELOAD") or "").strip().lower() in ("1", "true", "yes", "on")
    use_reloader = (not no_reload) and (_is_loopback_host(host) or dev or force_reload)
    if dev and not _is_loopback_host(host):
        print(
            "경고: DEU_DEV=1 인 상태에서 외부에 바인딩하면 디버거 노출 위험이 있습니다.",
            file=sys.stderr,
        )

    if open_b:
        import threading
        import time
        import webbrowser

        def _open() -> None:
            time.sleep(0.6)
            webbrowser.open(f"http://{host}:{port}/")

        threading.Thread(target=_open, daemon=True).start()

    print(f"{APP_NAME} — http://{host}:{port}/  (종료: Ctrl+C)", file=sys.stderr)
    if use_reloader:
        print(
            "코드·템플릿 저장 시 서버 자동 재시작(리로드). 끄려면 DEU_NO_RELOAD=1",
            file=sys.stderr,
        )
    if dev:
        print("DEU_DEV=1 · Werkzeug 디버그 UI 사용 중", file=sys.stderr)
    app.run(host=host, port=port, debug=dev, use_reloader=use_reloader)


if __name__ == "__main__":
    main()
