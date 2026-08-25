"""디지털 PDF 로더 (텍스트 레이어가 있는 PDF).

본문은 pdfplumber 로 읽는다. pypdf 의 extract_text() 는 셀 안에 줄바꿈이 있는
표에서 한 행을 3~5줄로 파열시키는데, 이 문서들은 표 안 글자가 54~88% 다
(SHN34 SRS 71.5%, RVVR 88.4%). 대가는 236쪽 17초 → 41초인데, AI 검토가
1분 남짓이라 묻힌다.

책갈피(outline)만 pypdf 로 읽는다 — pdfplumber 에는 그 API 가 없다.
파일을 두 번 여는 값을 치르지만, 380개 책갈피를 순서·계층 지켜 심는
_apply_outline 을 버릴 이유가 없다. 암호 걸린 PDF 판정도 pypdf 쪽이다.

스캔본(이미지만 있는 PDF)은 여기서 처리하지 못한다. 텍스트가 한 글자도 안 나오면
조용히 빈 문서를 돌려주는 대신 크게 실패한다 — 빈 문서는 "지적사항 없음"으로
읽히고, 그건 검토 도구가 낼 수 있는 최악의 거짓말이다.

PDF에는 마크다운 제목이 없어 섹션 트리를 만들 수 없다. 대신 페이지 경계를
폼피드로 표시해 normalize()가 Anchor.page를 채우게 한다. 지적사항의 위치가
"몇 쪽"으로 나오는 편이 아무 위치도 없는 것보다 훨씬 쓸모 있다.
"""
from __future__ import annotations

from pathlib import Path

from .base import RawDoc
from .pdf_labels import cluster_chars, render_lines
from .pdf_layout import split_bands
from .pdf_tables import render_table, table_meta, usable_tables

PAGE_BREAK = "\f"


_MAX_LEVEL = 6  # 마크다운은 ###### 까지


def _outline_marks(reader) -> dict[int, list[tuple[int, str]]]:
    """책갈피 → {쪽 인덱스: [(깊이, 제목), …]}. 문서 순서를 유지한다.

    깨진 책갈피 하나가 문서 전체를 못 읽게 만들면 안 된다 — 목적지를 못 푸는
    항목은 건너뛴다. 실무 PDF는 쪽을 수동 교체하다 목적지가 깨지는 일이 있고,
    내부검토 체크리스트도 그걸 점검 항목으로 두고 있다.
    """
    try:
        outline = reader.outline
    except Exception:  # noqa: BLE001 — 책갈피가 깨져도 본문은 읽어야 한다
        return {}

    marks: dict[int, list[tuple[int, str]]] = {}

    def walk(items, depth: int) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, depth + 1)
                continue
            title = str(getattr(item, "title", "") or "").strip()
            if not title:
                continue
            try:
                pno = reader.get_destination_page_number(item)
            except Exception:  # noqa: BLE001 — 목적지가 깨진 책갈피
                continue
            marks.setdefault(pno, []).append((depth, title))

    try:
        walk(outline, 1)
    except Exception:  # noqa: BLE001
        return {}
    return marks


def _squash(text: str) -> str:
    return "".join(str(text or "").split())


def _apply_outline(pages: list[str],
                   marks: dict[int, list[tuple[int, str]]]) -> list[str]:
    """책갈피 제목을 마크다운 heading 으로 본문에 심는다.

    제목이 그 쪽 본문에 실제로 찍혀 있으면 **그 줄 자리에서** heading 으로
    바꾼다. 쪽 맨 위에 몰아 넣으면 제목 앞에 있던 본문(앞 절의 꼬리)까지
    새 절로 딸려 들어간다 — 실문서는 한 쪽에 책갈피가 여러 개다(SHN34 는
    236쪽에 380개).

    본문에서 그 줄을 못 찾으면 **직전 책갈피 바로 뒤에** 끼운다. 쪽 맨 위로
    몰면 자식이 부모보다 앞서게 된다(1.1 이 1.0 위로 올라가 트리가 뒤집힌다).
    책갈피는 있는데 제목이 본문에 안 찍힌 경우(표지·목차·이미지 제목)라도
    순서와 계층은 지켜야 한다.
    """
    out = list(pages)
    for pno, items in marks.items():
        # pno None 가드(수정 2026-08-06): pypdf 는 대상 페이지를 해석 못 한 책갈피
        # (깨진 링크·외부 문서 참조)의 페이지 번호를 None 으로 준다 — 비교 연산에서
        # TypeError 로 문서 전체 파싱이 죽던 실측 크래시(Tyre Wear PDF).
        if pno is None or not 0 <= pno < len(out):
            continue
        lines = out[pno].split("\n")
        cursor = 0  # 여기서부터 찾는다 — 책갈피 순서를 거스르지 않기 위해
        for depth, title in items:
            head = "#" * min(depth, _MAX_LEVEL) + " " + title
            key = _squash(title)
            at = None
            for i in range(cursor, len(lines)):
                # 공백을 무시하고 맞춘다. PDF 추출은 자간 때문에 같은 낱말이
                # 여러 조각으로 나와 원문과 글자 수가 어긋나는 일이 흔하다.
                if key and _squash(lines[i]) == key:
                    at = i
                    break
            if at is None:
                lines.insert(cursor, head)
                cursor += 1
            else:
                lines[at] = head
                cursor = at + 1
        out[pno] = "\n".join(lines)
    return out


def _band_lines(page, band: dict, tables: list) -> list[str]:
    """밴드 하나를 줄 목록으로. 표면 행 단위, 본문이면 좌표 군집."""
    if band["kind"] == "table":
        try:
            return render_table(page, tables[band["index"]])
        except Exception:  # noqa: BLE001 — 표 하나가 문서를 못 읽게 만들면 안 된다
            pass  # 아래 본문 처리로 떨어진다
    top = max(band["top"], 0.0)
    bottom = min(band["bottom"], page.height)
    if bottom - top <= 0:
        return []
    crop = page.crop((0, top, page.width, bottom))
    return render_lines(cluster_chars(crop.chars))


def _page_lines(page) -> tuple[list[str], list[dict]]:
    """쪽 하나를 줄 목록으로. (줄들, 표마다의 요약)"""
    tables = usable_tables(page)
    spans = [(t.bbox[1], t.bbox[3]) for t in tables]
    lines: list[str] = []
    for band in split_bands(page.height, spans):
        lines.extend(_band_lines(page, band, tables))
    return lines, [table_meta(page, t) for t in tables]


class PdfDigitalLoader:
    extensions = (".pdf",)

    def load(self, path: Path) -> RawDoc:
        import pdfplumber
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        path = Path(path)
        try:
            reader = PdfReader(path)
        except PdfReadError as exc:
            raise ValueError(f"PDF를 읽을 수 없습니다: {path.name} ({exc})") from exc

        if reader.is_encrypted:
            # 빈 암호로 열리는 경우가 흔하다 (인쇄 제한만 걸린 문서).
            try:
                opened = reader.decrypt("")
            except Exception as exc:  # noqa: BLE001 - pypdf가 여러 예외를 던진다
                raise ValueError(f"암호가 걸린 PDF입니다: {path.name}") from exc
            if not opened:
                raise ValueError(f"암호가 걸린 PDF입니다: {path.name}")

        pages: list[str] = []
        tables: list[dict] = []
        with pdfplumber.open(path) as doc:
            for page in doc.pages:
                lines, metas = _page_lines(page)
                tables.extend(metas)
                pages.append("\n".join(lines).strip())
                # 236쪽을 통째로 들고 있지 않는다.
                page.flush_cache()
                page.get_textmap.cache_clear()

        if not any(pages):
            raise NotImplementedError(
                f"'{path.name}'에서 텍스트를 찾지 못했습니다. 스캔본(이미지) PDF로 "
                "보입니다 — OCR 로더는 아직 구현되지 않았습니다.")

        marks = _outline_marks(reader)
        if marks:
            pages = _apply_outline(pages, marks)

        text = f"\n{PAGE_BREAK}\n".join(pages)
        return RawDoc(source_path=str(path), text=text,
                      meta={"format": "pdf", "pages": len(pages), "tables": tables,
                            "bookmarks": sum(len(v) for v in marks.values())})
