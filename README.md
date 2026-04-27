# deu_info

동의대 **대표 공지**와 **DESS(학생서비스센터)** 를 한 화면에서 검색하고, **학사일정·간단게시판**을 두며 **AI 질문(출처 링크)** 까지 쓸 수 있는 **로컬 웹 앱**입니다.

---

## 주요 기능

| 구분 | 내용 |
|------|------|
| **공지 목록** | 소스 `deu` / `dess` 선택 후 **적용** 시 목록 갱신, 검색·페이지네이션 |
| **학사일정** | 참고용 달력 + [공식 학사일정](https://www.deu.ac.kr/www/scheduleList.do) 링크 |
| **간단게시판** | 제목 없이 본문만 저장(수정·삭제 API 없음), IP당 속도 제한·중복 방지 |
| **다가오는 일정** | 참고 일정 중 오늘 이후 항목 요약 |
| **AI 채팅** | 선택한 소스·페이지 깊이 기준 RAG 답변, 출처 URL(동의대 도메인만 링크) |
| **공지 무관 질문** | 판단 시 채팅 패널에 안내 배너(키워드·제목 유사도 기반) |
| **테마** | 다크 / 라이트, 전환 시 뷰 전환·카드 색 전환 애니메이션 |
| **보안·운영** | 메모판 JSON 전용·크기 제한, 채팅 job TTL/개수 상한, 디버그 API는 `DEU_DEV=1` 시만 등 |

---

## 요구 사항

- Python **3.11+** 권장 (프로젝트에서 3.13 사용 예시 많음)
- AI 사용 시: [OpenAI API 키](https://platform.openai.com/) (`OPENAI_API_KEY`)

---

## 설치·실행

프로젝트 **루트**에서:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export OPENAI_API_KEY="sk-..."   # AI 쓸 때만
python -m deu_info
```

- 기본 주소: **http://127.0.0.1:5050/**
- 포트: `PORT=5051 python -m deu_info`
- 바인딩: `HOST=0.0.0.0 python -m deu_info` (로컬만 쓰면 `127.0.0.1` 권장)

### 코드 수정 후 반영

- **루프백(127.0.0.1 등)** 에서는 기본적으로 **파일 저장 시 자동 리로드**(Werkzeug). 끄려면 `DEU_NO_RELOAD=1`.
- **디버그 UI**(에러 트레이스 등): `DEU_DEV=1 python -m deu_info` — **외부 공개 시 사용 금지.**

---

## 사용 방법 (UI)

1. **소스**: 대표 공지 / DESS 체크 → **적용** (체크만으로는 목록이 안 바뀜).
2. **검색**: 키워드 입력 후 검색, **초기화**로 조건 리셋.
3. **학사일정**: 월 이동, 오늘 날짜 강조는 **기기 로컬 날짜** 기준. 정확한 일정은 하단 링크(학교 학사일정 페이지).
4. **간단게시판**: 짧은 글만 입력 → **올리기**. HTML·첨부 불가, 저장은 `deu_info/local_data/`(또는 `DEU_DATA_DIR`).
5. **AI 채팅**: 우측 하단(또는 헤더)에서 패널 열기, 참고 페이지 수·DESS 본문 옵션 선택 후 질문.

자세한 모듈 설명은 [docs/deu-info.md](docs/deu-info.md) 를 참고하세요.

---

## 환경 변수 (자주 쓰는 것)

| 변수 | 설명 |
|------|------|
| `OPENAI_API_KEY` | AI 채팅·RAG |
| `PORT`, `HOST` | 서버 포트·바인딩 |
| `DEU_DEV` | `1` 이면 Flask 디버그 + `/api/debug/env` 허용 |
| `DEU_NO_RELOAD` | `1` 이면 자동 리로드 끔 |
| `DEU_DATA_DIR` | 간단게시판 JSON 저장 디렉터리(기본: `deu_info/local_data/`) |
| `TRUST_PROXY` | `1` 일 때만 `X-Forwarded-For`로 클라 IP(신뢰 프록시 뒤에서만) |

---

## 프로젝트 구조 (요약)

```
deu_info/
  web.py              # Flask, 페이지·API
  crawler.py          # 공지 크롤
  rag.py              # RAG·공지 무관 판별 등
  chat.py             # 채팅 진입
  pin_board.py        # 간단게시판 저장·검증
  academic_calendar_data.py  # 참고 학사일정 정적 데이터
docs/
  deu-info.md         # 실행·UI 보조 문서
requirements.txt
```

---

## 변경·추가 요약 (이번에 정리된 내용)

- **UI**: 3열(학사일정·간단게시판 / 공지 메인 / 다가오는 일정), 다크·라이트, 메인 카드 다크 테두리 글로우.
- **API**: `/api/calendar`, `/api/pins`(GET/POST), 채팅·목록 API에 보안·남용 완화.
- **게시판**: 서울(KST) 시각, 로컬 JSON, `.gitignore`에 `deu_info/local_data/`.
- **학사일정 링크**: 공식 페이지 `scheduleList.do` 연결.
- **README / 문서**: 실행법·기능 정리.

---

## 라이선스·면책

학교 공지·학사일정은 **동의대학교 공식 안내**가 우선입니다. 이 도구는 **개인 학습·편의**용으로 두는 것을 권장합니다.
