# agent_checklist

검토 기준(Criterion) → 검사기 라우팅. **기준이 자기를 검사할 규칙의 이름을 댄다.**

## 공개 인터페이스
`__init__.py`에서 export하는 것만 외부에서 쓴다:

`mode_for(criterion)` `check_name(criterion)` `checker_key(criterion)`
`rule_checkers(criteria, field_specs=())` `llm_checkers_for(criteria, doc_max_chars)`
`checkers_for(criteria, ...)` `RULE_CHECKS` `AGENT_MODES`.

## 두 축: mode 와 check

`mode` 는 **어떻게** 물을지, `check` 는 규칙일 때 **무엇이** 검사할지다.

| mode | 뜻 | 검사기 |
|---|---|---|
| `규칙` | 코드가 검사한다. LLM 없음 | `check` 가 가리키는 것 하나 |
| `LLM-조각` | 문서를 청크로 잘라 조각마다 묻는다 | `ChunkCriteriaChecker` 한 벌 |
| `LLM-문서` | 문서를 통째로 한 번 묻는다 | `WholeDocCriteriaChecker` 한 벌 |
| `사람` | 도구가 판정할 수 없다 | 없음 |

`mode` 를 안 적으면 `AGENT_MODES` 가 `agent` 라벨로 기본값을 정한다. 어휘에 없는
값은 오타이므로 `사람`으로 떨어뜨린다 — 조용히 통과시키면 검사되지 않은 기준이
검사된 것처럼 보인다.

## check — 규칙 기준의 라우팅

```yaml
- 'no': '9'
  agent: 형식·완전성
  mode: 규칙
  check: required_sections     # ← 이 기준을 검사하는 규칙의 이름
```

`RULE_CHECKS` 의 열쇠다. 현재: `placeholder` `required_sections` `field_presence`
`filename` `abbrev` `reflist` `text_pattern`.

**`check` 가 없거나 모르는 이름이면 검사기가 안 붙는다** — 그 기준을 검사하는 규칙이
아직 없다는 뜻이고, 조립 계층이 `manual` 로 두면서 이유를 남긴다. 오타를 조용히
넘기면 그 기준이 검사되지 않은 채 통과한다.

예전에는 `agent` 라벨로 이었다. 라벨은 여섯 개뿐인데 기준은 팀마다 수십 개라,
"형식·완전성" 하나에 EV2 의 규칙 기준 15개가 매달렸다. 규칙 검사기는 둘뿐이었고 그
둘의 지적이 15개 전부에 복사돼, 실제로 검사된 것은 둘인데 화면은 열다섯을 검사했다고
말했다. 라벨은 "어느 관점인가"를 뜻하지 "무엇이 검사하는가"가 아니다.

### 검사기 열쇠 (`checker_key`)

매개변수 없는 검사는 여러 기준이 같은 것을 대도 한 벌이면 된다(`placeholder`).
`params` 를 가진 기준은 **기준마다 따로** 만든다(`field_presence#20`) — 한 벌을
나눠 가지면 표지 항목과 개정기록 항목의 지적이 똑같아진다.

## 매개변수 주입

검사에 필요한 값은 코드가 아니라 데이터에서 온다.

```yaml
  check: placeholder
  params:
    placeholder_markers: ["미정", "미확인", "TBD", "TBC"]
```

`field_specs` 만 예외로 조립 계층이 넘긴다 — 어느 산출물인지는 파일명을 봐야 알고,
그건 모듈이 아니라 앱이 하는 일이다. 기준은 `params.fields` 에 이름만 적어 자기 몫을
고른다(안 적으면 그 산출물의 칸 전부).

## 입출력 스키마
검사 Agent는 공통 Finding 스키마로 반환한다(루트 CLAUDE.md 참조). Finding·Document
등 공통 타입은 `modules.shared`.

## 의존성
- 외부 패키지: 없음(표준 라이브러리).
- 모듈 의존: `shared`(Checker), `preset`(MODES), `agent_format`(규칙 검사기),
  `agent_quality`(ChunkCriteriaChecker·WholeDocCriteriaChecker), `doc_parser`(FieldSpec).
