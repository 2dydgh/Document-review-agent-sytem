"""폴더 검토의 외부 원천 입력값 추가 대조.

문서 파서에 의존하지 않고 이력 payload의 추출값만 다룬다. 점검 확정 API에서도
가볍게 불러올 수 있고, 업로드 원본이 삭제된 뒤에도 같은 결과를 재현할 수 있다.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

_DATE = re.compile(
    r"^(\d{4})\s*(?:[./-]|년)\s*(\d{1,2})\s*(?:[./-]|월)\s*(\d{1,2})\s*(?:\.|일)?$")


def _comparison_key(field_name: str, value: str) -> str | None:
    """원천 시스템과 문서의 표기 차이가 값 차이로 오인되지 않게 한다.

    날짜만 형식을 걷어낸다. 의뢰기관명은 기준이 띄어쓰기까지 같아야 한다고 명시해
    공백을 없애면 안 되고, 접수번호도 시스템 부여 문자열을 그대로 비교해야 한다.
    """
    stripped = value.strip()
    if field_name.endswith("일") or "날짜" in field_name:
        matched = _DATE.fullmatch(stripped)
        if not matched:
            return None
        try:
            parsed = date(*(int(part) for part in matched.groups()))
        except ValueError:
            return None
        return parsed.isoformat()
    return stripped


def manual_review_patch(payload: dict, checked: Sequence[str],
                        inputs: dict[str, str]) -> dict:
    """외부 원천 입력값을 이미 추출한 문서 필드와 대조한다.

    브라우저가 지적 자체를 보내게 두지 않는다. 입력값만 받고, 지적은 서버가 저장된
    추출값으로 다시 만든다. 재확정 때 예전 추가 지적이 중복되지 않도록
    ``kind=manual_input``만 갈아 끼운다.
    """
    manual = [dict(m) for m in payload.get("manual", [])]
    checked_set = {str(i) for i in checked}
    clean_inputs = {str(k): str(v).strip() for k, v in inputs.items()}
    results: list[dict] = []
    generated: list[dict] = []

    for item in manual:
        item_id = str(item.get("id", ""))
        # 기존 기준은 M-접수번호처럼 id에 필드명이 들어 있다. 앞으로는 서로 다른
        # 표시 이름이 필요할 수 있으므로 명시적인 field가 있으면 그것을 우선한다.
        field_name = str(item.get("field") or item_id.removeprefix("M-"))
        source_value = clean_inputs.get(item_id, "")
        is_checked = item_id in checked_set
        cells: list[dict] = []
        for output in payload.get("outputs", []):
            field_value = next((f for f in output.get("fields", [])
                                if f.get("name") == field_name), None)
            if field_value is None:
                continue
            found = bool(field_value.get("found"))
            value = str(field_value.get("value") or "") if found else ""
            source_key = _comparison_key(field_name, source_value)
            value_key = _comparison_key(field_name, value)
            cells.append({
                "output": str(output.get("key", "")),
                "value": value,
                "found": found,
                "at": str(field_value.get("at") or ""),
                "page": field_value.get("page"),
                "label": str(field_value.get("label") or ""),
                "sourceQuote": str(field_value.get("sourceQuote") or ""),
                "ok": (source_key is not None and value_key == source_key)
                      if found and source_value else None,
            })

        result = {
            "id": item_id,
            "text": str(item.get("text") or ""),
            "against": str(item.get("against") or ""),
            "field": field_name,
            "input": source_value,
            "checked": is_checked,
            "status": "확인 전",
            "correctValue": source_value,
            "affectedCount": 0,
            "affected": [],
            "cells": cells,
        }
        if not is_checked:
            results.append(result)
            continue
        if not source_value:
            result["status"] = "입력 없음"
            results.append(result)
            continue

        if _comparison_key(field_name, source_value) is None:
            result["status"] = "입력값 오류"
            document = " · ".join(c["output"] for c in cells)
            generated.append({
                "id": f"manual:{item_id}",
                "ruleId": item_id,
                "kind": "manual_input",
                "label": "외부 기준값 대조",
                "sev": "info",
                "message": (f"'{field_name}' 외부 입력값의 날짜 형식을 확인해 주세요: "
                            f"{source_value!r}"),
                "document": document,
                "unreviewed": True,
                "evidence": [],
            })
            results.append(result)
            continue

        seen = [c for c in cells if c["found"]]
        gaps = [c["output"] for c in cells if not c["found"]]
        mismatched = [c for c in seen if not c["ok"]]
        document = " · ".join(c["output"] for c in cells)
        evidence = [{"at": c["at"], "page": c["page"],
                     "quote": c["sourceQuote"] or c["value"],
                     "document": c["output"]} for c in seen]

        if mismatched:
            affected = [{"output": c["output"], "currentValue": c["value"],
                         "correctValue": source_value, "at": c["at"]}
                        for c in mismatched]
            result["status"] = "수정 필요"
            result["affectedCount"] = len(affected)
            result["affected"] = affected
            details = " · ".join(
                f"{c['output']} {c['value']!r}" for c in mismatched)
            gap_note = f" (값을 못 찾은 문서: {', '.join(gaps)})" if gaps else ""
            generated.append({
                "id": f"manual:{item_id}",
                "ruleId": item_id,
                "kind": "manual_input",
                "label": "외부 기준값 대조",
                "sev": "major",
                "message": (f"'{field_name}' 일괄 수정이 필요합니다 — 올바른 값 "
                            f"{source_value!r} · 대상 {len(affected)}개 문서: "
                            f"{details}{gap_note}"),
                "document": document,
                "unreviewed": False,
                "evidence": evidence,
            })
        elif gaps or not seen:
            result["status"] = "미검토"
            reason = (f"{', '.join(gaps)}에서 값을 찾지 못했습니다" if gaps
                      else f"'{field_name}' 추출값이 저장된 문서가 없습니다")
            generated.append({
                "id": f"manual:{item_id}",
                "ruleId": item_id,
                "kind": "manual_input",
                "label": "외부 기준값 대조",
                "sev": "info",
                "message": f"'{field_name}'를 외부 입력값과 대조하지 못했습니다 — {reason}",
                "document": document,
                "unreviewed": True,
                "evidence": evidence,
            })
        else:
            result["status"] = "일치"
        results.append(result)

    findings = [dict(f) for f in payload.get("findings", [])
                if f.get("kind") != "manual_input"] + generated
    stats = dict(payload.get("stats") or {})
    stats["findings"] = sum(1 for f in findings if not f.get("unreviewed"))
    stats["unreviewed"] = sum(1 for f in findings if f.get("unreviewed"))
    ordered_checked = [str(m.get("id")) for m in manual
                       if str(m.get("id")) in checked_set]
    ordered_inputs = {str(m.get("id")): clean_inputs[str(m.get("id"))]
                      for m in manual if clean_inputs.get(str(m.get("id")), "")}
    return {
        "manualChecked": ordered_checked,
        "manualInputs": ordered_inputs,
        "manualResults": results,
        "findings": findings,
        "stats": stats,
    }
