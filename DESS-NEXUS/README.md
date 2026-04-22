# DESS Nexus

동의대학교 학생서비스센터(DESS) 공지사항을 **Selenium으로 크롤링**하고, 크롤링된 내용을 **검색/필터링**하여 목록으로 보여주며, 질문을 입력하면 **AI(RAG)** 가 공지 내용을 근거로 답변하고 **출처 링크**까지 제공하는 로컬 웹 / 앱

## 주요 기능

- **공지 목록 크롤링**: [https://www.deu.ac.kr/www/deu-notice.do](https://www.deu.ac.kr/www/deu-notice.do) 공지 게시판(XpressEngine)에서 제목/작성자/날짜/조회/링크 수집
- **검색(키워드 필터)**: 검색어를 입력하면 해당 키워드가 포함된 공지 목록만 표시
- **페이지네이션**: 하단 `1 2 3` 버튼으로 게시판 페이지를 이동하며 목록 갱신
- **AI 질의응답(RAG)**: 공지 내용을 기반으로 답변 + 참고한 공지의 **URL(출처 링크)** 제공
- **데이터 저장/검색**:
  - **Pandas**로 크롤 결과 정리
  - **SQLite**에 스냅샷 저장
  - **ChromaDB(벡터DB)** 에 임베딩 후 **LangChain RAG** 로 관련 공지 검색

## 설치 및 실행 방법

아래 커맨드는 프로젝트 루트(= `requirements.txt`가 있는 폴더)에서 실행

```bash
cd /Users/404/Desktop/-Happy-/prj/Crawling
```

### 1) 가상환경 생성 및 의존성 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) 웹 서버 실행

```bash
python -m deu_nexus
```

실행 후 브라우저에서 아래로 접속

- `http://127.0.0.1:5050/`

포트를 바꾸고 싶으면:

```bash
PORT=8080 python -m deu_nexus
```

### 3) AI 기능 사용(선택)

AI 채팅을 쓰려면 OpenAI API 키를 환경변수로 설정

```bash
export OPENAI_API_KEY="sk-..."
python -m deu_nexus
```

> 주의: API 키는 **서버 환경변수로만** 두고, 프론트엔드 코드에 넣지 마세요.

### 4) 크롤러만 단독 실행(선택)

```bash
python -m deu_nexus.crawler --pages 1 --no-filter
```

## 사용 방법(UI)

- **검색**: 상단 검색창에 키워드를 입력하고 검색 → 포함된 공지만 리스트에 표시됩니다.
- **페이지 이동**: 하단 `1 2 3` 버튼 클릭 → 해당 게시판 페이지로 이동합니다.
- **AI 질문**: 오른쪽 채팅창에 질문 입력 → 답변 + 출처 링크가 출력됩니다.

## 요구 사항

- **Python 3.9+** (권장: 3.10 이상)
- **Chrome 브라우저 설치 필요** (Selenium이 Chrome을 사용)

## 프로젝트 구조(핵심 파일)

- `deu_nexus/web.py`: Flask 웹 UI + `/api/list`, `/api/chat`
- `deu_nexus/crawler.py`: Selenium 크롤러(목록/본문)
- `deu_nexus/rag.py`: LangChain + ChromaDB 기반 RAG
- `deu_nexus/pipeline.py`: Pandas/SQLite/Document 변환

## 데이터 저장 위치

기본 저장 경로는 프로젝트 루트의 `data/` 입니다.

- SQLite: `data/deu_articles.sqlite`
- ChromaDB: `data/chroma_db/`

환경변수 `DEU_DATA_DIR`로 저장 경로를 변경할 수 있습니다.