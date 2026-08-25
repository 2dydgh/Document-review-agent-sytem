"""docx 의 `w:ptab`(절대위치 탭)을 LibreOffice 가 읽는 탭으로 바꾼다.

**LibreOffice 는 `w:ptab` 을 통째로 무시한다.** 간격을 아예 넣지 않아서, 머릿말의
`의뢰번호 …[오른쪽 끝으로]… 성적서번호` 가 붙어 나온다. 실측(SST-26-999 시험 문서,
A4·여백 28pt):

    원본이 지시한 끝 위치   567pt (오른쪽 여백선)
    변환 결과               314pt  ← 성적서번호가 쪽 한가운데에 있다
    이 모듈을 거친 뒤        567pt

`w:ptab` 은 Word 2010+ 기능이라 옛 문서에는 없다. 있는 문서만 손댄다.

**원본 파일은 건드리지 않는다.** 임시 사본을 만들어 그 안의 머릿말·꼬리말 XML 만
고친다 — 사용자가 올린 문서를 우리가 고쳐 놓으면 안 된다.

## 왜 스타일의 탭 정지를 쓰지 않나

바꿔 넣을 자리를 문단 스타일이 이미 갖고 있는 것처럼 보인다(Word 기본 머리글
스타일 `header` 는 center·right 두 정지를 갖는다). 하지만 그 값은 **기본 여백
(1인치) 기준으로 만들어진 것**이고 문서가 여백을 바꿔도 갱신되지 않는다. 실측한
문서가 그랬다 — 스타일은 right@9026twip(=451pt)인데 실제 본문 폭은 539pt 라,
그 정지를 쓰면 87pt 짧게 붙는다. `w:ptab` 은 "여백 기준"이라고 말하고 있으므로
**여백에서 직접 계산한다.**

## 상속된 정지를 지워야 한다

정지를 더하기만 하면 안 된다. 탭 문자는 **가장 가까운** 정지로 가는데, 스타일의
낡은 정지가 앞에 있으면 거기서 멈춘다 — 실측: 정지를 10772 에 더했는데도 성적서번호가
스타일의 center@4513 으로 가서 쪽 한가운데(194pt)에 그대로 있었다. 그래서 우리 정지
앞에 있는 상속 정지를 `w:val="clear"` 로 지운다.

지운 뒤에는 우리 정지 하나만 남는다. 그보다 왼쪽에는 정지가 없으므로 탭 문자가
거기까지 간다(자동 탭 정지는 마지막 명시 정지 **뒤에서만** 작동한다).

## 본문 폭은 **그 머릿말이 붙는 구역**에서 가져온다

문서 하나에 구역(sectPr)이 여럿이고 여백이 서로 다르다 — 실측한 문서 표준화
가이드는 구역이 16개였고 첫 구역만 좌 85pt, 나머지는 71pt 였다. 첫 구역의 폭으로
탭을 놓았더니 나머지 쪽의 꼬리말이 13pt 왼쪽으로 밀렸다(고치기 전보다 나빴다).

그래서 구역의 `headerReference`/`footerReference` 를 rels 로 따라가 **파트마다**
자기 구역의 폭을 쓴다. 한 파트가 폭이 다른 구역 여럿에 걸쳐 있으면 어느 쪽에
맞춰야 할지 알 수 없으므로 **손대지 않는다** — 반쯤 맞히느니 그대로 두는 게 낫다.
"""
from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

#: 머릿말·꼬리말 파트만 손댄다. 본문의 w:ptab 은 드물고, 본문은 탭 정지가
#: 문단마다 제각각이라 잘못 건드리면 멀쩡한 줄이 밀린다.
_PART = re.compile(r"word/(?:header|footer)\d+\.xml$")

_PTAB = re.compile(r"<w:ptab\b[^>]*/>")
_ALIGN = re.compile(r'w:alignment="(\w+)"')
_RELATIVE_TO = re.compile(r'w:relativeTo="(\w+)"')
_PARA = re.compile(r"<w:p\b[^>]*>.*?</w:p>", re.S)
_PPR = re.compile(r"<w:pPr\b[^>]*>(.*?)</w:pPr>", re.S)
_PSTYLE_END = re.compile(r"(<w:pStyle\b[^>]*/>)")
_PSTYLE_ID = re.compile(r'<w:pStyle w:val="([^"]+)"')
_STYLE = re.compile(r"<w:style\b[^>]*w:styleId=\"([^\"]+)\"[^>]*>(.*?)</w:style>", re.S)
_BASED_ON = re.compile(r'<w:basedOn w:val="([^"]+)"')
_STOP = re.compile(r'<w:tab w:val="(\w+)" w:pos="(-?\d+)"')
_SECTPR = re.compile(r"<w:sectPr\b[^>]*>.*?</w:sectPr>", re.S)
_PART_REF = re.compile(r"<w:(header|footer)Reference\b([^>]*)/?>")
_REF_ID = re.compile(r'r:id="([^"]+)"')
_REF_TYPE = re.compile(r'w:type="([^"]+)"')
_REL = re.compile(r'<Relationship\b[^>]*Id="([^"]+)"[^>]*Target="([^"]+)"')

#: OOXML 은 pPr 자식의 순서를 정해 두는데, tabs 는 pStyle 뒤쪽이다. 완전히
#: 지키려면 스키마를 들여야 해서, 실제로 문제되는 하나만 맞춘다 — pStyle 바로
#: 뒤에 넣는다. LibreOffice 는 순서에 관대하고 이 파일은 LibreOffice 만 읽는다.


def _page_metrics(doc_xml: str) -> tuple[int, int] | None:
    """(본문 폭, 좌여백) — twip. 못 읽으면 None.

    첫 sectPr 만 본다. 구역마다 쪽 크기가 다른 문서는 드물고, 다르더라도 머릿말은
    보통 같은 폭을 쓴다. 못 읽으면 아무것도 하지 않는다 — 지어낸 폭으로 탭을 놓으면
    멀쩡한 머릿말이 밀린다.
    """
    size = re.search(r"<w:pgSz\b([^/>]*)/?>", doc_xml)
    margin = re.search(r"<w:pgMar\b([^/>]*)/?>", doc_xml)
    if not (size and margin):
        return None
    sz = dict(re.findall(r'w:(\w+)="(-?\d+)"', size.group(1)))
    mg = dict(re.findall(r'w:(\w+)="(-?\d+)"', margin.group(1)))
    try:
        width = int(sz["w"]) - int(mg["left"]) - int(mg["right"])
        left = int(mg["left"])
    except (KeyError, ValueError):
        return None
    return (width, left) if width > 0 else None


def part_text_widths(doc_xml: str, rels_xml: str) -> dict[str, int | None]:
    """머릿말·꼬리말 파트 이름 → 그 파트가 붙는 구역의 본문 폭(twip).

    폭이 다른 구역 여럿이 같은 파트를 쓰면 **None** 이다 — 어느 쪽에 맞출지 알 수
    없다. 그때 호출부는 그 파트를 건너뛴다. 문서 첫 구역 폭으로 폴백하면 안 된다:
    그 폭이 맞을 이유가 없고, 실제로 그렇게 했다가 꼬리말을 13pt 밀어 고치기
    전보다 나쁘게 만들었다.

    아예 안 나오는 파트(구역이 참조하지 않는 파트)는 키가 없다 — 그건 폴백해도
    된다. "어느 구역인지 모른다"와 "구역이 여럿인데 폭이 다르다"는 다르다.
    """
    targets = {rid: ("word/" + tgt.lstrip("/")) if not tgt.startswith("word/") else tgt
               for rid, tgt in _REL.findall(rels_xml)}
    widths: dict[str, set[int]] = {}
    active: dict[tuple[str, str], str] = {}
    for sect in _SECTPR.findall(doc_xml):
        # 참조가 없는 다음 구역은 앞 구역의 머릿말·꼬리말을 물려받는다. 구역마다
        # 폭이 다른데 이 상속을 빼먹으면 공유 파트를 한 폭에 맞춰 잘못 고친다.
        for kind, attrs in _PART_REF.findall(sect):
            rid = _REF_ID.search(attrs)
            if rid is None:
                continue
            name = targets.get(rid.group(1))
            if name:
                ref_type = _REF_TYPE.search(attrs)
                active[(kind, ref_type.group(1) if ref_type else "default")] = name
        metrics = _page_metrics(sect)
        if metrics is None:
            continue
        width, _left = metrics
        for name in active.values():
            widths.setdefault(name, set()).add(width)
    return {name: (next(iter(w)) if len(w) == 1 else None)
            for name, w in widths.items()}


def style_tab_stops(styles_xml: str) -> dict[str, list[int]]:
    """스타일 id → 그 스타일이 물려주는 탭 정지 위치들(twip).

    basedOn 사슬을 따라 올라가 물려받은 것까지 모은다. 사슬이 도는 문서가 있어
    (실무 문서에서 실제로 본다) 방문한 것을 표시해 무한 반복을 막는다.
    """
    own: dict[str, list[int]] = {}
    based: dict[str, str] = {}
    for sid, body in _STYLE.findall(styles_xml):
        own[sid] = [int(pos) for val, pos in _STOP.findall(body) if val != "clear"]
        parent = _BASED_ON.search(body)
        if parent:
            based[sid] = parent.group(1)

    out: dict[str, list[int]] = {}
    for sid in own:
        stops: list[int] = []
        seen: set[str] = set()
        cur: str | None = sid
        while cur and cur not in seen and cur in own:
            seen.add(cur)
            stops.extend(own[cur])
            cur = based.get(cur)
        out[sid] = stops
    return out


def _fix_paragraph(para: str, text_width: int,
                   style_stops: dict[str, list[int]]) -> str:
    """문단 하나의 w:ptab 을 탭 정지 + 탭 문자로 바꾼다."""
    ptabs = _PTAB.findall(para)
    supported: list[str] = []
    for raw in ptabs:
        align = _ALIGN.search(raw)
        relative = _RELATIVE_TO.search(raw)
        if (align and align.group(1) in {"center", "right"}
                and relative and relative.group(1) == "margin"):
            supported.append(raw)
    if not supported:
        return para

    # 나온 순서대로 정지를 만든다. 같은 문단에 center → right 가 이어지면
    # 탭 문자도 둘이고, 각각 자기 정지로 간다.
    stops: list[str] = []
    positions: list[int] = []
    for raw in supported:
        found = _ALIGN.search(raw)
        align = found.group(1)
        if align == "right":
            pos = text_width
        else:
            pos = text_width // 2
        stops.append(f'<w:tab w:val="{align}" w:pos="{pos}"/>')
        positions.append(pos)

    supported_set = set(supported)
    out = _PTAB.sub(
        lambda match: "<w:tab/>" if match.group(0) in supported_set
        else match.group(0), para)

    # 우리 정지보다 왼쪽에 있는 상속·기존 정지를 지운다. 안 지우면 탭이 거기서
    # 멈춘다(모듈 머리말 "상속된 정지를 지워야 한다").
    farthest = max(positions)
    inherited: list[int] = []
    sid = _PSTYLE_ID.search(para)
    if sid:
        inherited += style_stops.get(sid.group(1), [])
    inherited += [int(pos) for val, pos in _STOP.findall(para) if val != "clear"]
    clears = "".join(f'<w:tab w:val="clear" w:pos="{p}"/>'
                     for p in sorted({p for p in inherited if p < farthest}))

    tabs = "<w:tabs>" + clears + "".join(stops) + "</w:tabs>"
    ppr = _PPR.search(out)
    if ppr is None:
        # pPr 이 없으면 만들어 문단 여는 태그 뒤에 넣는다.
        head = re.match(r"<w:p\b[^>]*>", out)
        if head is None:
            return out
        return out[:head.end()] + f"<w:pPr>{tabs}</w:pPr>" + out[head.end():]

    inner = ppr.group(1)
    if "<w:tabs>" in inner:
        # 이미 정지가 있으면 그 절 안에 clear 와 우리 정지를 앞세워 넣는다.
        # clear 를 빼먹으면 문단 자신의 낡은 정지에 탭이 걸린다.
        new_inner = inner.replace("<w:tabs>", "<w:tabs>" + clears + "".join(stops), 1)
    elif _PSTYLE_END.search(inner):
        new_inner = _PSTYLE_END.sub(r"\1" + tabs, inner, count=1)
    else:
        new_inner = tabs + inner
    return out[:ppr.start(1)] + new_inner + out[ppr.end(1):]


def rewrite_ptabs(src: Path, dest: Path) -> int:
    """src 를 dest 로 복사하며 머릿말·꼬리말의 w:ptab 을 바꾼다. 바꾼 개수를 돌려준다.

    바꿀 것이 없거나 쪽 규격을 못 읽으면 **그대로 복사**한다(0 을 돌려준다).
    """
    with zipfile.ZipFile(src) as zin:
        names = zin.namelist()
        if not any(_PART.match(n) for n in names):
            shutil.copyfile(src, dest)
            return 0
        try:
            doc = zin.read("word/document.xml").decode("utf-8", "ignore")
        except KeyError:
            shutil.copyfile(src, dest)
            return 0
        metrics = _page_metrics(doc)
        if metrics is None:
            shutil.copyfile(src, dest)
            return 0
        fallback_width, _left = metrics
        try:
            rels = zin.read("word/_rels/document.xml.rels").decode("utf-8", "ignore")
        except KeyError:
            rels = ""
        by_part = part_text_widths(doc, rels)
        try:
            style_stops = style_tab_stops(
                zin.read("word/styles.xml").decode("utf-8", "ignore"))
        except KeyError:
            style_stops = {}

        changed = 0
        parts: dict[str, bytes] = {}
        for name in names:
            if not _PART.match(name):
                continue
            xml = zin.read(name).decode("utf-8", "ignore")
            if "<w:ptab" not in xml:
                continue
            # 구역을 못 찾으면 문서 첫 구역의 폭으로 간다. 구역이 하나뿐인
            # 문서가 대부분이고, 그때는 이 값이 곧 맞는 값이다. 다만 폭이 다른
            # 구역 여럿이 이 파트를 쓰면(None) 손대지 않는다.
            if name in by_part and by_part[name] is None:
                continue
            text_width = by_part.get(name) or fallback_width
            fixed = _PARA.sub(
                lambda m: _fix_paragraph(m.group(0), text_width, style_stops), xml)
            if fixed != xml:
                changed += len(_PTAB.findall(xml)) - len(_PTAB.findall(fixed))
                parts[name] = fixed.encode("utf-8")

        if not parts:
            shutil.copyfile(src, dest)
            return 0

        # zip 을 다시 쓴다. 손댄 파트만 갈아끼우고 나머지는 바이트 그대로 옮긴다.
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                zout.writestr(item, parts.get(item.filename, zin.read(item.filename)))
    return changed
