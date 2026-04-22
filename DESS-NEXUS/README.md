# DESS Nexus

동의대학교 공지사항을 크롤링해서 **목록/검색**으로 보기 좋게 보여주고, 질문을 입력하면 공지 내용을 근거로 **AI가 답변 + 출처 링크**를 제공하는 로컬 웹 앱입니다.

## 데이터 소스

앱에서 소스를 선택할 수 있습니다.

- **대표 홈페이지 공지(기본)**: `https://www.deu.ac.kr/www/deu-notice.do`
- **학생서비스센터(DESS) 공지(옵션)**: `https://dess.deu.ac.kr/?mid=Notice`

## 주요 기능

- **공지 목록 크롤링**: 공지 목록을 가져와 표로 표시
- **검색**: 키워드가 포함된 공지만 필터링
- **페이지네이션(검색 결과 기준)**: 검색 결과를 최신순으로 정렬한 뒤 결과 수에 맞춰 1/2/3… 페이지로 표시
- **다크/라이트 테마**: 버튼으로 테마 전환(설정 저장)
- **AI 챗 패널 토글**: 기본 숨김, 버튼으로 열기/닫기(설정 저장)
- **AI 질의응답(RAG)**: 관련 공지를 찾아 답하고, 참고한 공지의 URL(출처)를 함께 표시
- **저장/검색(서버 내부)**:
  - SQLite: 크롤 결과 스냅샷 저장
  - ChromaDB: 벡터 검색

## 설치 및 실행 방법

아래 커맨드는 **프로젝트 루트(= `requirements.txt`가 있는 폴더)** 에서 실행합니다.

```bash
cd <your-repo-directory>
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m deu_nexus
```

브라우저 접속:

- `http://127.0.0.1:5050/`

포트 변경:

```bash
PORT=8080 python -m deu_nexus
```

## AI 사용(선택)

AI 채팅을 사용하려면 API 키를 **환경변수로만** 설정하세요.

```bash
export OPENAI_API_KEY="sk-..."
python -m deu_nexus
```

> 주의: API 키를 코드/README/프론트에 하드코딩하지 마세요.

## 사용 방법(UI)

- **소스 선택**: 상단 드롭다운에서 대표 공지 / DESS 공지 선택
- **검색**: 검색어 입력 → 포함된 공지 목록만 표시(최신순)
- **AI 챗**: 상단 `AI 챗` 버튼 → 패널 열기 → 질문 입력 → 답변 + 출처 링크 확인

## 요구 사항

- **Python 3.9+**
- **Chrome 브라우저 설치** (Selenium 사용)

## 데이터 저장 위치

기본 저장 경로는 프로젝트 루트의 `data/` 입니다.

- SQLite: `data/deu_articles.sqlite`
- ChromaDB: `data/chroma_db/`

환경변수 `DEU_DATA_DIR`로 저장 경로를 변경할 수 있습니다.

## 프로젝트 구조(핵심)

- `deu_nexus/web.py`: Flask 웹 UI + `/api/list`, `/api/chat`
- `deu_nexus/crawler.py`: 공지 크롤러(대표 공지 + DESS)
- `deu_nexus/rag.py`: LangChain + ChromaDB 기반 RAG(출처 포함)
- `deu_nexus/pipeline.py`: SQLite 저장 + 문서 변환(지연 로딩)

