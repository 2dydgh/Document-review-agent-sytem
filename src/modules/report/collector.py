"""지적사항 수집: 중복 제거 + 심각도 정렬."""
from __future__ import annotations

from dataclasses import replace

from modules.shared import Finding, Severity

_ORDER = {Severity.MAJOR: 0, Severity.MINOR: 1, Severity.INFO: 2}


def stamp(source, findings) -> list[Finding]:
    """지적에 **무엇이 잡았나**(label)를 찍는다.

    source 는 체커 객체이거나 그냥 이름 문자열이다. 문자열도 받는 이유: 모든 지적이
    체커에서 나오지는 않는다 — 산출물 간 대조(`compare_pair`)와 전체 대조
    (`compare_case_wide`)는 **함수**라 label 을 들 자리가 없다. 그것들을 빼먹으면
    화면 뱃지가 거기서만 `MAJOR` 로 되돌아간다(실제로 그랬다).

    체커가 Finding 마다 자기 이름을 적게 하지 않는 이유: 아홉 군데에 같은 말을
    되풀이하게 되고, 새 체커가 그걸 빠뜨려도 아무도 모른다. **무엇이 검사했는지
    아는 자리**가 한 번에 찍는다.

    이미 label 이 있으면 두지 않는다 — 조립 계층이 더 정확한 이름을 붙였을 수 있다.
    """
    label = source if isinstance(source, str) else (getattr(source, "label", "") or "")
    if not label:
        return list(findings)
    return [f if f.label else replace(f, label=label) for f in findings]


def merge_duplicates(findings: list[Finding]) -> tuple[list[Finding], dict[int, Finding]]:
    """같은 종류(kind)·같은 절·같은 근거 인용 집합의 지적을 하나로 합친다.

    LLM 은 청크×기준묶음마다 따로 불려서, 같은 문장을 같은 이유로 두세 번
    지적한다(실측 SKN56 RVVR: '운영권 조정/운영권조정' 모순 두 장, §4 문장 붕괴
    두 장). 내용이 같으니 카드도 하나여야 한다 — 문구가 조금 다른 쪽은 버려지지만
    남는 카드가 같은 근거로 같은 종류의 잘못을 이미 말한다.

    kind 나 근거가 없는 지적(규칙 검사·INFO 보고·미검토)은 합치지 않는다 —
    동일성을 주장할 신호가 없는데 합치면 다른 지적을 삼키게 된다.

    반환: (생존 목록, {버린 지적의 id(): 생존 지적}). 체크리스트 항목이 버린
    지적을 참조하고 있으면 이 맵으로 생존 지적으로 갈아끼운다 — 항목 쪽 참조를
    끊으면 "이 기준에서 나온 지적"이 조용히 사라진다.
    """
    out: list[Finding] = []
    replaced: dict[int, Finding] = {}
    by_key: dict[tuple, Finding] = {}
    for f in findings:
        quotes = tuple(sorted("".join((e.quote or "").split())
                              for e in (f.evidence or [])))
        kind = getattr(f, "kind", "") or ""
        if not quotes or not kind:
            out.append(f)
            continue
        key = (kind, getattr(f.anchor, "section", None), quotes)
        keep = by_key.get(key)
        if keep is None:
            by_key[key] = f
            out.append(f)
        else:
            replaced[id(f)] = keep
    return out, replaced


def collect(findings: list[Finding]) -> list[Finding]:
    seen = set()
    unique: list[Finding] = []
    for f in findings:
        key = (f.checker, f.severity, f.message, f.anchor, f.document)
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    return sorted(unique, key=lambda f: _ORDER[f.severity])
