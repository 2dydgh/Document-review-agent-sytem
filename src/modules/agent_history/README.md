# agent_history

검토 의견·이력 관리. 문서를 계보로 이어 관리하고, 회신본의 반영 여부를 확인한다.
순수 규칙(LLM 없음) — 파일명과 저장된 지적(findings)만으로 판정한다.

## 공개 인터페이스
`__init__.py`에서 export하는 것만 외부에서 쓴다:

`guess_original_name(filename)` — 개정 접미사 제거해 원 이름 추정 ·
`find_prior(entries, name)` — 이력에서 이전 검토 찾기 ·
`match_findings(prior, new) -> LineageReview` — 이전 지적 ↔ 새 지적 매칭(닫힘/열림/신규) ·
`LineageReview` · `LineageItem` · `OBSERVED`(그대로 있음·안 보임 — **기계가 본 것**) ·
`STATUSES`(미반영·반영됨·해당없음 — **사람이 내린 판정**) · `DEFAULT_VERDICT` · `LEGACY`.

둘을 가른 이유: `안 보임` 은 "같은 인용을 못 찾았다" 일 뿐이다. 문장을 다듬어도,
절이 옮겨져도 못 찾는다 — 고쳤는지는 사람이 정한다. 예전 `열림`·`닫힘` 은 그 추정을
단정으로 만들었고, 이슈 트래커 말이라 검토자에게 통하지도 않았다.

## 입출력 스키마
UI finding dict(`{checker, message, section, evidence:[{quote}]}`)로 동작한다 —
Finding 객체가 아니라 HistoryStore·payload 에 저장된 형태를 그대로 다룬다.

## 의존성
- 외부 패키지: 없음(표준 라이브러리 re·dataclasses).
- 모듈 의존: 없음. (계보 저장·HistoryStore 는 app 이 한다.)
