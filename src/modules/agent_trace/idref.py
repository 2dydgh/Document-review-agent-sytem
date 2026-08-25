"""ID 참조 추출: 문서 텍스트에서 정규식으로 ID를 스캔한다.

포맷 독립적이다. pattern은 체크리스트 설정값으로 주입된다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from modules.shared import Anchor, Document


@dataclass(frozen=True)
class Statement:
    """ID 하나가 서술된 한 줄과 그 위치."""

    id: str
    text: str
    section_title: str
    anchor: Anchor


# PDF 표 셀 안에서는 ID가 하이픈 뒤에서 줄바꿈된다("FR-\nESCM_08"). 실측
# (SHN34 RVVR)으로 358회. 붙이지 않으면 하위문서에 **실재하는** ID를 못 찾아
# 상위문서의 그 요건이 '누락'으로 보고된다 — 없는 결함을 만들어내는 것이다.
#
# 하이픈으로 끝난 줄만 잇는다. 아무 줄이나 이으면 표의 다음 행이 앞 행에
# 달라붙어 서술이 뒤섞인다.
_WRAP = re.compile(r"-[ \t]*\n[ \t]*")


def _unwrap(text: str | None) -> str:
    return _WRAP.sub("-", text or "")


def extract_id_anchors(doc: Document, pattern: str) -> dict[str, Anchor]:
    """pattern에 매칭되는 ID를 {id: 최초 등장 Anchor}로 반환한다."""
    if not pattern:
        return {}
    rx = re.compile(pattern)
    found: dict[str, Anchor] = {}
    for sec in doc.iter_sections():
        for text in (_unwrap(sec.title), _unwrap(sec.text)):
            for m in rx.finditer(text):
                _id = m.group(0)
                if _id not in found:
                    found[_id] = sec.anchor
    return found


def extract_id_statements(doc: Document, pattern: str) -> dict[str, Statement]:
    """pattern에 매칭되는 ID를 {id: 그 ID가 서술된 한 줄}로 반환한다.

    섹션 단위로 자르면 안 된다. 요구사항은 보통 한 섹션에 여러 개가 나열되므로
    (예: "- SR-001 ...", "- SR-002 ..."), 섹션 전체를 넘기면 어느 요건에 대한
    판단인지 흐려지고 같은 텍스트를 ID 수만큼 반복 전송하게 된다.
    """
    if not pattern:
        return {}
    rx = re.compile(pattern)
    found: dict[str, Statement] = {}
    for sec in doc.iter_sections():
        lines = [_unwrap(sec.title)] + _unwrap(sec.text).splitlines()
        for line in lines:
            for m in rx.finditer(line):
                _id = m.group(0)
                if _id not in found:
                    found[_id] = Statement(
                        id=_id, text=line.strip(), section_title=sec.title,
                        anchor=sec.anchor)
    return found
