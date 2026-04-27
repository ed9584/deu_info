"""참고용 학사일정(정적). 정확한 일정은 학교 학사공지를 확인하세요."""

from __future__ import annotations

# date: YYYY-MM-DD, label: 표시 문구
ACADEMIC_EVENTS: list[dict[str, str]] = [
    {"date": "2025-09-01", "label": "2학기 개강(참고)", "kind": "term"},
    {"date": "2025-10-31", "label": "수업일수 1/2 시점 인근(참고)", "kind": "misc"},
    {"date": "2025-12-22", "label": "동계방학 시작(대략, 참고)", "kind": "vacation"},
    {"date": "2026-01-02", "label": "신정", "kind": "holiday"},
    {"date": "2026-02-01", "label": "1학기 수강신청 시즌(참고)", "kind": "reg"},
    {"date": "2026-03-02", "label": "1학기 개강(참고)", "kind": "term"},
    {"date": "2026-05-05", "label": "어린이날", "kind": "holiday"},
    {"date": "2026-06-03", "label": "대체공휴일(참고)", "kind": "holiday"},
    {"date": "2026-06-06", "label": "현충일", "kind": "holiday"},
    {"date": "2026-06-15", "label": "1학기 기말·하계방학 전후(참고)", "kind": "exam"},
    {"date": "2026-08-15", "label": "광복절", "kind": "holiday"},
    {"date": "2026-08-17", "label": "임시공휴일(해당 시, 참고)", "kind": "holiday"},
    {"date": "2026-09-01", "label": "2학기 개강(참고)", "kind": "term"},
]

CALENDAR_NOTE = (
    "위 일정은 일반적인 대학 학기 흐름을 바탕으로 한 참고용입니다. "
    "등록·수강·시험·휴일은 매년 학교 학사일정 공지가 우선입니다."
)

# 학교 공지(대표)
OFFICIAL_NOTICE_URL = "https://www.deu.ac.kr/www/deu-notice.do"
# 학사일정 공식 페이지
OFFICIAL_SCHEDULE_URL = "https://www.deu.ac.kr/www/scheduleList.do"
