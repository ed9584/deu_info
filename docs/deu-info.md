# deu_info

동의대 공지를 크롤링해 **목록·검색**으로 보고, **AI 답변 + 출처 링크**를 제공하는 로컬 웹 앱입니다.

## 폴더 구조(루트 기준)


| 경로                 | 설명                                 |
| ------------------ | ---------------------------------- |
| `deu_info/`        | 앱 패키지 (`web`, `crawler`, `rag`, …) |
| `data/`            | SQLite·ChromaDB 등 로컬 데이터(기본)       |
| `docs/`            | 이 문서 등                             |
| `requirements.txt` | Python 의존성                         |
| `.venv/`           | 가상환경(로컬 생성, Git 제외 권장)             |


## 실행

프로젝트 루트에서:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m deu_info
```

- 로컬에서 코드 수정 후 **새로고침만**으로 반영: `DEU_DEV=1 python -m deu_info` (자동 재시작). **운영 배포에서는 켜지 마세요.**
- 기본 URL: `http://127.0.0.1:5050/`
- 포트: `PORT=5051 python -m deu_info`

## UI 참고

- **대표 공지 / DESS**: 체크 후 **적용**을 눌러야 목록이 갱신됩니다.
- **AI 패널**: 헤더 **왼쪽 위** 크기 버튼을 누른 채 드래그해 크기 조절(저장됨).

## AI (선택)

```bash
export OPENAI_API_KEY="sk-..."
python -m deu_info
```

## 모듈

- `deu_info/web.py` — Flask, `/api/list`, `/api/chat`
- `deu_info/crawler.py` — 크롤러
- `deu_info/rag.py` — RAG·출처
- `deu_info/pipeline.py` — SQLite·문서 파이프라인

