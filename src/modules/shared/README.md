# shared

공통 타입·계약 — Finding·Document·Checker 등을 모든 모듈이 여기서 가져온다.

## 공개 인터페이스
`__init__.py`에서 export하는 것만 외부에서 쓴다:

`Finding` `Evidence` `Severity` `Anchor` `Section` `Document` `Chunk` `RtmRow` · `Config` `ReviewConfig` · `Checker` `Context` · `verify_quotes`(환각방지) `suggest_revision` · LLM JSON 파서 `_parse` · 근거 재확인 검색 도구 `DocTools`.

## 입출력 스키마
검사 Agent는 공통 Finding 스키마로 반환한다(루트 CLAUDE.md 참조). Finding·Document 등 공통 타입은 `modules.shared`.

## 의존성
- 외부 패키지: 없음(표준 라이브러리만).
- 모듈 의존: `llm_client`(Context.llm·Checker의 LLMClient 타입).
