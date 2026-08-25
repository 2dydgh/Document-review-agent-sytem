"""케이스 검토 — 산출물 세트를 한 번에.

검사 1건이 문서 하나가 아니라 **산출물 세트**다. 팀 워크플로우가 폴더 세트이고
(SST-26-999 하나에 문서 10종), 산출물 간 대조는 문서가 여럿 모여야 판정된다.

업로드 1회 = 검사 1회 = 리포트 1개다. 서버에 상태를 남기지 않으므로 DB·문서 저장소
(미정 영역)를 건드리지 않는다.

orchestrator.py 에 넣지 않고 파일을 나눴다 — 거기는 이미 289줄에 진입점이 셋이다.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from modules.agent_format import FieldPresenceChecker, FontSizeChecker, SignatureSpec
from modules.agent_trace import (
    CaseWideResult,
    CaseWideRule,
    PairRow,
    PairRule,
    compare_case_wide,
    compare_pair,
)
from modules.doc_parser import (
    FieldSpec,
    FieldValue,
    UnsupportedFormatError,
    extract_fields,
    load_document,
    normalize,
)
from modules.preset import Classification, classify_output
from modules.report import stamp
from modules.shared import Anchor, Finding, Severity


@dataclass
class OutputResult:
    """산출물 하나의 결과."""
    key: str
    source_path: str
    classification: Classification
    field_specs: list[FieldSpec] = field(default_factory=list)
    values: dict[str, FieldValue] = field(default_factory=dict)
    # 이 산출물 하나만 보고 낸 지적(칸 값 검사). 문서 간 대조와 층이 다르다 —
    # 여기 달아 두어야 리포트가 산출물별로 펼 수 있다.
    findings: list[Finding] = field(default_factory=list)
    # reason 이 왜인지 말한다 — "지적 0건"으로 두면 검사하지 않은 것이
    # 이상 없음으로 보인다.
    status: str = "unreviewed"
    reason: str = ""
    error: str = ""


@dataclass
class CaseReviewResult:
    case_id: str = ""
    outputs: list[OutputResult] = field(default_factory=list)
    missing_outputs: list[str] = field(default_factory=list)
    # 한 값이 여러 산출물에서 같은가 (문서 간 md §3). 리포트의 필드 × 산출물
    # 매트릭스가 이걸 그린다 — 맞은 곳까지 남아 있어야 "6곳 중 1곳이 틀렸다"를
    # 보여줄 수 있다.
    case_wide: list[CaseWideResult] = field(default_factory=list)
    unclassified: list[str] = field(default_factory=list)
    # 왜 건너뛰었는지까지 남긴다. 파일명만 남기면 리포트가 "건너뜀"이라고만
    # 말하고 이유를 못 댄다 — 조용히 버린 것과 구분이 흐려진다.
    ignored: list[dict] = field(default_factory=list)
    # 문서 대조로 판정할 수 없는 것(문서 간 md §4). 접수번호·접수일·사업자등록증은
    # 문서 밖 원천과 맞춰야 해서, 도구는 목록만 내고 사람이 확인했다고 남긴다.
    manual: list[dict] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


def _field_specs(output_spec: dict) -> list[FieldSpec]:
    """기준 파일의 fields 절 → FieldSpec.

    변환이 app 에 있는 이유: 기준을 읽는 것은 preset 의 일이고 문서에서 값을 꺼내는
    것은 doc_parser 의 일인데, 둘을 잇는 것은 조립이다. preset 이 doc_parser 를
    import 하면 모듈 둘이 묶인다.
    """
    return [FieldSpec(name=f["name"], source=f.get("from", "table"),
                      labels=tuple(f.get("labels", ())), at=f.get("at", "right"),
                      options=tuple(f.get("options", ())),
                      select=f.get("select", ""), pattern=f.get("pattern", ""),
                      format=f.get("format", ""), equals=f.get("equals", ""),
                      required=bool(f.get("required", False)),
                      columns=tuple(f.get("columns", ())),
                      key=f.get("key", ""),
                      required_columns=tuple(f.get("required_columns", ())),
                      capture=f.get("capture", ""))
            for f in output_spec.get("fields", [])]


def _presence_checker(output_spec: dict, specs: list[FieldSpec],
                      key: str) -> FieldPresenceChecker:
    """기준 파일의 fields·fixed_text·signatures 절 → 칸 값 검사기.

    document 에 산출물 이름을 실어 어느 문서의 지적인지 남긴다 — 산출물 세트 검토는
    문서 열몇 개를 한꺼번에 보므로 이게 없으면 지적이 어디서 났는지 알 수 없다.
    """
    return FieldPresenceChecker(
        fields=specs,
        fixed_text=list(output_spec.get("fixed_text", [])),
        signatures=[SignatureSpec(role=s["role"], placeholder=s["placeholder"],
                                  at=s.get("at", "right"))
                    for s in output_spec.get("signatures", [])],
        document=key)


def _ignore_rule(path: Path, rules: Sequence[dict]) -> dict | None:
    """이 파일을 건너뛰게 만든 규칙. 없으면 None."""
    return next((r for r in rules
                 if r.get("pattern") and re.search(r["pattern"], path.name)), None)


def _case_id(outputs: Sequence[OutputResult]) -> str:
    """케이스 번호. 산출물들이 말하는 의뢰번호 중 가장 흔한 것.

    전부 같아야 하지만(문서 간 §3 "의뢰번호 전 문서 일치"), 다르면 그것 자체가
    지적거리다 — 여기서는 이름만 정하고 판정은 case_wide 가 한다.
    """
    seen = Counter(v.value for o in outputs
                   for name, v in o.values.items()
                   if name == "의뢰번호" and v.found and v.value)
    return seen.most_common(1)[0][0] if seen else ""


def review_case(paths: Sequence[str | Path], spec: dict,
                on_progress: Callable[[dict], None] | None = None
                ) -> CaseReviewResult:
    """산출물 세트를 검토한다.

    spec 은 팀 기준 파일(presets/criteria/teams/*.yaml)을 읽은 dict 다.
    """
    emit = on_progress or (lambda ev: None)
    result = CaseReviewResult()
    output_specs = {o["key"]: o for o in spec.get("outputs", [])}
    ignore_rules = spec.get("ignore", [])

    # 1. 판별. 양식번호가 없으면 추측하지 않는다 — 엉뚱한 필드맵으로 검사하면
    #    거짓 지적이 난다. 사람이 지정하거나 제외해야 한다.
    picked: dict[str, tuple[Path, Classification]] = {}
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            continue
        skip = _ignore_rule(path, ignore_rules)
        if skip is not None:
            result.ignored.append({"path": str(path),
                                   "reason": skip.get("reason", "")})
            continue
        found = classify_output(path.name, list(output_specs.values()))
        if found.output_key is None:
            result.unclassified.append(str(path))
        else:
            picked[found.output_key] = (path, found)
    emit({"key": "classify", "status": "done",
          "detail": f"산출물 {len(picked)}종 인식"})

    result.missing_outputs = [k for k in output_specs if k not in picked]

    # 2. 문서별 — 값을 꺼낸다. 하나가 터져도 나머지는 간다.
    for key, (path, found) in picked.items():
        out = OutputResult(key=key, source_path=str(path), classification=found,
                           field_specs=_field_specs(output_specs[key]))
        try:
            doc = normalize(load_document(path))
        except (UnsupportedFormatError, NotImplementedError, ValueError) as exc:
            out.error = str(exc)
            out.reason = f"문서를 읽지 못했습니다 — {exc}"
            result.outputs.append(out)
            continue
        spec_for_key = output_specs[key]
        has_form = bool(out.field_specs or spec_for_key.get("fixed_text")
                        or spec_for_key.get("signatures"))
        if has_form:
            out.values = extract_fields(doc, out.field_specs)
            # 2b. 칸 값 판정. 뽑기만 하고 판정하지 않으면 프리셋의
            #     required·pattern·format 이 아무 일도 하지 않는다.
            _ck = _presence_checker(spec_for_key, out.field_specs, key)
            out.findings = stamp(_ck, _ck.check(doc))
            result.findings.extend(out.findings)
            out.status = "reviewed"
            flagged = sum(1 for f in out.findings if not f.unreviewed)
            missing = [n for n, v in out.values.items() if not v.found]
            out.reason = (f"필드 {len(out.values) - len(missing)}/{len(out.values)}개 "
                          f"추출 · 지적 {flagged}건")
            if missing:
                out.reason += f" (못 찾음: {', '.join(missing)})"
        else:
            out.reason = "이 산출물의 필드맵이 아직 없습니다"
        result.outputs.append(out)
        emit({"key": "output", "status": "done", "detail": key})

    result.manual = [dict(m) for m in spec.get("manual", [])]
    result.case_id = _case_id(result.outputs)
    values = {o.key: o.values for o in result.outputs}

    # 3. 전 산출물 대조(문서 간 md §3). 쌍보다 먼저 본다 — 의뢰번호처럼 여러
    #    곳에 걸친 값은 여기서 한 번만 판정해야 지적이 쌍 수만큼 부풀지 않는다.
    all_keys = list(output_specs)
    configured_fields = {
        o.key: {field.name for field in o.field_specs}
        for o in result.outputs
    }
    for cw_spec in spec.get("case_wide", []):
        rule = CaseWideRule(
            id=str(cw_spec["id"]), field=cw_spec["field"],
            outputs=(cw_spec.get("outputs") if cw_spec.get("outputs") == "all"
                     else tuple(cw_spec.get("outputs", ()))),
            rule=cw_spec.get("rule", "exact"), ignoring=cw_spec.get("ignoring", ""))
        got = compare_case_wide(
            values, rule, all_outputs=all_keys,
            configured_fields=configured_fields)
        result.case_wide.append(got)
        if got.finding is not None:
            result.findings.extend(stamp("전체 대조", [got.finding]))
        emit({"key": "case_wide", "status": "done", "detail": rule.id})

    # 4. 산출물 간 대조. 양쪽이 다 올라온 쌍만 판정하고, 없으면 이유를 남긴다.
    for pair_spec in spec.get("pairs", []):
        pair = PairRule(
            id=str(pair_spec["id"]), left=pair_spec["left"], right=pair_spec["right"],
            rows=tuple(PairRow(field=r["field"], rule=r.get("rule", "exact"),
                               right_field=r.get("right_field", ""))
                       for r in pair_spec.get("rows", [])))
        missing = [n for n in (pair.left, pair.right) if n not in values]
        if missing:
            result.findings.extend(stamp(
                "산출물 간 대조",
                _pair_unavailable(pair, f"{' · '.join(missing)} 가 올라오지 않았습니다")))
            continue
        result.findings.extend(stamp(
            "산출물 간 대조",
            compare_pair(values[pair.left], values[pair.right], pair)))
        emit({"key": "pair", "status": "done", "detail": pair.id})

    return result


def _pair_unavailable(pair: PairRule, reason: str) -> list[Finding]:
    """문서가 없어 판정 못 한 쌍. 조용히 건너뛰면 통과로 읽힌다."""
    return [Finding(
        checker="field_match", severity=Severity.INFO,
        message=f"{pair.left} ↔ {pair.right} '{row.field}' 대조를 하지 못했습니다 — {reason}",
        anchor=Anchor(None, None), document=f"{pair.left} ↔ {pair.right}",
        rule_id=f"{pair.id}/{row.field}", unreviewed=True)
        for row in pair.rows]


# Finding.checker → 화면이 쓰는 층 이름. FieldPresenceChecker 의 checker 는
# PlaceholderChecker 와 같은 "completeness" 다(형식·완전성 묶음).
_KIND = {"completeness": "output", "case_wide": "case_wide"}


def to_ui_case_payload(result: CaseReviewResult, team_name: str = "") -> dict:
    """화면이 그대로 대입할 수 있는 dict.

    report/ui_export.py 가 아니라 여기 있는 이유: CaseReviewResult 는 조립 타입이라
    모듈이 알면 안 된다(모듈은 DocSuree 를 몰라야 한다). 기존 to_ui_* 들이 원시값만
    받는 것도 같은 이유다.

    **evidence 를 그대로 싣는다.** 기존 compare payload 는 anchor 하나만 남기고
    버리는데, 대조 지적에서 가장 값어치 있는 정보가 "여기와 저기"다.
    """
    findings = [{
        "id": f"c{i + 1}",
        "ruleId": f.rule_id,
        # 어느 층이 낸 지적인가. 전 산출물 대조(case_wide)는 매트릭스가 이미
        # 보여주므로 리포트·CSV 가 같은 것을 두 번 세지 않게 가른다.
        #   output    문서 하나만 보고 낸 것 (칸 값 검사)
        #   case_wide 한 값이 N곳에서 같은가
        #   pair      산출물 두 개 대조
        "kind": _KIND.get(f.checker, "pair"),
        "label": f.label,
        "sev": f.severity.value,
        "message": f.message,
        "document": f.document or "",
        "unreviewed": f.unreviewed,
        "evidence": [{"at": e.anchor.section or "", "page": e.anchor.page,
                      "quote": e.quote}
                     for e in f.evidence],
    } for i, f in enumerate(result.findings)]

    outputs = [{
        "key": o.key,
        "file": Path(o.source_path).name,
        "formNo": {"found": o.classification.form_no_found,
                   "expected": o.classification.form_no_expected,
                   "stale": o.classification.revision_stale},
        "status": o.status,
        "reason": o.reason,
        "error": o.error,
        # 이 산출물 하나만 보고 낸 지적. 둘을 갈라 싣는다 — 합치면 "검사 못 한
        # 칸"이 "결함"으로 보인다.
        "findings": sum(1 for f in o.findings if not f.unreviewed),
        "unreviewed": sum(1 for f in o.findings if f.unreviewed),
        "fields": [{"name": v.name,
                    "value": v.value,
                    "found": v.found,
                    "at": v.anchor.section or "",
                    "page": v.anchor.page,
                    "label": v.matched_label,
                    "sourceQuote": v.source_quote,
                    "selected": list(v.selected)}
                   for v in o.values.values()],
    } for o in sorted(result.outputs, key=lambda x: x.key)]

    # 필드 × 산출물 매트릭스. 팀이 xlsx No.13 에서 "비교용 엑셀" 이라고 부른 것이다.
    # 지적 목록만으로는 **맞은 곳이 안 보인다** — 검토자는 "6곳 다 봤고 1곳이
    # 틀렸다"를 알아야지 "1곳이 틀렸다"만 알면 안 된다.
    matrix = [{
        "id": cw.id,
        "field": cw.field,
        "status": cw.status,
        "seen": sum(1 for c in cw.cells if c.found),
        "total": len(cw.cells),
        "cells": [{"output": c.output, "value": c.value,
                   "present": c.present, "configured": c.configured,
                   "found": c.found, "ok": c.ok,
                   "label": c.matched_label,
                   "at": c.anchor.section or ""} for c in cw.cells],
    } for cw in result.case_wide]

    flagged = [f for f in findings if not f["unreviewed"]]
    return {
        "caseId": result.case_id,
        "team": team_name,
        "stats": {
            "outputs": len(result.outputs),
            "missing": len(result.missing_outputs),
            "findings": len(flagged),
            "unreviewed": len(findings) - len(flagged),
            "unclassified": len(result.unclassified),
            "ignored": len(result.ignored),
            # §3 8항목 중 몇 개를 실제로 판정했나. "발급해도 되는가"의 근거다.
            "wideChecked": sum(1 for m in matrix if m["status"] != "미검토"),
            "wideTotal": len(matrix),
            "manual": len(result.manual),
        },
        "outputs": outputs,
        "matrix": matrix,
        "missing": list(result.missing_outputs),
        "manual": result.manual,
        "unclassified": [{"file": Path(p).name} for p in result.unclassified],
        "ignored": [{"file": Path(i["path"]).name, "reason": i.get("reason", "")}
                    for i in result.ignored],
        "findings": findings,
    }


def _fields_by_name(outputs: Sequence[dict], wide: Sequence[dict],
                    pairs: Sequence[dict], shape: Callable[[dict], dict]
                    ) -> list[dict]:
    """필드 이름으로 묶는다. {이름: 어느 산출물에서 어떻게 뽑나 + 어느 대조에 쓰나}.

    대조 기준은 있는데 어느 문서에서도 못 뽑는 필드(시험항목명)도 낸다 —
    빠뜨리면 리포트의 "0/4 미검토"를 눌러도 갈 곳이 없다.
    """
    order: list[str] = []
    where: dict[str, list[dict]] = {}
    for o in outputs:
        for f in o.get("fields", []):
            name = f["name"]
            if name not in where:
                where[name] = []
                order.append(name)
            where[name].append({"output": o["key"], **shape(f)})

    in_wide = {c["field"]: c["id"] for c in wide}
    in_pairs: dict[str, list[str]] = {}
    for p in pairs:
        for r in p["rows"]:
            in_pairs.setdefault(r["field"], []).append(p["id"])

    # 뽑을 곳이 없는데 대조에만 있는 필드를 뒤에 붙인다.
    for name in list(in_wide) + list(in_pairs):
        if name not in where:
            where[name] = []
            order.append(name)

    return [{"name": n, "where": where[n],
             "caseWide": in_wide.get(n, ""), "pairs": in_pairs.get(n, [])}
            for n in order]


def to_ui_criteria_payload(spec: dict) -> dict:
    """팀 기준 파일 → 화면이 그대로 그릴 dict.

    **판정에 쓰인 그대로 내려준다.** 화면이 다시 계산하거나 요약하면 실제로 도는
    규칙과 화면이 갈린다 — 검토자가 "왜 이게 지적이지?"를 물었을 때 답이 되려면
    라벨·형식·필수 여부가 있는 그대로여야 한다.

    items(팀이 준 원문 요구사항)는 개수만 낸다. 80항목 전문은 여기서 쓸 일이
    아니고, 화면이 무거워진다.
    """
    outputs = spec.get("outputs", [])
    all_keys = [o["key"] for o in outputs]

    def field(f: dict) -> dict:
        return {
            "name": f["name"],
            "from": f.get("from", "table"),
            "labels": list(f.get("labels", ())),
            "at": f.get("at", "right"),
            "pattern": f.get("pattern", ""),
            "format": f.get("format", ""),
            "equals": f.get("equals", ""),
            "required": bool(f.get("required", False)),
            "options": list(f.get("options", ())),
            "select": f.get("select", ""),
            # from: table_rows 는 labels 가 아니라 columns 로 표를 찾는다.
            "columns": list(f.get("columns", ())),
            "key": f.get("key", ""),
            "requiredColumns": list(f.get("required_columns", ())),
            "capture": f.get("capture", ""),
        }

    wide = [{
        "id": str(c["id"]), "field": c["field"], "rule": c.get("rule", "exact"),
        "ignoring": c.get("ignoring", ""),
        "outputs": (all_keys if c.get("outputs") == "all"
                    else list(c.get("outputs", ()))),
    } for c in spec.get("case_wide", [])]

    pairs = [{
        "id": str(p["id"]), "left": p["left"], "right": p["right"],
        "rows": [{"field": r["field"], "rule": r.get("rule", "exact"),
                  "rightField": r.get("right_field", "")}
                 for r in p.get("rows", [])],
    } for p in spec.get("pairs", [])]

    return {
        "team": spec.get("name", ""),
        "variant": spec.get("variant", ""),
        # 필드 중심 보기. 산출물별로만 주면 같은 필드가 반복된다 — 실측(AI시험인증1):
        # 48줄인데 실제 필드는 20개고 의뢰번호 하나가 7번 나온다. "의뢰번호를
        # 어디서 어떻게 뽑나"는 한 자리에 모여야 검토자가 훑지 않는다.
        "fields": _fields_by_name(outputs, wide, pairs, field),
        "outputs": [{
            "key": o["key"],
            "formNo": o.get("form_no", ""),
            "folder": o.get("folder", ""),
            "fields": [field(f) for f in o.get("fields", [])],
            "fixedText": list(o.get("fixed_text", [])),
            "signatures": [{"role": s["role"], "placeholder": s["placeholder"],
                            "at": s.get("at", "right")}
                           for s in o.get("signatures", [])],
        } for o in outputs],
        # outputs: all 을 글자 그대로 내리면 검토자는 몇 곳인지 모른다. 풀어서 낸다.
        "caseWide": wide,
        "pairs": pairs,
        "manual": [dict(m) for m in spec.get("manual", [])],
        "ignore": [dict(i) for i in spec.get("ignore", [])],
        "itemCount": len(spec.get("items", [])),
    }


def classify_names(names: Sequence[str], spec: dict,
                   team_name: str = "") -> dict:
    """파일명 목록 → 산출물 판별 결과. 파일을 읽지 않는다.

    검사 전에 사람에게 보여주고 확인받는 자리다. 양식번호가 없는 파일은 추측하지
    않고 unclassified 로 넘기며, outputKeys 로 지정 선택지를 함께 준다 —
    추측해 배정하면 엉뚱한 필드맵으로 검사해 거짓 지적이 난다.
    """
    outputs = spec.get("outputs", [])
    ignore_rules = spec.get("ignore", [])
    recognized, unclassified, ignored = [], [], []

    for raw in names:
        name = Path(raw).name
        hit = next((r for r in ignore_rules
                    if r.get("pattern") and re.search(r["pattern"], name)), None)
        if hit:
            ignored.append({"file": name, "reason": hit.get("reason", "")})
            continue
        found = classify_output(name, outputs)
        if found.output_key is None:
            unclassified.append(name)
        else:
            recognized.append({
                "file": name,
                "key": found.output_key,
                "formNo": {"found": found.form_no_found,
                           "expected": found.form_no_expected,
                           "stale": found.revision_stale}})

    seen = {r["key"] for r in recognized}
    return {
        "team": team_name,
        "recognized": recognized,
        "unclassified": unclassified,
        "ignored": ignored,
        "missing": [o["key"] for o in outputs if o["key"] not in seen],
        # 미분류 파일을 사람이 지정할 때 고를 수 있는 것들.
        "outputKeys": [o["key"] for o in outputs],
    }


def output_spec_for(filename: str, spec: dict) -> tuple[dict | None, str]:
    """파일명으로 산출물 하나를 가린다. 못 가리면 (None, 이유).

    폴더 검토는 세트를 통째로 받아 무엇이 무엇인지 가릴 수 있지만, 단일 검토는
    문서 하나만 받는다. 그래서 **판별이 먼저**다 — 엉뚱한 필드맵으로 검사하면
    거짓 지적이 난다(docs/checker-inventory.md "실제로 도는가" 절).

    판별은 파일명으로만 한다. 추측하지 않는다 — 못 가리면 검사를 걸지 않고
    그 사실을 돌려준다. 조용히 건너뛰면 "표지를 검사했는데 이상 없음"과
    "표지를 아예 안 봤음"이 화면에서 같아 보인다.
    """
    outputs = spec.get("outputs") or []
    if not outputs:
        return None, ""      # 이 팀은 칸 값 기준이 아직 없다. 말할 것도 없다.

    # 후보가 하나뿐이면 그것이다. 추측이 아니라 선택지가 없는 것이다 — EV2 가
    # 그렇다(RVVR 필드맵 하나, 양식번호 없음). classify_output 은 양식번호로만
    # 가리므로 여기를 안 열면 EV2 는 영영 칸 값 검사를 못 받는다.
    #
    # 틀린 필드맵이 걸려도 거짓 지적은 안 난다. 라벨을 못 찾으면 "미검토(INFO)"
    # 이고 "비어 있음(MAJOR)"과 갈라져 있다(agent_format/fields.py 첫 주석).
    if len(outputs) == 1:
        return outputs[0], ""
    found = classify_output(filename, list(outputs))
    if found.output_key is None:
        return None, (f"파일명으로 산출물을 가리지 못해 칸 값 검사를 걸지 "
                      f"않았습니다 ({filename}).")
    return next(o for o in outputs if o["key"] == found.output_key), ""


def presence_fields_for(filename: str, spec: dict) -> tuple[list, str]:
    """단일 문서에 쓸 **칸 규격** 목록. 못 가리면 ([], 이유).

    기준(Criterion)이 `check: field_presence` 로 이 규격들을 가져다 쓴다 —
    어느 칸이 자기 몫인지는 그 기준의 `params.fields` 가 이름으로 고른다.
    검사기를 통째로 넘기지 않는 이유는, 표지 항목과 개정기록 항목이 같은 검사기
    하나를 나눠 가지면 둘의 지적이 또 똑같아지기 때문이다.
    """
    output_spec, why = output_spec_for(filename, spec)
    if output_spec is None:
        return [], why
    return _field_specs(output_spec), ""


def presence_checker_for(filename: str, spec: dict) -> tuple[list | None, str]:
    """단일 문서 하나에 쓸 낱장 검사기 목록. 못 가리면 (None, 이유)."""
    output_spec, why = output_spec_for(filename, spec)
    if output_spec is None:
        return None, why
    key = str(output_spec.get("key", ""))
    specs = _field_specs(output_spec)
    sizes = tuple(float(s) for s in output_spec.get("font_sizes", ()) or ())
    if not (specs or output_spec.get("fixed_text")
            or output_spec.get("signatures") or sizes):
        return None, f"‘{key}’의 필드맵이 아직 없습니다."
    out = []
    if specs or output_spec.get("fixed_text") or output_spec.get("signatures"):
        out.append(_presence_checker(output_spec, specs, key))
    if sizes:
        out.append(FontSizeChecker(allowed=sizes, document=key))
    return out, ""


def supplemental_checkers_for(filename: str, spec: dict) -> tuple[list, str]:
    """기준 ``items``가 다루지 않는 outputs 구조 검사기.

    필드 값은 ``check: field_presence`` 기준이 ``field_specs``를 받아 검사하므로 여기서
    다시 넣지 않는다. 고정 문구·서명·글꼴 크기만 평면 구조 지적으로 보탠다. 산출물에
    구조 지도가 전혀 없으면 기존 단일검토와 같은 미검토 이유를 돌려준다.
    """
    output_spec, why = output_spec_for(filename, spec)
    if output_spec is None:
        return [], why
    key = str(output_spec.get("key", ""))
    specs = _field_specs(output_spec)
    sizes = tuple(float(s) for s in output_spec.get("font_sizes", ()) or ())
    fixed = output_spec.get("fixed_text") or []
    signatures = output_spec.get("signatures") or []
    if not (specs or fixed or signatures or sizes):
        return [], f"‘{key}’의 필드맵이 아직 없습니다."
    out = []
    if fixed or signatures:
        out.append(_presence_checker(output_spec, [], key))
    if sizes:
        out.append(FontSizeChecker(allowed=sizes, document=key))
    return out, ""
