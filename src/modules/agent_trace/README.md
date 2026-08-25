# agent_trace

정합성·추적성 검사. 추적성·내용일치·RTM.

## 공개 인터페이스
`__init__.py`에서 export하는 것만 외부에서 쓴다:

`TraceabilityChecker` `ContentMatchChecker` · `extract_id_anchors` `extract_id_statements` `build_rtm`.

## 입출력 스키마
검사 Agent는 공통 Finding 스키마로 반환한다(루트 CLAUDE.md 참조). Finding·Document 등 공통 타입은 `modules.shared`.

## 의존성
- 외부 패키지: 없음(표준 라이브러리).
- 모듈 의존: `shared`(Checker·Document·RtmRow).
