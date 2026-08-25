# app

DocSuree 조립 계층. 모듈들의 **공개 인터페이스로만** 조립한다 — 모듈은 DocSuree를
몰라야 하고, 팀명·문서명·규칙값 하드코딩은 여기가 아니라 presets/에 있다.

## 구성
- `server.py` — FastAPI 웹/API (정적 자산은 `web/`, 검토 이력은 `.docreview/`)
- `cli.py` — `docreview` 엔트리포인트 (`app.cli:main`)
- `orchestrator.py` — 검토 파이프라인 조립 (load_document→normalize→chunk→체커→report)
- `registry.py` — agent 모듈 체커 등록
- `config.py` — settings.toml + 체크리스트 YAML → Config (스키마는 modules.shared)
- `history.py` — 검토 이력 저장

## 의존성
- 외부 패키지: fastapi, uvicorn, python-multipart, pyyaml.
- 모듈 의존: `doc_parser` `llm_client` `preset` `report` `agent_format` `agent_quality`
  `agent_trace` `agent_checklist` `shared` — 전부 공개 인터페이스로만.
