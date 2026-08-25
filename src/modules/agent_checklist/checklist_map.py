"""검토 기준(Criterion) → 검사기 연결.

**기준이 자기를 검사할 규칙의 이름을 댄다**(`check:`). 코드가 추측하지 않는다.

예전에는 `agent` 라벨로 이었다. 라벨은 여섯 개뿐인데 기준은 팀마다 수십 개라,
"형식·완전성" 하나에 EV2 의 규칙 기준 15개가 전부 매달렸다. 규칙 검사기는 둘뿐이고
그 둘이 낸 지적이 15개 전부에 복사됐다 — 실제로 검사된 것은 둘인데 화면은 열다섯을
검사했다고 말했다. 라벨은 "어느 관점인가"를 뜻하지 "무엇이 검사하는가"가 아니다.

`check:` 가 없는 규칙 기준은 **검사하는 규칙이 아직 없다**는 뜻이고 사람 몫으로
떨어진다. 새 검사기가 생기면 여기 한 줄 + 그 기준 yaml 에 `check:` 한 줄이다.

agent 라벨은 남는다 — 화면이 관점별로 묶어 보여주고, mode 기본값을 정한다.
"""
from __future__ import annotations

from collections.abc import Sequence

from modules.agent_format import (
    AbbrevChecker,
    CompletenessChecker,
    FieldPresenceChecker,
    FilenameChecker,
    FontSizeChecker,
    HeaderFooterChecker,
    PlaceholderChecker,
    RefListChecker,
    TextPatternChecker,
)
from modules.agent_quality import ChunkCriteriaChecker, WholeDocCriteriaChecker
from modules.preset import MODES
from modules.shared import Checker

#: `check:` 이름 → 검사기 팩토리. 팩토리는 기준의 `params` 와, 조립 계층이 문서를
#: 보고 마련해 준 칸 규격(field_specs)을 받는다 — 기준이 정하는 값(마커 목록·필수
#: 절 등)은 코드가 아니라 데이터에서 온다.
RULE_CHECKS: dict[str, object] = {
    # 미작성 표시. 마커는 params.placeholder_markers 가 정한다(기본 TBD).
    "placeholder": lambda params, specs: PlaceholderChecker(),
    # 필수 장절. 목록은 params.required_sections 가 정한다.
    "required_sections": lambda params, specs: CompletenessChecker(),
    # 표/결재란의 칸 값. 어느 칸이 이 기준 몫인지는 params.fields 가 고른다.
    "field_presence": lambda params, specs: FieldPresenceChecker(
        fields=_pick_fields(params, specs)),
    # 약어 목록 ↔ 본문 양방향 대조. 장절 제목·예외 토큰은 params 가 정한다.
    "abbrev": lambda params, specs: AbbrevChecker(
        sections=tuple(params.get("abbrev_sections") or ()),
        ignore=tuple(params.get("abbrev_ignore") or ())),
    # 참조문서 목록 ↔ 본문 인용 양방향. 절 제목이 다르면 params 가 덮는다.
    "reflist": lambda params, specs: RefListChecker(
        sections=tuple(params.get("ref_sections") or ())),
    # 머릿말·꼬리말에 있어야 할 것. 본문에는 안 실리므로(반복 텍스트라 뺀다)
    # 파서가 meta 로 옮긴 것을 본다(app/parser_bridge.py).
    "header_footer": lambda params, specs: HeaderFooterChecker(
        where=params.get("where", "header"),
        contains=tuple(params.get("contains") or ()),
        pattern=params.get("pattern", ""),
        message=params.get("message", ""),
        rule_id=str(params.get("_no", ""))),
    # 본문 표기 규칙(날짜 형식·단위 공백·금지 기호 등). 규칙값은 팀마다 다르므로
    # params 가 통째로 정한다 — 코드에는 "찾아서 맞춰본다"는 뼈대만 있다.
    # rule_id 를 넘기는 이유: 한 문서에 이 검사가 여럿 붙는데(표기 9건), 지적이
    # 어느 기준의 것인지 rule_id 로 갈라야 화면이 제 기준 아래에 붙인다.
    "text_pattern": lambda params, specs: TextPatternChecker(
        find=params.get("find", ""),
        must=params.get("must", ""),
        forbid=params.get("forbid", ""),
        message=params.get("message", ""),
        rule_id=str(params.get("_no", ""))),
    # 제출 파일명. 규칙(정규식)은 팀마다 달라 params 가 정한다.
    # 표 안에 **직접 박힌** 글꼴 크기. 문단 스타일이 정하는 크기는 아직 못 읽는다
    # (fontsize.py 머리말). 허용 크기는 산출물마다 달라 기준이 준다.
    "fontsize": lambda params, specs: FontSizeChecker(
        allowed=tuple(float(x) for x in (params.get("font_sizes") or ()))),
    "filename": lambda params, specs: FilenameChecker(
        pattern=params.get("filename_pattern", ""),
        example=params.get("filename_example", ""),
        forbidden=tuple(params.get("filename_forbidden") or ())),
}


#: `check:` 이름 → (그 검사가 읽는 기준값 이름, 사람이 읽을 이름).
#: 값이 없으면 그 검사는 돌 수 없다 — **검사기를 아예 만들지 않는다.** 만들어 두면
#: "검사할 것이 없어 못 했습니다" 한 장을 매 검토마다 낸다(실측: 공통 기준이 필수 절
#: 검사를 켜는데 목록은 팀이 주게 돼 있어, 목록을 안 준 일곱 팀의 모든 검토에 그 카드가
#: 떴다). 검사 못 한 사실은 카드가 아니라 **그 기준의 상태**(사람 확인 필요)가 진다.
RULE_NEEDS: dict[str, tuple[str, str]] = {
    "required_sections": ("required_sections", "필수 절 목록"),
}


def missing_value(criterion, review) -> str:
    """이 규칙 기준을 못 돌게 하는 빈 기준값의 이름. 돌 수 있으면 "".

    review 는 ReviewConfig 다 — 기준의 `params` 는 조립 계층이 이미 여기 얹었다
    (app/config.apply_criteria_params). 그래서 어느 층이 값을 적었든 여기서 보인다.
    """
    need = RULE_NEEDS.get(check_name(criterion))
    if not need:
        return ""
    attr, label = need
    return "" if getattr(review, attr, None) else label


def _pick_fields(params: dict, specs: Sequence) -> list:
    """이 기준이 가져가는 칸들.

    `params.fields` 가 **이름 목록**이면 조립 계층이 마련한 규격에서 골라 온다
    (팀 기준의 outputs 절이 실측으로 적어 둔 것이라, 기준은 이름만 대면 된다).
    딕셔너리 목록이면 기준이 직접 적은 규격이다. **안 적었으면 그 산출물의 칸을
    전부** 본다 — "필수 작성 항목이 비어 있지 않은가" 처럼 산출물마다 칸이 다른
    기준은 이름을 미리 못 적는다.

    나눠 갖게 하는 이유: 표지 항목과 개정기록 항목이 검사기 하나를 공유하면
    둘의 지적이 똑같아진다 — 이 리팩터링이 없애려던 바로 그 모습이다.

    # ponytail: fixed_text·signatures 는 아직 안 넘긴다(칸 값만). 그 둘까지
    # 기준별로 나누려면 outputs 절 전체를 모듈에 들여야 해서, 필요해지면 그때.
    # 폴더 검토(case.py)는 지금도 셋 다 본다.
    """
    wanted = params.get("fields") or []
    if not wanted:
        return list(specs)
    if all(isinstance(w, str) for w in wanted):
        by_name = {s.name: s for s in specs}
        return [by_name[w] for w in wanted if w in by_name]
    return _field_specs(wanted)


def _field_specs(rows: Sequence) -> list:
    """params.fields 의 딕셔너리들을 FieldSpec 으로. 모르는 키는 무시한다."""
    from modules.doc_parser import FieldSpec  # noqa: PLC0415

    allowed = {f.name for f in FieldSpec.__dataclass_fields__.values()}
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        kw = {k: (tuple(v) if isinstance(v, list) else v)
              for k, v in row.items() if k in allowed}
        if kw.get("name"):
            out.append(FieldSpec(**kw))
    return out


# agent 라벨 → 기본 mode. 라벨과 처리 방식은 다른 축이지만 대부분 이 대응이 맞는다.
# 안 맞는 기준만 데이터(yaml)에서 mode 를 적어 덮는다.
AGENT_MODES: dict[str, str] = {
    "형식·완전성": "규칙",
    "표현·내용품질": "LLM-조각",
    "정합성·추적성": "LLM-문서",
    "표준·체크리스트": "LLM-조각",
    "문서작성·생성": "사람",   # 지적이 아니라 산출물을 만드는 계열
    "검토의견·이력": "사람",   # 검사가 아니라 이력 관리
}


def check_name(criterion) -> str:
    """이 기준을 검사하는 규칙 이름. 없거나 모르는 이름이면 "".

    모르는 이름을 조용히 넘기면 오타 하나가 기준을 검사되지 않은 채 통과시킨다.
    """
    name = (getattr(criterion, "check", "") or "").strip()
    return name if name in RULE_CHECKS else ""


def checker_key(criterion) -> str:
    """이 기준이 쓸 검사기의 열쇠. 매개변수가 있으면 기준마다 따로 만든다.

    매개변수 없는 검사(미작성 표시 등)는 여러 기준이 같은 것을 대도 한 벌이면
    된다. 반면 칸 값 검사는 기준마다 보는 칸이 다르므로 따로 만들어야 한다 —
    한 벌을 나눠 가지면 표지 항목과 개정기록 항목의 지적이 똑같아진다.
    """
    name = check_name(criterion)
    if not name:
        return ""
    params = getattr(criterion, "params", None) or {}
    return f"{name}#{criterion.no}" if params else name


def rule_checkers(criteria: Sequence, field_specs: Sequence = ()) -> dict[str, Checker]:
    """규칙 기준 → {열쇠: 검사기}. 같은 열쇠는 한 번만 만든다.

    field_specs 는 조립 계층이 문서를 보고 마련한 칸 규격이다(팀 기준의 outputs
    절). 기준은 `params.fields` 에 이름만 적어 자기 몫을 고른다.
    """
    out: dict[str, Checker] = {}
    for c in criteria:
        if mode_for(c) != "규칙":
            continue
        key = checker_key(c)
        if not key or key in out:
            continue
        name = check_name(c)
        out[key] = RULE_CHECKS[name](getattr(c, "params", None) or {}, field_specs)
    return out


def llm_checkers_for(criteria: Sequence,
                     doc_max_chars: int = 120_000) -> dict[str, Checker]:
    """LLM 기준 → {mode: 검사기}.

    조각 기준은 **하나의** ChunkCriteriaChecker 에 모아 넣는다 — 기준마다 검사기를
    만들면 같은 청크를 기준 수만큼 다시 읽는다.

    LLM-문서 기준은 하나의 WholeDocCriteriaChecker 에 모아 문서를 통째로 묻는다 — 멀리
    떨어진 두 곳을 맞대야 하는 기준은 조각으로는 원리상 못 잡는다. 문서가 창을
    넘으면 그 검사기가 조각으로 내려가고 그 사실을 밝힌다.
    """
    slice_criteria = [c for c in criteria if mode_for(c) == "LLM-조각"]
    doc_criteria = [c for c in criteria if mode_for(c) == "LLM-문서"]
    out: dict[str, Checker] = {}
    if slice_criteria:
        out["LLM-조각"] = ChunkCriteriaChecker(criteria=slice_criteria)
    if doc_criteria:
        out["LLM-문서"] = WholeDocCriteriaChecker(criteria=doc_criteria,
                                                  max_chars=doc_max_chars)
    return out


def checkers_for(criteria: Sequence, doc_max_chars: int = 120_000,
                 field_specs: Sequence = ()) -> list[Checker]:
    """기준 목록 → 검사기 목록. mode 가 정한다.

    사람 mode 는 검사기를 내지 않는다. 조립 계층이 manual 로 둔다. 어느 검사기가
    어느 기준의 것인지 알아야 하는 호출부는 이걸 쓰지 말고 위의 두 함수를 직접
    부른다 — 여기서 만든 것을 다시 만들면 지적을 낸 객체와 짝이 어긋난다.
    """
    return [*rule_checkers(criteria, field_specs).values(),
            *llm_checkers_for(criteria, doc_max_chars).values()]


# 이 문서를 검사하는 기준이 **아닌** 계열. 지적을 낼 대상이 애초에 아니다.
#   문서작성·생성 — 수식 도출 · 시험환경 이미지 · 용어 설명 · 표 그리기 · 코드 수정.
#                   만들어 주는 기능이지 이 문서를 보는 검사가 아니다.
#   검토의견·이력  — 의견 등록 · 해결/미해결 갱신 · 이력 통계. 검사가 아니라 관리다.
#
# "사람이 확인" 과 갈라야 한다. 사람 확인은 **이 문서를 사람이 봐야 한다**는 뜻이고
# 이쪽은 **이 문서를 볼 항목이 아니다**는 뜻이다. 뭉치면 검토자가 "사람 확인 19건"
# 을 보고 그중 6건이 자기 일이 아닌 줄 모른 채 문서를 뒤진다(실측: AI시험인증1팀
# 기준 13개 중 6개가 문서작성·생성이었다).
_OUT_OF_SCOPE_AGENTS = frozenset({"문서작성·생성", "검토의견·이력"})


def out_of_scope(criterion) -> bool:
    """이 기준이 문서 검토 항목 자체가 아닌가.

    기준이 mode·check 를 **명시했으면** 그쪽이 이긴다 — 이 판정은 호출부에서
    규칙·LLM 갈래를 다 거친 뒤 마지막에만 쓴다(orchestrator 참고).
    """
    return (getattr(criterion, "agent", "") or "") in _OUT_OF_SCOPE_AGENTS


def mode_for(criterion) -> str:
    """기준을 어떻게 검사할지. 못 정하면 '사람'(manual).

    데이터에 적힌 mode 가 라벨 기본값을 덮는다. 다만 어휘에 없는 값은 오타이므로
    '사람'으로 떨어뜨린다 — 조용히 통과시키면 검사되지 않은 기준이 검사된 것처럼
    보이고, 그건 이 도구가 낼 수 있는 최악의 거짓말이다.
    """
    declared = (getattr(criterion, "mode", "") or "").strip()
    if declared:
        return declared if declared in MODES else "사람"
    agent = getattr(criterion, "agent", "") or ""
    return AGENT_MODES.get(agent, "사람")
