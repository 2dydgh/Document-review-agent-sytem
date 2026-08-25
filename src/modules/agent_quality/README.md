# agent_quality

표현·내용 품질 검사 (LLM). 모호·모순 일관성.

## 공개 인터페이스
`__init__.py`에서 export하는 것만 외부에서 쓴다:

`ChunkCriteriaChecker`.

## 입출력 스키마
검사 Agent는 공통 Finding 스키마로 반환한다(루트 CLAUDE.md 참조). Finding·Document 등 공통 타입은 `modules.shared`.

## 인용 구조(rescue)

원문 대조에 실패한 지적 후보는 즉시 버리지 않고, 검색 도구(`find_term`)를 쥔
LLM 재질의(후보당 최대 2회)로 실재 근거를 다시 대게 한다(`rescue.py`). 판정은
그대로 `verify_quotes` 가 내린다 — 재인용도 대조에 실패하면 그때 버린다.
복원·제외 건수는 INFO 로 드러난다. 상한은 `Context.rescue_max`(직접 만들면
기본 0 = 끔)이고 **검사기 하나당** 상한이다 — 조각 단위 `ChunkCriteriaChecker`
와 문서 전체 단위 `WholeDocCriteriaChecker`가 각자 쓴다. DocSuree 배포 기본값 10은
`Config.llm_rescue_max`(`settings.toml`의 `[llm] rescue_max`)가 채운다. 0이면
예전처럼 즉시 폐기한다.

## 의존성
- 외부 패키지: 없음(표준 라이브러리).
- 모듈 의존: `shared`(Checker·Context·verify_quotes 등).
