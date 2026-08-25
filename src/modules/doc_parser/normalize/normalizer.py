"""RawDoc를 내부 Document 모델로 정규화 (마크다운 heading 파싱)."""
from __future__ import annotations

import re

from modules.shared import Anchor, Document, Section

from ..ingestion.base import RawDoc

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

# PDF 로더가 페이지 경계에 넣는 표시. 본문에는 남기지 않고 쪽 번호만 센다.
_PAGE_BREAK = "\f"


def normalize(raw: RawDoc, doc_type: str | None = None) -> Document:
    roots: list[Section] = []
    stack: list[Section] = []
    counters: dict[int, int] = {}
    # heading 밖의 본문. PDF는 쪽마다 따로 모은다 (아래 _page_sections 참고).
    preamble: dict[int, list[str]] = {}
    # 페이지 정보가 없는 포맷(마크다운/HWPX)에서는 계속 None으로 둔다.
    paginated = _PAGE_BREAK in raw.text
    page = 1 if paginated else None

    def section_number(level: int) -> str:
        counters[level] = counters.get(level, 0) + 1
        for deeper in [k for k in counters if k > level]:
            del counters[deeper]
        parts = [str(counters[l]) for l in sorted(counters) if l <= level]
        return ".".join(parts)

    # splitlines()를 쓰면 안 된다. 폼피드(\f)를 줄바꿈으로 취급해 삼켜버려서
    # 페이지 표시가 사라진다 (\v, \x1c,  도 마찬가지).
    for line in raw.text.replace("\r\n", "\n").split("\n"):
        # strip()으로 지우면 안 된다. \f는 공백문자라 통째로 사라진다.
        if paginated and line.strip(" \t\r") == _PAGE_BREAK:
            page += 1
            continue

        m = _HEADING.match(line)
        if not m:
            if stack:
                s = stack[-1]
                s.text = (s.text + "\n" + line).strip() if s.text else line.strip()
            else:
                preamble.setdefault(page or 0, []).append(line)
            continue

        level = len(m.group(1))
        title = m.group(2).strip()
        number = section_number(level)
        node = Section(id=number, title=title, level=level, text="",
                       anchor=Anchor(page=page, section=number), children=[])
        while stack and stack[-1].level >= level:
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)

    for section in reversed(_body_sections(preamble, paginated)):
        roots.insert(0, section)

    # 서식 정보는 본문으로 안 남는다. 로더가 모은 것을 **그대로** 넘긴다 —
    # 여기서 고르면 파서마다 무엇이 오는지 두 곳에서 알아야 한다.
    #
    # 실제로 그 일이 났다(2026-08-20): 주석은 "그대로 넘긴다" 인데 코드는 `tables`
    # 하나만 통과시켰다. 파서가 머릿말을 meta["headers"] 로 옮겨도 여기서 사라져,
    # 머릿말 검사가 "파서가 머릿말을 싣지 못했다"고 매번 보고했다 — 싣고 있었는데.
    #
    # Document.meta 주석이 "여기 아무거나 담지 않는다"고 못박고 있으므로, 거르는
    # 자리는 **넣는 쪽**(로더)이지 여기가 아니다.
    return Document(source_path=raw.source_path, doc_type=doc_type, sections=roots,
                    meta=dict(raw.meta))


def _body_sections(preamble: dict[int, list[str]], paginated: bool) -> list[Section]:
    """heading에 속하지 않는 본문을 섹션으로 만든다.

    PDF에는 heading이 없어 문서 전체가 여기로 온다. 한 덩어리로 묶으면 위치가
    사라지므로 쪽마다 섹션을 만든다. 그래야 지적사항이 "3쪽"을 가리킬 수 있다.
    """
    if not paginated:
        body = "\n".join(preamble.get(0, [])).strip()
        if not body:
            return []
        return [Section(id="0", title="(본문)", level=0, text=body,
                        anchor=Anchor(page=None, section="0"), children=[])]

    sections = []
    for page in sorted(preamble):
        body = "\n".join(preamble[page]).strip()
        if not body:
            continue
        sections.append(Section(id=str(page), title=f"{page}쪽", level=0, text=body,
                                anchor=Anchor(page=page, section=str(page)),
                                children=[]))
    return sections
