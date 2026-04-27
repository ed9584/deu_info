"""간단게시판: 본문만 저장, 수정/삭제 API 없음. 로컬 JSON + 속도 제한."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_SEOUL = ZoneInfo("Asia/Seoul")

_LOCK = threading.Lock()
_RATE_TIMES: dict[str, list[float]] = {}
_RECENT_BODY_BY_IP: dict[str, list[str]] = {}

_MAX_BODY_CHARS = 400
_MAX_STORED_POSTS = 120
_RATE_WINDOW_SEC = 900
_MAX_POSTS_PER_WINDOW = 4
API_MAX_CONTENT_LENGTH = 2048
_WS_RE = re.compile(r"\s+", re.UNICODE)


def _data_dir() -> Path:
    raw = (os.environ.get("DEU_DATA_DIR") or "").strip()
    if raw:
        p = Path(raw).expanduser()
    else:
        p = Path(__file__).resolve().parent / "local_data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _data_path() -> Path:
    return _data_dir() / "pin_board.json"


def _load_unlocked() -> dict[str, Any]:
    path = _data_path()
    if not path.is_file():
        return {"posts": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"posts": []}


def _save_unlocked(data: dict[str, Any]) -> None:
    path = _data_path()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")


def _normalize_body(raw: str) -> str | None:
    s = (raw or "").replace("\x00", "").strip()
    if not s:
        return None
    s = _WS_RE.sub(" ", s)
    if len(s) > _MAX_BODY_CHARS:
        return None
    if "<" in s or ">" in s:
        return None
    if not s:
        return None
    return s


def _spam_repeat(ip: str, body: str) -> bool:
    lst = _RECENT_BODY_BY_IP.setdefault(ip, [])
    if body in lst:
        return True
    return False


def _remember_body(ip: str, body: str) -> None:
    lst = _RECENT_BODY_BY_IP.setdefault(ip, [])
    lst.append(body)
    if len(lst) > 12:
        del lst[:-12]


def add_post(*, body: str, client_ip: str) -> tuple[bool, str, dict[str, Any] | None]:
    """
    Returns (ok, code, record).
    code: ok | empty | too_long | invalid | no_html | rate_limit | duplicate | server
    """
    ip = (client_ip or "0.0.0.0").strip() or "0.0.0.0"
    normalized = _normalize_body(body)
    if normalized is None:
        if (raw := (body or "").replace("\x00", "").strip()) and len(raw) > _MAX_BODY_CHARS:
            return False, "too_long", None
        if raw and ("<" in raw or ">" in raw):
            return False, "no_html", None
        return False, "empty", None

    with _LOCK:
        if _spam_repeat(ip, normalized):
            return False, "duplicate", None
        now = time.time()
        rlst = _RATE_TIMES.setdefault(ip, [])
        rlst[:] = [t for t in rlst if now - t < _RATE_WINDOW_SEC]
        if len(rlst) >= _MAX_POSTS_PER_WINDOW:
            return False, "rate_limit", None

        data = _load_unlocked()
        posts: list[dict[str, Any]] = list(data.get("posts") or [])
        rec = {
            "id": uuid.uuid4().hex[:16],
            "body": normalized,
            "created": datetime.now(_SEOUL).isoformat(timespec="seconds"),
        }
        posts.append(rec)
        if len(posts) > _MAX_STORED_POSTS:
            posts = posts[-_MAX_STORED_POSTS:]
        data["posts"] = posts
        try:
            _save_unlocked(data)
        except OSError:
            return False, "server", None
        rlst.append(time.time())
        _remember_body(ip, normalized)

    return True, "ok", rec


def list_posts(limit: int = 40) -> list[dict[str, Any]]:
    lim = max(1, min(80, int(limit)))
    with _LOCK:
        data = _load_unlocked()
    posts = list(data.get("posts") or [])
    out = posts[-lim:]
    out.reverse()
    return out
