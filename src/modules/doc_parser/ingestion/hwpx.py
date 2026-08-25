"""HWPX(한글 2014+) 로더.

HWPX는 ZIP + OWPML XML이라 표준 라이브러리만으로 읽는다.
(구형 .hwp는 OLE 바이너리라 별도 구현이 필요하다 — hwp.py 참고)

내부 구조:
    Contents/section0.xml ...  본문 (섹션별로 분리)
    Contents/header.xml        스타일/문단모양 정의
    hp:p(문단) > hp:run > hp:t(텍스트)
    hp:tbl > hp:tr > hp:tc > hp:subList > hp:p   (표: 셀 안에 또 문단)

두 가지를 정확히 다뤄야 한다.

1. **표를 문단에 합치지 말 것.** 표는 `hp:p` 안에 중첩되므로 `p.iter(hp:t)`로
   긁으면 셀 텍스트가 바깥 문단에 붙는다. 실제로 "ID"와 "RQ-SFR-..."이 이어붙어
   "IDRQ-SFR-..."가 됐다. 요구사항이 표에 들어 있는 문서에서는 치명적이다.

2. **제목은 스타일이 아니라 문단모양이 안다.** header.xml의 `hh:paraPr` 중
   `hh:heading[@type="OUTLINE"]`인 것의 `level`이 개요 수준이다. BULLET/NUMBER는
   목록이지 제목이 아니다.

출력은 마크다운이다. normalize()가 `#` heading만 이해하기 때문이다.
표는 `| 셀 | 셀 |` 한 줄로 낸다 — 요건 ID와 설명이 같은 줄에 오게 하려는 것이다
(내용 대조가 줄 단위로 동작한다).
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .base import RawDoc
from .images import image_size

_HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
_HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
_SECTION = re.compile(r"Contents/section\d+\.xml$")
_OPF = "{http://www.idpf.org/2007/opf/}"
_MANIFEST = "Contents/content.hpf"

_MAX_HEADING_LEVEL = 6  # 마크다운은 ###### 까지


def _tag(elem: ET.Element) -> str:
    return elem.tag.rsplit("}", 1)[-1]


def _outline_levels(header: ET.Element) -> dict[str, int]:
    """{paraPr id: 개요 수준(0부터)}. OUTLINE만 제목으로 본다."""
    levels: dict[str, int] = {}
    for para_pr in header.iter(f"{_HH}paraPr"):
        heading = para_pr.find(f"{_HH}heading")
        if heading is None or heading.get("type") != "OUTLINE":
            continue
        pr_id = para_pr.get("id")
        try:
            levels[pr_id] = int(heading.get("level", "0"))
        except (TypeError, ValueError):
            continue
    return levels


def _split_paragraph(para: ET.Element) -> tuple[str, list[ET.Element], list[ET.Element]]:
    """문단의 직접 텍스트와, 그 안에 박힌 표·그림을 분리한다.

    표 안으로는 내려가지 않는다. 표는 따로 렌더한다.

    그림은 문단 안에 인라인으로 들어 있어 여기서 걷으면 **문서상 위치가 보존된다.**
    그림 안의 내용은 아직 읽지 못하지만(비전 모델이 할 일), 그림이 있었다는 사실은
    남겨야 한다 — 지금까지는 흔적조차 없어서 검토 Agent 에게 그 자리가 빈 곳이었다.
    """
    parts: list[str] = []
    tables: list[ET.Element] = []
    pics: list[ET.Element] = []

    def walk(node: ET.Element) -> None:
        for child in node:
            name = _tag(child)
            if name == "tbl":
                tables.append(child)
            elif name == "t":
                parts.append(child.text or "")
            elif name == "pic":
                pics.append(child)
            else:
                walk(child)

    walk(para)
    return "".join(parts).strip(), tables, pics


def _manifest_parts(archive: zipfile.ZipFile) -> dict[str, str]:
    """{binaryItemIDRef: ZIP 내부 경로}. hp:pic 은 id 만 들고 실제 경로는 여기 있다."""
    try:
        pkg = ET.fromstring(archive.read(_MANIFEST))
    except (KeyError, ET.ParseError):
        return {}
    return {item.get("id"): item.get("href")
            for item in pkg.iter(f"{_OPF}item")
            if item.get("id") and item.get("href", "").startswith("BinData/")}


def _note_pic(pic: ET.Element, images: list[dict], parts: dict[str, str],
              sizes: dict[str, tuple[int, int]] | None = None) -> str:
    """그림 하나를 기록하고 본문에 넣을 자리표시를 돌려준다.

    hwpx 에는 대체텍스트가 없다(한컴이 넣지 않는다). 그래서 번호만 남는다 —
    없는 설명을 지어내지 않는다. docx 는 이름·설명이 있어 더 낸다(docx.py 참고).
    """
    ref = ""
    for node in pic.iter():
        ref = node.get("binaryItemIDRef") or ref
    no = len(images) + 1
    part = parts.get(ref, "")
    w, h = (sizes or {}).get(part, (0, 0))
    images.append({"no": no, "name": "", "alt": "", "part": part,
                   "width": w, "height": h})
    return f"[그림 {no}]"


def _cell_text(cell: ET.Element, images: list[dict], parts: dict[str, str],
               sizes: dict | None = None) -> str:
    """셀 하나를 한 줄 텍스트로. 셀 안의 표는 평탄화한다."""
    lines: list[str] = []
    _emit(cell, lines, levels={}, in_table=True, images=images, parts=parts,
          sizes=sizes)
    return " ".join(line.strip() for line in lines if line.strip())


def _emit_table(table: ET.Element, out: list[str], images: list[dict],
                parts: dict[str, str], sizes: dict | None = None) -> None:
    for row in table:
        if _tag(row) != "tr":
            continue
        cells = [_cell_text(c, images, parts, sizes) for c in row if _tag(c) == "tc"]
        if any(cells):
            # 파이프로 셀을 잇는다. 셀 안의 파이프는 깨지지 않게 치환.
            out.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    out.append("")


def _emit(node: ET.Element, out: list[str], levels: dict[str, int],
          in_table: bool = False, images: list[dict] | None = None,
          parts: dict[str, str] | None = None,
          sizes: dict | None = None) -> None:
    images = images if images is not None else []
    parts = parts if parts is not None else {}
    for child in node:
        name = _tag(child)
        if name == "p":
            text, tables, pics = _split_paragraph(child)
            # 그림 자리표시는 그 문단 텍스트 뒤에 붙인다 — 문단이 제목이면 제목
            # 줄에 섞이지 않도록 별도 줄로 낸다.
            marks = [_note_pic(pic, images, parts, sizes) for pic in pics]
            if text:
                level = levels.get(child.get("paraPrIDRef"))
                if level is not None and not in_table:
                    depth = min(level + 1, _MAX_HEADING_LEVEL)
                    out.append("")
                    out.append("#" * depth + " " + text)
                else:
                    out.append(text)
            out.extend(marks)
            for table in tables:
                _emit_table(table, out, images, parts, sizes)
        elif name == "tbl":
            _emit_table(child, out, images, parts, sizes)
        else:
            _emit(child, out, levels, in_table, images, parts, sizes)


class HwpxLoader:
    extensions = (".hwpx",)

    def load(self, path: Path) -> RawDoc:
        path = Path(path)
        try:
            archive = zipfile.ZipFile(path)
        except zipfile.BadZipFile as exc:
            raise ValueError(f"HWPX가 아닌 것 같습니다 (ZIP이 아님): {path.name}") from exc

        with archive:
            names = sorted(n for n in archive.namelist() if _SECTION.search(n))
            if not names:
                raise ValueError(
                    f"HWPX 본문(Contents/section*.xml)이 없습니다: {path.name}")
            try:
                header = ET.fromstring(archive.read("Contents/header.xml"))
                levels = _outline_levels(header)
            except (KeyError, ET.ParseError):
                levels = {}  # 제목 정보가 없으면 전부 본문으로 취급한다

            parts = _manifest_parts(archive)
            # 그림 크기는 뷰어용 PDF 안의 이미지와 짝짓는 열쇠다. 아카이브가
            # 이미 열려 있으니 여기서 읽는다 — 바이트는 버리고 크기만 남긴다.
            sizes = {}
            for part in set(parts.values()):
                size = image_size(archive.read(part))
                if size:
                    sizes[part] = size
            lines: list[str] = []
            images: list[dict] = []
            for name in names:
                _emit(ET.fromstring(archive.read(name)), lines, levels,
                      images=images, parts=parts, sizes=sizes)

        text = "\n".join(lines)
        # images 는 본문의 `[그림 N]` 자리표시와 같은 번호로 이어진다. part 는 ZIP
        # 내부 경로다 — 바이트를 meta 에 담지 않는다(RawDoc 은 JSON 직렬화 가능해야
        # 한다). 그림을 읽어야 하는 쪽이 source_path 로 ZIP 을 다시 열면 된다.
        return RawDoc(source_path=str(path), text=text,
                      meta={"format": "hwpx", "sections": len(names),
                            "images": images})
