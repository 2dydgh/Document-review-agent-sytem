"""팀이 정리해 준 md 가 팀 기준 yaml 에 다 옮겨졌는가.

기준의 **원본은 팀 md** 이고 yaml 은 그것을 옮긴 것이다(presets/README.md). 둘이
어긋나도 앱은 아무 말을 안 한다 — yaml 에 없는 기준은 애초에 검사되지 않으니
화면은 그냥 "지적 없음"이 된다. 그건 이 프로젝트가 계속 막으려던 조용한 0건이다.

그래서 대조를 테스트로 건다. 팀이 md 에 줄을 더하면 여기서 깨지고, "yaml 에 아직
안 옮겼다"고 알려준다.

**대조 방식은 두 가지다.**

1. 요건 ID (CVR01-01 · SRVR14-02 …) — 정확 대조. 있거나 없거나다.
2. 체크박스 줄 — 낱말 대조. yaml 은 md 를 그대로 베끼지 않는다(여러 줄을 한 항목에
   묶거나, 값은 outputs 절로 간다). 그래서 문구 일치가 아니라 **그 줄의 낱말이
   yaml 어딘가에 있는가**를 본다. items 뿐 아니라 outputs·pairs·case_wide·manual
   까지 건초더미에 넣는다 — md 한 줄이 반드시 items 로 가지는 않는다.

아직 안 옮긴 줄은 KNOWN_GAPS 에 적어 통과시킨다. **목록을 늘리는 것은 빚을 지는
것이다** — 지우는 방향으로만 움직여야 한다. 여기 없는 새 줄이 나타나면 실패한다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
MD_ROOT = ROOT / "data" / "AX안전신뢰실"
CRITERIA = ROOT / "presets" / "criteria" / "teams"

#: 팀 기준 yaml ← 그 팀이 정리해 준 md 들.
PAIRS: dict[str, list[str]] = {
    "ax-quality.yaml": [
        "AX품질팀/품질팀_VV_단일문서_검토요구사항.md",
        "AX품질팀/품질팀_VV_문서간_검토요구사항.md",
        "AX품질팀/품질팀_VV_검토의견서_및_보고서_요구사항.md",
    ],
    "ai-test-cert-1.yaml": [
        "AI시험인증팀/AI시험인증1팀_요구사항_단일문서.md",
        "AI시험인증팀/AI시험인증1팀_요구사항_문서 간.md",
    ],
}

#: 아직 yaml 로 안 옮긴 md 줄. 앞머리 40자로 적는다.
#:
#: **줄이는 방향으로만 고친다.** 새 줄을 여기 더하는 것은 "옮기지 않기로 했다"가
#: 아니라 "아직 못 옮겼다"는 기록이다 — 왜 못 옮겼는지 한 줄로 남긴다.
KNOWN_GAPS: dict[str, dict[str, str]] = {
    "ai-test-cert-1.yaml": {
        "파일명과 꼬리말의 양식 번호가 서로 일치": "파일명↔꼬리말 대조 검사기 없음",
        "파일명에 의뢰번호(`SST-26-001`) 포함": "filename 검사기에 붙일 params 미정",
        "**버전 셀에는 숫자만** (제품명 셀과 별도": "산출물별 칸 규칙 — outputs 에 자리 필요",
        "선택 항목이 각각 하나씩만 체크": "체크박스 단일선택 검사기 없음",
        "신청인·접수자 서명란 작성 (일자 포함)": "시험의뢰서 outputs 에 signatures 절 없음",
        "조건부: 시험방법(적용 규격) — 표준명이": "조건부 항목 — 조건을 표현할 자리 없음",
        "**성적서 유형 문구**가 해당 유형(일반 /": "유형별 고정문구 — variant 축 필요",
        "인계자 소속 기재": "제출물 확인증 outputs 에 칸 없음",
        "문서 작성일자가 **계약 이후 · 의뢰서 작성일": "문서 간 일자 순서 — case_wide 로 갈 항목",
        "시험 대상 품명이 **버전 제외**로 기재되고": "산출물별 칸 규칙 — outputs 에 자리 필요",
        "각 확인 항목의 **적합/부적합이 하나만** 체크": "체크박스 단일선택 검사기 없음",
        "확인결과 문구 작성 — `확인 결과, 현장 시험을":
            "산출물별 고정문구 — outputs.fixed_text 로 갈 항목",
        "저장일자 기재": "시험기록서 outputs 에 칸 없음",
        "품명은 **버전 제외**, 버전은 별도 셀에 숫자만": "산출물별 칸 규칙 — outputs 에 자리 필요",
        "파일 규모(LOC)·주석 비율 칸 — 해당 없으면": "시험기록서 outputs 에 칸 없음",
        "번호 체계가 올바른가": "번호 체계 검사기 없음 (표는 md 에만)",
        "시험결과란에 `Pass(별첨 참조)` 표기": "산출물별 고정문구 — outputs.fixed_text 로 갈 항목",
    },
}

#: yaml 이 **값으로** 담고 있어 낱말 대조로는 안 잡히는 md 줄.
#:
#: md 는 "회사명·전화·홈페이지가 안 바뀌었나"라고 **설명**하는데 yaml 은
#: `슈어소프트테크㈜`·`031-606-2000` 이라는 **값**을 적는다. 겹치는 낱말이 없으니
#: 대조가 실패하지만 실제로는 검사된다(outputs.fixed_text → FieldPresenceChecker).
#:
#: KNOWN_GAPS 와 갈라 둔다 — 저쪽은 빚이고 이쪽은 정상이다. 뭉치면 다음 사람이
#: "아직 못 한 것 19개" 를 보고 이미 되는 검사까지 다시 만든다.
COVERED_BY_VALUE: dict[str, dict[str, str]] = {
    "ai-test-cert-1.yaml": {
        "템플릿 고정값 미변경 — 회사명": "outputs[갑지].fixed_text 에 값 그대로 있음",
        "**비고문구 4개 모두 유지**": "outputs[갑지].fixed_text 에 4문구 전문이 있음",
    },
}

_ID = re.compile(r"\b((?:CVR|SRVR|DVR)\d\d)-(\d\d)\b")
_ID_RANGE = re.compile(r"\b((?:CVR|SRVR|DVR))(\d\d)-(\d\d)~(\d\d)\b")
_CHECKBOX = re.compile(r"\s*- \[ \]\s*(.+)")
_WORD = re.compile(r"[가-힣A-Za-z]{2,}")


def _expand(text: str) -> set[str]:
    """문서에 적힌 요건 ID 전부. `SRVR03-01~07` 같은 범위도 펼친다."""
    ids: set[str] = set()
    for m in _ID_RANGE.finditer(text):
        prefix, group, first, last = m.groups()
        ids |= {f"{prefix}{group}-{i:02d}" for i in range(int(first), int(last) + 1)}
    for m in _ID.finditer(text):
        ids.add(f"{m.group(1)}-{m.group(2)}")
    return ids


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text))


def _yaml_text(path: Path) -> str:
    """yaml 전체를 한 덩어리 문자열로. items 밖(outputs·pairs·manual)도 건초더미다.

    **공통 기준도 함께 넣는다.** 팀 md 의 한 줄이 공통 기준으로 덮이는 일이 있다 —
    실측: AI시험인증1팀 md §1.4 의 "맞춤법·오탈자"는 팀 항목(No.15)이 지고 있었는데,
    그것이 공통 C1 과 같은 검사라 팀에서 뺐다(2026-08-20). 팀 파일만 보면 그 줄이
    사라진 것처럼 보이지만 검사는 그대로 돈다.
    """
    blob = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    common_path = path.parent.parent / "common.yaml"
    common = (yaml.safe_load(common_path.read_text(encoding="utf-8")) or {}
              if common_path.is_file() else {})
    return json.dumps([blob, common], ensure_ascii=False)


def _checkbox_lines(md: Path) -> list[str]:
    return [m.group(1).strip()
            for m in (_CHECKBOX.match(ln.rstrip()) for ln in
                      md.read_text(encoding="utf-8").splitlines())
            if m]


@pytest.mark.parametrize("yaml_name", sorted(PAIRS))
def test_team_md_ids_all_present(yaml_name: str) -> None:
    """md 가 매긴 요건 ID 가 yaml 에 하나도 빠짐없이 있는가."""
    ypath = CRITERIA / yaml_name
    if not ypath.is_file():
        pytest.skip(f"{yaml_name} 없음")
    blob = _yaml_text(ypath)
    have = _expand(blob)

    missing: list[str] = []
    for rel in PAIRS[yaml_name]:
        md = MD_ROOT / rel
        if not md.is_file():
            pytest.skip(f"{rel} 없음 — 사내 문서라 clone 에 따라 빠질 수 있다")
        missing += sorted(i for i in _expand(md.read_text(encoding="utf-8"))
                          if i not in have)

    assert not missing, (
        f"{yaml_name}: md 의 요건 ID {len(missing)}개가 yaml 에 없습니다 — "
        f"{missing}. 팀이 md 에 항목을 더했다면 yaml 에도 옮겨야 검사됩니다.")


@pytest.mark.parametrize("yaml_name", sorted(PAIRS))
def test_team_md_checkboxes_all_covered(yaml_name: str) -> None:
    """md 체크박스 줄의 내용이 yaml 어딘가에 있는가 (KNOWN_GAPS 는 뺀다)."""
    ypath = CRITERIA / yaml_name
    if not ypath.is_file():
        pytest.skip(f"{yaml_name} 없음")
    hay = _words(_yaml_text(ypath))
    skip = {**KNOWN_GAPS.get(yaml_name, {}), **COVERED_BY_VALUE.get(yaml_name, {})}

    uncovered: list[str] = []
    for rel in PAIRS[yaml_name]:
        md = MD_ROOT / rel
        if not md.is_file():
            pytest.skip(f"{rel} 없음 — 사내 문서라 clone 에 따라 빠질 수 있다")
        for line in _checkbox_lines(md):
            if any(line.startswith(k) for k in skip):
                continue
            words = _words(line)
            if not words:
                continue
            # 낱말의 절반 넘게 yaml 에 없으면 안 옮긴 것으로 본다. 문턱을 낮게
            # 잡으면 한 항목에 여러 md 줄을 묶은 정상 변환이 실패로 뜬다.
            if len(words - hay) / len(words) > 0.45:
                uncovered.append(line[:70])

    assert not uncovered, (
        f"{yaml_name}: yaml 에 옮기지 않은 md 줄 {len(uncovered)}개 —\n  "
        + "\n  ".join(uncovered)
        + "\n\n옮기거나, 아직 못 옮기는 이유를 KNOWN_GAPS 에 적으세요.")


def test_known_gaps_are_real_md_lines() -> None:
    """KNOWN_GAPS 에 적힌 앞머리가 실제 md 줄과 맞는가.

    md 가 고쳐져 그 줄이 사라지면 예외 항목이 죽은 채로 남는다. 죽은 예외는
    다음 사람에게 "이건 못 한다"고 잘못 알려준다.
    """
    stale: list[str] = []
    both = {k: {**KNOWN_GAPS.get(k, {}), **COVERED_BY_VALUE.get(k, {})}
            for k in set(KNOWN_GAPS) | set(COVERED_BY_VALUE)}
    for yaml_name, gaps in both.items():
        lines: list[str] = []
        for rel in PAIRS[yaml_name]:
            md = MD_ROOT / rel
            if md.is_file():
                lines += _checkbox_lines(md)
        if not lines:
            pytest.skip(f"{yaml_name} 의 md 가 없음")
        stale += [f"{yaml_name}: {k}" for k in gaps
                  if not any(ln.startswith(k) for ln in lines)]

    assert not stale, (
        "KNOWN_GAPS 에 md 에 없는 줄이 적혀 있습니다 (md 가 바뀐 듯) — "
        f"{stale}. 옮겼거나 사라진 항목이면 목록에서 지우세요.")
