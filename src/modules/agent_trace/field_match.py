"""산출물 간 필드 대조.

`Checker` 가 아니라 순수 함수다. 대조는 "문서 하나를 검사"가 아니고 **추출된 필드
값(dict) 두 개**만 있으면 판정된다 — 문서를 안 받으니 테스트가 dict 두 개로 끝나고,
파싱이 바뀌어도 이 판정은 흔들리지 않는다. `build_rtm` 도 같은 이유로 함수다.

이 층이 단일 문서 형식 검사보다 신뢰도가 높다. 기준이 "**서로 같아야 한다**"라서
규정 해석 여지가 없다 — "특정 형식이어야 한다"는 규정 원문 해석이 갈린다(실측:
버전 `X.Y` 규칙이 6개 문서를 전부 지적했다. 그러면 문서가 아니라 규칙을 의심해야 한다).
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from itertools import pairwise

from modules.doc_parser import FieldValue
from modules.shared import Anchor, Evidence, Finding, Severity


def _evidence_quote(value: FieldValue) -> str:
    """PDF 위치용 문맥은 실제 연속 원문만 쓴다."""
    return value.source_quote or value.value or ""


@dataclass(frozen=True)
class PairRow:
    """대조표 한 줄. 어느 필드를 어떤 규칙으로 맞대볼 것인가."""
    field: str
    rule: str = "exact"
    # 양쪽 필드 이름이 다를 때만. md §1-1 "요구 사항 ↔ 시험합격기준" 같은 경우다.
    right_field: str = ""


@dataclass(frozen=True)
class PairRule:
    """문서쌍 하나. md 의 §1-1 ~ §1-18 에 해당한다."""
    id: str
    left: str
    right: str
    rows: tuple[PairRow, ...] = ()


def _unreviewed(pair: PairRule, row: PairRow, reason: str) -> Finding:
    """판정을 못 했다는 보고. 지적 0건과 구분해야 한다.

    못 찾은 것을 "다르다"로 판정하면 거짓 지적이 되고, 조용히 넘기면 검사하지 않은
    것이 "이상 없음"으로 보인다. 둘 다 거짓이다.
    """
    return Finding(
        checker="field_match", severity=Severity.INFO,
        message=f"{pair.left} ↔ {pair.right} '{row.field}' 대조를 하지 못했습니다 — {reason}",
        anchor=Anchor(None, None),
        document=f"{pair.left} ↔ {pair.right}",
        rule_id=f"{pair.id}/{row.field}", unreviewed=True)


def compare_pair(left: dict[str, FieldValue], right: dict[str, FieldValue],
                 pair: PairRule) -> list[Finding]:
    """문서쌍 하나를 대조한다. 일치하면 지적이 없다.

    left·right 는 `doc_parser.extract_fields` 가 낸 것이다.
    """
    findings: list[Finding] = []
    for row in pair.rows:
        lv = left.get(row.field)
        rv = right.get(row.right_field or row.field)

        missing = [name for name, v in ((pair.left, lv), (pair.right, rv))
                   if v is None or not v.found]
        if missing:
            findings.append(_unreviewed(
                pair, row, f"{' · '.join(missing)} 에서 값을 찾지 못했습니다"))
            continue

        if lv.value == rv.value:
            continue

        findings.append(Finding(
            checker="field_match", severity=Severity.MAJOR,
            message=(f"'{row.field}' 가 다릅니다 — "
                     f"{pair.left} {lv.value!r} ↔ {pair.right} {rv.value!r}"),
            # 첫 근거의 위치를 anchor 에 둔다. 기존 리포트·UI 는 anchor 만 읽으므로
            # 그대로 동작하고, 근거 둘은 evidence 로 따라간다.
            anchor=lv.anchor,
            document=f"{pair.left} ↔ {pair.right}",
            rule_id=f"{pair.id}/{row.field}",
            evidence=[Evidence(anchor=lv.anchor, quote=_evidence_quote(lv)),
                      Evidence(anchor=rv.anchor, quote=_evidence_quote(rv))]))
    return findings


# 문서 간 md §1-5 가 "갑지는 버전 포함 전체, 을지는 버전 제외" 라고 쓴다. 같은
# 제품명을 두 모양으로 적으므로 대조할 때만 버전을 떼어낸다 — 표시는 원문 그대로다.
_DATE_KEY = re.compile(r"^(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?$")
_VERSION = re.compile(r"\(\s*Ver[^)]*\)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class CaseWideRule:
    """한 값이 여러 산출물에서 같아야 한다는 규칙 (문서 간 md §3).

    outputs 가 "all" 이면 케이스에 정의된 전 산출물이다(의뢰번호가 그렇다).
    """
    id: str
    field: str
    outputs: tuple[str, ...] | str = ()
    # exact      : 값이 전부 같아야 한다 (의뢰번호·제품명 등)
    # nondecreasing: outputs 에 적힌 **순서대로** 값이 커져야 한다. 작성일자
    #                선후 관계(의뢰서 → 계획서 → 설계서 → 시험 수행)가 그것이다.
    #                같은 날 작성은 정상이라 "커지거나 같다" 로 본다.
    rule: str = "exact"
    ignoring: str = ""          # "version" 이면 대조에서 버전을 뗀다


@dataclass(frozen=True)
class CaseWideCell:
    """매트릭스 한 칸. 맞은 곳도 남긴다 — 검토자는 "6곳 중 1곳이 틀렸다"를 알아야 한다."""
    output: str
    value: str | None
    present: bool               # 그 산출물이 케이스에 올라왔나
    configured: bool            # 그 산출물에 이 필드의 추출 규칙이 있나
    found: bool                 # 올라왔다면 그 필드를 찾았나
    matched_label: str = ""     # 실제 표에서 맞춘 라벨. PDF의 정확한 셀을 찾는 문맥
    source_quote: str = ""       # 값을 읽은 실제 표 행. 근거는 원문을 지어내면 안 된다.
    anchor: Anchor = Anchor(None, None)
    # 이 칸이 다수 값과 같은가. None 이면 못 봤다.
    # 어느 칸이 틀렸는지는 여기서 정한다 — 버전 무시 같은 정규화가 여기 있고,
    # 화면이 다시 계산하면 두 곳의 판정이 어긋난다.
    ok: bool | None = None


def _cell_evidence_quote(cell: CaseWideCell) -> str:
    return cell.source_quote or cell.value or ""


@dataclass
class CaseWideResult:
    id: str
    field: str
    status: str                 # 일치 | 불일치 | 미검토
    cells: list[CaseWideCell] = field(default_factory=list)
    finding: Finding | None = None


def _compare_key(value: str | None, ignoring: str) -> str:
    if value is None:
        return ""
    return _VERSION.sub("", value).strip() if ignoring == "version" else value


def _sort_key(value: str | None) -> str:
    """대소 비교용 열쇠. `2026. 01. 03.` → `20260103`.

    날짜만 다룬다. 이 규칙을 쓰는 항목이 지금 작성일자뿐이고, 어휘를 미리 넓히면
    비교 못 할 값을 비교한 것처럼 보인다 — 형식이 안 맞으면 못 본 것으로 둔다.
    """
    m = _DATE_KEY.match((value or "").strip())
    return f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}" if m else ""


def _nondecreasing(rule: CaseWideRule, cells, seen, gaps, wanted) -> CaseWideResult:
    """outputs 순서대로 값이 커지는가. 순서가 뒤집힌 곳을 짚는다.

    **어긋난 쌍만 지적한다.** 전부 나열하면 어디가 문제인지 안 보인다.
    """
    keyed = [(c, _sort_key(c.value)) for c in seen]
    unreadable = [c.output for c, k in keyed if not k]
    ordered = [(c, k) for c, k in keyed if k]

    bad = [(a, b) for (a, ka), (b, kb) in pairwise(ordered) if ka > kb]
    if bad:
        pairs = " · ".join(f"{a.output} {a.value!r} → {b.output} {b.value!r}"
                           for a, b in bad)
        return CaseWideResult(
            id=rule.id, field=rule.field, status="불일치",
            # 짚는 것은 쌍의 **뒤** 문서다. 의뢰서(1/10) → 계획서(1/05) 라면
            # 날짜가 틀린 쪽은 계획서다 — 앞을 짚으면 검토자가 멀쩡한 의뢰서를
            # 고치고 진짜 역전은 다음 검토에도 그대로 남는다.
            cells=[replace(c, ok=not any(c is b for _, b in bad)) if c.found else c
                   for c in cells],
            finding=Finding(
                checker="case_wide", severity=Severity.MAJOR,
                message=f"'{rule.field}' 의 선후가 뒤집혔습니다 — {pairs}",
                anchor=bad[0][1].anchor,
                document=" · ".join(c.output for c, _ in ordered),
                rule_id=rule.id,
                evidence=[Evidence(anchor=c.anchor, quote=_cell_evidence_quote(c))
                          for c, _ in ordered]))

    missing = gaps + unreadable
    if missing:
        return CaseWideResult(
            id=rule.id, field=rule.field, status="미검토",
            cells=[replace(c, ok=True) if c.found else c for c in cells],
            finding=Finding(
                checker="case_wide", severity=Severity.INFO,
                message=(f"'{rule.field}' 를 {', '.join(missing)} 에서 읽지 못해 "
                         f"선후 관계를 마저 보지 못했습니다"),
                anchor=Anchor(None, None), document=" · ".join(wanted),
                rule_id=rule.id, unreviewed=True))

    return CaseWideResult(id=rule.id, field=rule.field, status="일치",
                          cells=[replace(c, ok=True) if c.found else c for c in cells])


def compare_case_wide(values_by_output: dict[str, dict[str, FieldValue]],
                      rule: CaseWideRule,
                      all_outputs: Sequence[str] = (),
                      configured_fields: dict[str, set[str]] | None = None,
                      ) -> CaseWideResult:
    """한 필드를 여러 산출물에 걸쳐 대조한다.

    **지적은 1건이고 근거가 N개다.** 쌍마다 대조하면 의뢰번호 하나가 틀렸을 때 같은
    지적이 12번 난다(18쌍 중 12쌍에 등장한다).

    못 본 곳이 있으면 미검토다. 다만 **이미 어긋난 것이 있으면 불일치가 이긴다** —
    미검토가 불일치를 덮으면 틀린 것이 안 보인다.
    """
    wanted = (tuple(all_outputs) if rule.outputs == "all"
              else tuple(rule.outputs))
    cells: list[CaseWideCell] = []
    for key in wanted:
        vals = values_by_output.get(key)
        if vals is None:
            cells.append(CaseWideCell(output=key, value=None, present=False,
                                      configured=False, found=False))
            continue
        fv = vals.get(rule.field)
        if fv is None:
            configured = (rule.field in configured_fields.get(key, set())
                          if configured_fields is not None else False)
            cells.append(CaseWideCell(output=key, value=None, present=True,
                                      configured=configured, found=False))
            continue
        if not fv.found:
            cells.append(CaseWideCell(output=key, value=None, present=True,
                                      configured=True, found=False,
                                      anchor=fv.anchor))
            continue
        cells.append(CaseWideCell(output=key, value=fv.value, present=True,
                                  configured=True, found=True,
                                  matched_label=fv.matched_label,
                                  source_quote=fv.source_quote,
                                  anchor=fv.anchor))

    seen = [c for c in cells if c.found]
    gaps = [c.output for c in cells if not c.found]

    if rule.rule == "nondecreasing":
        return _nondecreasing(rule, cells, seen, gaps, wanted)

    distinct = {_compare_key(c.value, rule.ignoring) for c in seen}

    # 어느 칸이 틀렸나 — 유일한 다수 값이 있으면 그것과 다른 칸이다.
    # 값이 반반으로 갈리면 어느 쪽이 맞는지 정할 근거가 없다. 예전에는 문서 순서상
    # 먼저 나온 값을 임시 기준으로 삼아 기록서↔갑지 1:1 충돌에서 갑지만 빨갛게
    # 표시했다. 순서는 정답의 근거가 아니므로 동률이면 충돌한 값을 모두 표시한다.
    if seen:
        keys = [_compare_key(c.value, rule.ignoring) for c in seen]
        counts = {key: keys.count(key) for key in dict.fromkeys(keys)}
        top = max(counts.values())
        leaders = [key for key, count in counts.items() if count == top]
        marked = {
            c.output: (len(leaders) == 1
                       and _compare_key(c.value, rule.ignoring) == leaders[0])
            for c in seen
        }
        cells = [replace(c, ok=marked.get(c.output) if c.found else None) for c in cells]
        seen = [c for c in cells if c.found]

    if len(distinct) > 1:
        pairs = " · ".join(f"{c.output} {c.value!r}" for c in seen)
        note = f" (못 본 곳: {', '.join(gaps)})" if gaps else ""
        return CaseWideResult(
            id=rule.id, field=rule.field, status="불일치", cells=cells,
            finding=Finding(
                checker="case_wide", severity=Severity.MAJOR,
                message=f"'{rule.field}' 가 산출물마다 다릅니다 — {pairs}{note}",
                anchor=seen[0].anchor, document=" · ".join(c.output for c in seen),
                rule_id=rule.id,
                evidence=[Evidence(anchor=c.anchor, quote=_cell_evidence_quote(c))
                          for c in seen]))

    if gaps:
        return CaseWideResult(
            id=rule.id, field=rule.field, status="미검토", cells=cells,
            finding=Finding(
                checker="case_wide", severity=Severity.INFO,
                message=(f"'{rule.field}' 를 {', '.join(gaps)} 에서 확인하지 못해 "
                         f"{len(wanted)}곳 대조를 마치지 못했습니다"),
                anchor=Anchor(None, None), document=" · ".join(wanted),
                rule_id=rule.id, unreviewed=True))

    return CaseWideResult(id=rule.id, field=rule.field, status="일치", cells=cells)
