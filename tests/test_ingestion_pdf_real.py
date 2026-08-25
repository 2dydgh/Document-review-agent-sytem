"""실문서로 재는 회귀 테스트.

data/ 는 gitignore 되어 있다(고객 문서). 없으면 전부 skip 하고, 있는 기계에서만
진짜 문서로 검증한다. 여기서 쓰는 쪽 번호는 **본문 기준**(PDF 뷰어에 보이는 수).

905쪽을 읽으므로 2~3분 걸린다. 빠른 루프에서는 `pytest -m "not slow"` 로 뺀다.
"""
import contextlib

import pytest

pytest.importorskip("pdfplumber")

pytestmark = pytest.mark.slow

from modules.doc_parser import PdfDigitalLoader  # noqa: E402
from modules.doc_parser.ingestion.pdf_labels import cluster_chars, render_lines  # noqa: E402
from modules.doc_parser.ingestion.pdf_tables import usable_tables  # noqa: E402

from conftest import sample  # noqa: E402

SRS_NAME = "SHN34_ESF-CCS_SRS.pdf"
SRS = sample(SRS_NAME)


@contextlib.contextmanager
def _page(path, index):
    """실문서 한 쪽을 연다. 파일이 없으면 skip."""
    import pdfplumber
    if path is None or not path.exists():
        pytest.skip("실문서 없음 (data/ 는 커밋되지 않는다)")
    with pdfplumber.open(path) as doc:
        yield doc.pages[index]


@pytest.fixture(scope="module")
def srs():
    """236쪽을 한 번만 읽는다 — 40초 걸린다."""
    if SRS is None:
        pytest.skip(f"{SRS_NAME} 없음 (data/ 는 커밋되지 않는다)")
    return PdfDigitalLoader().load(SRS)


def test_signal_table_row_is_one_line(srs):
    """본문 108쪽. pypdf 는 이 행을 5줄로 파열시켰다."""
    assert ("6 | MSIS local manual reset status | GC A/B | MTP A/B | Bool | Not Reset/ Reset"
            in srs.text)


def test_memory_table_keeps_row_order(srs):
    """본문 23쪽, 31행 4열 단순 표."""
    body = srs.text
    assert "%MX0 | BOOL | 4096 | pSET-II" in body
    assert body.index("%MX0 | BOOL | 4096 | pSET-II") < body.index("%MW1 | WORD | 12032 | Processor")


def test_diagram_labels_are_recovered(srs):
    """본문 17쪽. 줄 단위로 읽으면 'A D M c i t a v...' 로 뭉개지던 것."""
    body = srs.text
    for label in ("Diverse", "Minimum Inventory", "DCN-Q (PEDL)"):
        assert label in body, f"{label!r} 이 복원되지 않았다"


def test_meta_counts_are_real(srs):
    assert srs.meta["pages"] == 236
    assert len(srs.meta["tables"]) > 100
    assert srs.meta["bookmarks"] > 300


def test_표마다_글꼴_크기를_들고_나온다(srs):
    """PDF 도 표 글꼴을 읽는다. Word 만 읽던 것을 맞췄다.

    팀 기준(AI시험인증1팀)이 `font_sizes: [8, 9]` 로 테스트케이스 글꼴을 정해두는데,
    PDF 로 올리면 그 검사가 아예 못 돌았다 — 파서가 표 **개수**만 남겼기 때문이다.
    Word 는 대부분의 글자가 크기를 안 갖고 스타일에서 물려받아 직접 박은 것만
    보이지만, PDF 는 종이에 찍힌 실제 크기가 글자마다 있다.
    """
    tables = srs.meta["tables"]
    with_sizes = [t for t in tables if t["fontSizes"]]
    assert len(with_sizes) > 100, "표는 잡았는데 글꼴을 못 읽었다"
    # 크기는 pt 숫자, 값은 글자 수. 표 글꼴 검사가 이 모양을 읽는다.
    sizes = {s for t in with_sizes for s in t["fontSizes"]}
    assert all(isinstance(s, float) and 3 < s < 40 for s in sizes), sorted(sizes)
    assert any(t["columns"] for t in tables), "머리행을 하나도 못 읽었다"


def test_fake_single_column_table_is_filtered():
    """본문 17쪽에서 잡히는 13x64pt 1열 오검출을 표로 쓰지 않는다."""
    with _page(SRS, 16) as page:
        assert all(len(t.columns) >= 2 for t in usable_tables(page))


def test_clustering_is_lossless_on_prose():
    """본문 10쪽(줄글). 글자를 하나도 잃지 않아야 한다 — 이 모듈의 핵심 계약."""
    with _page(SRS, 9) as page:
        boxes = [t.bbox for t in usable_tables(page)]

        def outside(obj):
            cx = (obj["x0"] + obj["x1"]) / 2
            cy = (obj["top"] + obj["bottom"]) / 2
            return not any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in boxes)

        sub = page.filter(outside)
        plain = "".join((sub.extract_text() or "").split())
        clustered = "".join("".join(render_lines(cluster_chars(sub.chars))).split())
        assert sorted(clustered) == sorted(plain)


@pytest.mark.parametrize("name", [
    "SHN34_ESF-CCS_SRS.pdf",
    "SHN34_ESF-CCS_RVVR.pdf",
    "SKN56 CPS_SRS.pdf",
    "SKN56_CDMS_RVVR_Rev05.pdf",
    "SKN56_CPS_RVVR_Rev09.pdf",
    "IS16-CHK-0000(내부검토_체크리스트).pdf",
])
def test_every_real_document_loads(name):
    path = sample(name)
    if path is None:
        pytest.skip(f"{name} 없음 (data/ 는 커밋되지 않는다)")
    raw = PdfDigitalLoader().load(path)
    assert raw.text.strip()
    assert raw.meta["pages"] > 0


# ── 표 셀에서 글자가 깨지지 않는다 ──────────────────────────────────────────
# 실문서에서만 드러나는 증상이다. 손으로 재던 것을 관문으로 옮긴다 — 파서를 다시
# 만졌을 때 되살아나면 여기서 걸린다.
#
# 두 원인을 잡았다(2026-08-06):
#   ① 셀 안 줄바꿈을 무조건 공백으로 접어 잘린 단어가 갈라졌다
#      `Communication`→`Communicati on` · `Backup`→`Ba ckup` · `구현하여`→`구 현하여`
#   ② 한글·영문의 기준선이 0.2pt 달라 한 줄이 둘로 갈렸다
#      갈린 둘을 위→아래로 이어 붙여 `CDMS에서 통신`이 `에서통신CDMS`가 됐다
#
# 검토자에게는 문서 오탈자로 보이지만 문서는 멀쩡하다. 우리가 깨뜨린 것을 지적으로
# 올리는 것이라 결과 신뢰도를 직접 깎는다.

_ALL_DOCS = [
    "SHN34_ESF-CCS_SRS.pdf",
    "SHN34_ESF-CCS_RVVR.pdf",
    "SKN56 CPS_SRS.pdf",
    "SKN56_CDMS_RVVR_Rev05.pdf",
    "SKN56_CPS_RVVR_Rev09.pdf",
    "IS16-CHK-0000(내부검토_체크리스트).pdf",
]

# 어떤 문서에도 있으면 안 되는 것들. 전부 파서가 만들어내던 글자다.
_BROKEN = [
    "Ba ckup", "구 현", "를구현하여제공", "에서통신CDMS", "설정Server",
    # 실문서에는 공백이 있다. 같은 시각적 줄의 PDF text-line 조각을
    # 먼저 합친 뒤 줄 끝 공백을 문자열로 찾으면 신호를 놓쳐 붙어 버린다.
    "softwarerequirements", "providesinformation", "managingchanges", "andmanaging",
    "accuratelyspecified", "tosoftware",
]


def _text(name):
    path = sample(name)
    if path is None:
        pytest.skip(f"{name} 없음 (data/ 는 커밋되지 않는다)")
    return PdfDigitalLoader().load(path).text


@pytest.mark.parametrize("name", _ALL_DOCS)
def test_표_셀에서_단어가_갈라지지_않는다(name):
    text = _text(name)
    for bad in _BROKEN:
        assert bad not in text, f"{name}: {bad!r} 가 다시 나온다"


# `Communicati` 뒤에 `on` 이 안 오는 경우. 남은 것은 **열 경계** 문제라 원인이 다르다 —
# 한 셀에 `Communicati`, 옆 셀에 `on` 이 들어간다. 이 파일은 legacy
# PdfDigitalLoader의 계약을 검사하므로 기존 기준선을 유지한다. 기본 trkim
# 경로의 0건 계약은 test_parser_contract.py에서 별도로 지킨다.
_COMMUNICATI_BASELINE = {"SKN56_CDMS_RVVR_Rev05.pdf": 3}


@pytest.mark.parametrize("name", _ALL_DOCS)
def test_열_경계로_갈린_단어가_늘지_않는다(name):
    import re
    n = len(re.findall(r"Communicati(?!on)", _text(name)))
    cap = _COMMUNICATI_BASELINE.get(name, 0)
    assert n <= cap, f"{name}: {n}건 (기준선 {cap}). 줄이는 것이 목표다"
