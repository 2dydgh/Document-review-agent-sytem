"""지적사항 마크다운 렌더."""
from __future__ import annotations

import json
from collections import Counter

from modules.shared import Finding, RtmRow

_STATUS_LABEL = {
    "linked": "✅ 연결됨",
    "missing": "❌ 누락",
    "orphan": "⚠️ 근거없음",
    "out_of_scope": "➖ 범위 밖",
    "rolled_up": "🔗 부모 수준 검증",
}


def render_markdown(findings: list[Finding], source_path: str) -> str:
    lines = [f"# 문서 검토 결과: {source_path}", ""]
    counts = Counter(f.severity.value for f in findings)
    lines.append(f"총 {len(findings)}건 " + ", ".join(
        f"{sev} {n}" for sev, n in counts.items()) if findings else "지적사항 없음.")
    lines.append("")
    for f in findings:
        loc = f.anchor.section or f.anchor.page or "-"
        where = f"{f.document} " if f.document else ""
        lines.append(f"- **[{f.severity.value}]** ({f.checker}, {where}위치 {loc}) {f.message}")
        if f.suggestion:
            lines.append(f"  - 제안: {f.suggestion}")
    return "\n".join(lines) + "\n"


def _finding_to_dict(f: Finding) -> dict:
    d = {
        "checker": f.checker,
        "severity": f.severity.value,
        "message": f.message,
        "anchor": {"page": f.anchor.page, "section": f.anchor.section},
        "suggestion": f.suggestion,
    }
    if f.document is not None:
        d["document"] = f.document
    if f.rescued:
        # 재질의 왕복 끝에 근거를 찾은 지적. UI payload 와 같은 이유로 리포트에도
        # 남긴다 — 출처를 숨기면 실측(복원 지적만 골라 검수)이 리포트로는 안 된다.
        d["rescued"] = True
        if f.rescue_trace:
            d["rescue_trace"] = f.rescue_trace
    if f.evidence:
        d["evidence"] = [
            {"section": e.anchor.section, "page": e.anchor.page, "quote": e.quote}
            for e in f.evidence
        ]
    return d


def render_json(findings: list[Finding], source_path: str) -> str:
    by_severity = Counter(f.severity.value for f in findings)
    payload = {
        "source_path": source_path,
        "summary": {"total": len(findings), "by_severity": dict(by_severity)},
        "findings": [_finding_to_dict(f) for f in findings],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _rtm_counts(rows: list[RtmRow]) -> Counter:
    return Counter(r.status for r in rows)


def render_rtm_markdown(
    rows: list[RtmRow], findings: list[Finding], source_path: str
) -> str:
    """전체 추적성 매트릭스 표 + 조치 필요 항목을 마크다운으로 렌더한다."""
    counts = _rtm_counts(rows)
    lines = [f"# 추적성 매트릭스: {source_path}", ""]
    summary = (f"총 {len(rows)}개 항목 — 연결 {counts['linked']}, "
               f"누락 {counts['missing']}, 근거없음 {counts['orphan']}")
    if counts["rolled_up"]:
        # 누락은 아니지만 연결도 아니다. 세부 요건이 개별로 검증됐는지는
        # 사람이 봐야 하므로 개수를 드러낸다.
        summary += f", 부모 수준 검증 {counts['rolled_up']}"
    if counts["out_of_scope"]:
        # 조용히 빼지 않는다. 진짜 누락이 여기 묻힐 수 있다.
        summary += f", 범위 밖 {counts['out_of_scope']}(검사 안 함)"
    lines.append(summary)
    lines.append("")
    lines.append("| 상위 ID | 하위 연결 | 상태 |")
    lines.append("|---|---|---|")
    for r in rows:
        upper = r.upper_id or "—"
        lower = ", ".join(r.lower_ids) if r.lower_ids else "(없음)"
        label = _STATUS_LABEL.get(r.status, r.status)
        lines.append(f"| {upper} | {lower} | {label} |")

    if findings:
        lines.append("")
        lines.append(f"## 조치 필요 ({len(findings)}건)")
        for f in findings:
            loc = f.anchor.section or f.anchor.page or "-"
            where = f"{f.document} " if f.document else ""
            lines.append(
                f"- **[{f.severity.value}]** ({where}위치 {loc}) {f.message}")
            if f.suggestion:
                lines.append(f"  - 제안: {f.suggestion}")
    return "\n".join(lines) + "\n"


def _rtm_row_to_dict(r: RtmRow) -> dict:
    return {
        "upper_id": r.upper_id,
        "lower_ids": r.lower_ids,
        "status": r.status,
        "anchor": {"page": r.anchor.page, "section": r.anchor.section},
    }


def render_rtm_json(
    rows: list[RtmRow], findings: list[Finding], source_path: str
) -> str:
    counts = _rtm_counts(rows)
    payload = {
        "source_path": source_path,
        "summary": {
            "total": len(rows),
            "linked": counts["linked"],
            "missing": counts["missing"],
            "orphan": counts["orphan"],
            "out_of_scope": counts["out_of_scope"],
            "rolled_up": counts["rolled_up"],
        },
        "rtm": [_rtm_row_to_dict(r) for r in rows],
        "findings": [_finding_to_dict(f) for f in findings],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
