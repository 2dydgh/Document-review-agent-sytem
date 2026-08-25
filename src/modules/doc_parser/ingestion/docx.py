"""DOCX(워드 2007+) 로더.

DOCX는 ZIP + OOXML XML이라 표준 라이브러리만으로 읽는다. (.doc은 OLE 바이너리라
별도 포맷이다 — .hwp와 같은 사정이다.)

내부 구조:
    word/document.xml   본문 (w:body > w:p | w:tbl)
    word/styles.xml     스타일 정의 (styleId -> 개요 수준)
    w:p(문단) > w:r(런) > w:t(텍스트)
    w:tbl > w:tr > w:tc > w:p   (표: 셀 안에 또 문단)

세 가지를 정확히 다뤄야 한다.

1. **런을 공백 없이 이어붙일 것.** 워드는 편집 이력(rsid) 때문에 한 단어를 런
   여러 개로 쪼갠다. "RQ-SFR" + "-PR-01" + "-001"처럼 갈라지므로, 런 사이에
   공백을 넣으면 요건 ID가 깨져 추적성 검사가 통째로 무너진다.

2. **삭제된 글자(w:delText)를 읽지 말 것.** 변경내용 추적이 켜진 문서에서
   w:delText는 지워진 글자다. 읽으면 문서에 없는 내용을 검토하게 된다.
   w:instrText(필드 코드)도 본문이 아니다.

3. **제목은 스타일 이름이 아니라 개요 수준이 안다.** styles.xml의 w:outlineLvl이
   근거다. 스타일 이름은 "제목 1"/"Heading 1"/"머리글 1"로 문서마다 다르다.
   문단에 직접 박힌 w:outlineLvl은 스타일보다 우선한다.

출력은 마크다운이다. normalize()가 `#` heading만 이해하기 때문이다.
표는 `| 셀 | 셀 |` 한 줄로 낸다 — hwpx.py와 같은 규약이다.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .base import RawDoc
from .images import image_size

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_MAX_HEADING_LEVEL = 6  # 마크다운은 ###### 까지

# 본문이 아닌 텍스트. 통째로 건너뛴다.
_SKIP = frozenset({"delText", "instrText"})
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_RELS = "word/_rels/document.xml.rels"


def _tag(elem: ET.Element) -> str:
    return elem.tag.rsplit("}", 1)[-1]


def _outline_levels(styles: ET.Element) -> dict[str, int]:
    """{styleId: 개요 수준(0부터)}. outlineLvl이 있는 스타일만 제목으로 본다."""
    levels: dict[str, int] = {}
    for style in styles.iter(f"{_W}style"):
        style_id = style.get(f"{_W}styleId")
        if style_id is None:
            continue
        level = _outline_level(style.find(f"{_W}pPr"))
        if level is not None:
            levels[style_id] = level
    return levels


def _outline_level(para_pr: ET.Element | None) -> int | None:
    if para_pr is None:
        return None
    node = para_pr.find(f"{_W}outlineLvl")
    if node is None:
        return None
    try:
        return int(node.get(f"{_W}val", ""))
    except ValueError:
        return None


def _paragraph_level(para: ET.Element, levels: dict[str, int]) -> int | None:
    """문단의 개요 수준. 직접 지정이 스타일을 이긴다."""
    para_pr = para.find(f"{_W}pPr")
    direct = _outline_level(para_pr)
    if direct is not None:
        return direct
    if para_pr is None:
        return None
    style = para_pr.find(f"{_W}pStyle")
    if style is None:
        return None
    return levels.get(style.get(f"{_W}val", ""))


def _paragraph_text(para: ET.Element) -> tuple[str, list[ET.Element]]:
    """문단의 텍스트와 그 안의 그림. 런은 공백 없이 잇는다.

    그림(w:drawing)은 문단 안에 인라인으로 들어 있어 여기서 걷으면 **문서상 위치가
    보존된다.** 그림 안으로는 내려가지 않는다 — 도형 글상자(w:txbxContent)의 글자는
    이미 본문으로 읽고 있으므로, 내려가면 그것이 두 번 들어간다.
    """
    parts: list[str] = []
    drawings: list[ET.Element] = []

    def walk(node: ET.Element) -> None:
        for child in node:
            name = _tag(child)
            if name == "tbl" or name in _SKIP:
                continue  # 표는 따로 렌더하고, 삭제된 글자는 본문이 아니다
            if name == "t":
                parts.append(child.text or "")
            elif name in ("tab", "br"):
                parts.append(" ")
            elif name == "drawing":
                drawings.append(child)
                walk(child)      # 도형 글상자의 글자는 본문이다
            else:
                walk(child)

    walk(para)
    return "".join(parts).strip(), drawings


def _rel_targets(archive: zipfile.ZipFile) -> dict[str, str]:
    """{rId: ZIP 내부 경로}. w:drawing 은 rId 만 들고 실제 경로는 rels 에 있다."""
    try:
        rels = ET.fromstring(archive.read(_RELS))
    except (KeyError, ET.ParseError):
        return {}
    out = {}
    for rel in rels.iter(f"{_PR}Relationship"):
        target = rel.get("Target", "")
        if "media/" in target:
            out[rel.get("Id")] = "word/" + target.lstrip("/")
    return out


def _note_drawing(drawing: ET.Element, images: list[dict],
                  targets: dict[str, str],
                  sizes: dict[str, tuple[int, int]] | None = None) -> str:
    """그림 하나를 기록하고 본문에 넣을 자리표시를 돌려준다. 그림이 아니면 빈 문자열.

    워드는 이름("그림 11")과 대체텍스트를 붙여 둔다. 자동 생성된 설명이라 품질은
    낮지만("텍스트이(가) 표시된 사진"), 그림이 무엇에 관한 것인지 짐작할 근거는 된다.
    없으면 번호만 남긴다 — 없는 설명을 지어내지 않는다.

    w:drawing 에는 실제 이미지가 없는 것도 온다(도형·글상자: "직사각형 10"). 그런
    것은 세지 않는다 — 도형 안의 글자는 이미 본문으로 읽고 있으므로 "그림"으로
    또 세면 개수만 부풀고, 비전 모델에 보낼 바이트도 없다.
    """
    name = alt = rid = ""
    for node in drawing.iter():
        if node.tag == f"{_WP}docPr":
            name = (node.get("name") or "").strip()
            alt = (node.get("descr") or "").strip()
        rid = node.get(f"{_R}embed") or rid

    part = targets.get(rid, "")
    if not part:
        return ""

    # 워드가 대체텍스트에 줄바꿈을 넣는다("…사진\n\n자동 생성된 설명").
    alt = " ".join(alt.split())
    no = len(images) + 1
    w, h = (sizes or {}).get(part, (0, 0))
    images.append({"no": no, "name": name, "alt": alt, "part": part,
                   "width": w, "height": h})
    return f"[그림 {no}: {alt}]" if alt else f"[그림 {no}]"


def _cell_text(cell: ET.Element, images: list[dict], targets: dict[str, str],
               sizes: dict | None = None) -> str:
    """셀 하나를 한 줄 텍스트로. 셀 안의 표는 평탄화한다."""
    lines: list[str] = []
    _emit(cell, lines, levels={}, in_table=True, images=images, targets=targets,
          sizes=sizes)
    return " ".join(line.strip() for line in lines if line.strip())


def _unwrap(node: ET.Element) -> list[ET.Element]:
    """직접 자식. 단 w:sdt(콘텐츠 컨트롤)는 벗겨 그 안을 내놓는다.

    워드 양식 문서는 값 칸이나 행을 w:sdt 로 감싼다. 감싼 것을 그냥 직접 자식으로
    보면 그 셀·행이 통째로 사라진다 — 실문서(시험성적서 갑지)의 w:tr 직접 자식이
    [trPr, tc(라벨), sdt(값)] 이라 기관명·대표자·주소·시험대상품목의 **값이**
    없어졌다. 라벨만 남으면 "필드가 비었다"는 거짓 지적이 된다.

    sdt 는 중첩될 수 있어 재귀로 벗긴다.
    """
    out: list[ET.Element] = []
    for child in node:
        if _tag(child) == "sdt":
            content = child.find(f"{_W}sdtContent")
            if content is not None:
                out.extend(_unwrap(content))
        else:
            out.append(child)
    return out


def _font_sizes(node: ET.Element) -> dict[float, int]:
    """이 가지 안에서 **직접 적힌** 글꼴 크기 → 몇 글자에 쓰였나.

    워드는 대부분의 글자에 크기를 안 적는다 — 문단 스타일이 정하고, 그 스타일은
    styles.xml 에 있다. 실측(시험 설계서): 런 405개 중 크기가 적힌 것은 23개다.
    그래서 여기서 세는 것은 "이 문서의 글꼴"이 아니라 **"스타일을 벗어나 직접
    박아둔 글꼴"** 이다. 그 구분을 검사기가 알아야 한다.

    다행히 그게 검사 대상과 겹친다. 실측에서 8pt 22개가 전부 테스트케이스였다 —
    본문은 스타일에 맡기고 테스트케이스만 직접 박는다. 상속 사슬(docDefaults →
    스타일 → 문단 → 런)과 theme 해석 없이도 문서 간 md 가 요구하는 검사는 된다.
    """
    out: dict[float, int] = {}
    for run in node.iter(_W + "r"):
        pr = run.find(_W + "rPr")
        sz = pr.find(_W + "sz") if pr is not None else None
        val = sz.get(_W + "val") if sz is not None else None
        if not val:
            continue
        chars = sum(len(t.text or "") for t in run.iter(_W + "t"))
        if chars:
            out[int(val) / 2] = out.get(int(val) / 2, 0) + chars
    return out


def _emit_table(table: ET.Element, out: list[str], images: list[dict],
                targets: dict[str, str], sizes: dict | None = None,
                tables: list[dict] | None = None) -> None:
    head: list[str] = []
    for row in _unwrap(table):
        if _tag(row) != "tr":
            continue
        cells = [_cell_text(c, images, targets, sizes)
                 for c in _unwrap(row) if _tag(c) == "tc"]
        if any(cells):
            if not head:
                head = [c.strip() for c in cells]
            # 파이프로 셀을 잇는다. 셀 안의 파이프는 깨지지 않게 치환.
            out.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    if tables is not None and head:
        # 첫 행을 머리행으로 본다 — 표를 특정하는 근거가 그것뿐이다(table_rows 와
        # 같은 규약). 크기가 하나도 안 적힌 표는 담지 않는다: 담아 두면 검사기가
        # "다 스타일대로다" 와 "볼 게 없다" 를 구분 못 한다.
        found = _font_sizes(table)
        if found:
            tables.append({"columns": head, "fontSizes": found})
    out.append("")


def _emit(node: ET.Element, out: list[str], levels: dict[str, int],
          in_table: bool = False, images: list[dict] | None = None,
          targets: dict[str, str] | None = None,
          sizes: dict | None = None,
          tables: list[dict] | None = None) -> None:
    images = images if images is not None else []
    targets = targets if targets is not None else {}
    for child in node:
        name = _tag(child)
        if name == "p":
            text, drawings = _paragraph_text(child)
            marks = [m for m in (_note_drawing(d, images, targets, sizes)
                                 for d in drawings) if m]
            if not text and not marks:
                continue
            if text:
                level = _paragraph_level(child, levels)
                if level is not None and not in_table:
                    depth = min(level + 1, _MAX_HEADING_LEVEL)
                    out.append("")
                    out.append("#" * depth + " " + text)
                else:
                    out.append(text)
            # 그림 자리표시는 별도 줄로 낸다 — 제목 줄에 섞이면 제목이 오염된다.
            out.extend(marks)
        elif name == "tbl":
            _emit_table(child, out, images, targets, sizes, tables)
        else:
            _emit(child, out, levels, in_table, images, targets, sizes, tables)


class DocxLoader:
    extensions = (".docx",)

    def load(self, path: Path) -> RawDoc:
        path = Path(path)
        try:
            archive = zipfile.ZipFile(path)
        except zipfile.BadZipFile as exc:
            raise ValueError(f"DOCX가 아닌 것 같습니다 (ZIP이 아님): {path.name}") from exc

        with archive:
            try:
                document = ET.fromstring(archive.read("word/document.xml"))
            except KeyError as exc:
                raise ValueError(
                    f"DOCX 본문(word/document.xml)이 없습니다: {path.name}") from exc

            try:
                styles = ET.fromstring(archive.read("word/styles.xml"))
                levels = _outline_levels(styles)
            except (KeyError, ET.ParseError):
                levels = {}  # 제목 정보가 없으면 전부 본문으로 취급한다

            targets = _rel_targets(archive)
            # 그림 크기는 뷰어용 PDF 안의 이미지와 짝짓는 열쇠다. 아카이브가
            # 이미 열려 있으니 여기서 읽는다 — 바이트는 버리고 크기만 남긴다.
            sizes = {}
            for part in set(targets.values()):
                try:
                    size = image_size(archive.read(part))
                except KeyError:
                    continue          # rels 가 가리키는 파일이 없을 수 있다
                if size:
                    sizes[part] = size
            lines: list[str] = []
            images: list[dict] = []
            tables: list[dict] = []
            _emit(document, lines, levels, images=images, targets=targets,
                  sizes=sizes, tables=tables)

        text = "\n".join(lines)
        # images 는 본문의 `[그림 N]` 자리표시와 같은 번호로 이어진다. part 는 ZIP
        # 내부 경로다 — 바이트를 meta 에 담지 않는다(RawDoc 은 JSON 직렬화 가능해야
        # 한다). 그림을 읽어야 하는 쪽이 source_path 로 ZIP 을 다시 열면 된다.
        return RawDoc(source_path=str(path), text=text,
                      meta={"format": "docx", "images": images, "tables": tables})
