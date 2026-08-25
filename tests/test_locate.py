"""인용문이 PDF의 어디에 있나 — 굽지 않고 좌표만 돌려주는 경로.

화면 뷰어가 지적 위치로 점프하고 형광펜을 얹으려면 이 좌표가 필요하다. 예전에는
annotate가 좌표를 알고도 PDF 안에만 남겨서, 화면은 체커가 주장한 쪽으로 갔다.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from pypdf import PdfReader

from modules.report import annotate, locate

pytest.importorskip("pdfplumber")

PDF = Path(__file__).parent / "data" / "probe.pdf"
pytestmark = pytest.mark.skipif(not PDF.exists(), reason="시험용 PDF 없음")

QUOTE_3 = "RQ-SFR-PR-01-001 예측  응답시간은  3 초  이내여야  한다 ."
QUOTE_5 = "RQ-SFR-PR-01-001 예측  응답시간은  5 초  이내로  한다 ."


def _finding(fid, quote, sev="minor", page=1):
    return {"id": fid, "sev": sev, "checker": "consistency",
            "message": "응답시간이 3초와 5초로 상충된다",
            "section": "0", "page": page,
            "evidence": [{"quote": quote, "section": "0", "page": page}]}


def _highlights(pdf_bytes):
    """표시본의 형광펜 주석. 요약 페이지가 앞에 붙으므로 마지막 쪽을 본다."""
    pg = PdfReader(io.BytesIO(pdf_bytes)).pages[-1]
    return [a.get_object() for a in (pg.get("/Annots") or [])
            if a.get_object().get("/Subtype") == "/Highlight"]


def _short_version_pdf() -> bytes:
    """날짜가 버전보다 먼저 나오는 표를 흉내 낸 한 쪽 PDF."""
    FPDF = pytest.importorskip("fpdf").FPDF
    pdf = FPDF(unit="pt", format="A4")
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.text(100, 100, "Date")
    pdf.text(200, 100, "2026. 01. 02.")
    pdf.text(100, 200, "Version")
    pdf.text(200, 200, "1.0")
    return bytes(pdf.output())


def test_quote_gets_a_mark_with_coordinates():
    loc = locate(PDF.read_bytes(), [_finding("f1", QUOTE_3)])
    assert loc["pages"] >= 1
    it = loc["items"][0]
    assert it["id"] == "f1"
    assert it["marks"], "인용을 찾았으면 마크가 있어야 한다"
    x0, y0, x1, y1 = it["marks"][0]["rect"]
    assert x1 > x0 and y1 > y0, "사각형이 뒤집혀 있다"


def test_short_version_value_does_not_point_into_an_earlier_date():
    """`1.0`은 날짜에도 들어간다. 표 라벨을 보존해야 버전 행을 정확히 짚는다."""
    pdf = _short_version_pdf()
    bare = locate(pdf, [_finding("bare", "1.0")])["items"][0]["marks"][0]
    contextual = locate(
        pdf, [_finding("context", "Version | 1.0")]
    )["items"][0]["marks"][0]

    assert bare["rect"][1] > contextual["rect"][1], \
        "짧은 값만 찾으면 위쪽 날짜를 잡는 회귀 조건이어야 한다"
    assert contextual["rect"][1] == pytest.approx(640, abs=15), \
        "라벨과 값을 함께 찾으면 아래쪽 버전 행이어야 한다"


def test_reports_the_page_it_actually_found_not_the_claimed_one():
    """체커가 주장한 쪽이 틀려도(page=99) 실제로 찾아낸 쪽을 돌려준다.

    _candidate_pages가 문서 전체를 뒤져 올바른 자리를 찾아내므로 형광펜은 제자리에
    찍힌다. 그 교정된 쪽을 밖으로 내보내는 것이 이 함수의 존재 이유다.
    """
    loc = locate(PDF.read_bytes(), [_finding("f1", QUOTE_3, page=99)])
    it = loc["items"][0]
    assert it["marks"], "전체를 뒤져서라도 찾아야 한다"
    assert it["page"] == it["marks"][0]["page"]      # 실제로 찾은 쪽
    assert it["page"] != 99                           # 주장한 쪽이 아니다


def test_missing_quote_is_reported_not_swallowed():
    loc = locate(PDF.read_bytes(), [_finding("f1", "본문에 절대 없는 문장이다")])
    assert loc["items"][0]["marks"] == []
    assert loc["items"][0]["page"] is None
    assert len(loc["unlocated"]) == 1
    assert loc["unlocated"][0]["id"] == "f1"


def test_all_page_numbers_are_one_based():
    loc = locate(PDF.read_bytes(), [_finding("f1", QUOTE_3)])
    it = loc["items"][0]
    assert it["page"] >= 1
    assert all(m["page"] >= 1 for m in it["marks"])


def test_locate_rect_matches_the_highlight_annotate_draws():
    """핵심 계약: 화면이 그리는 자리와 내려받은 PDF의 형광펜이 같은 자리여야 한다.

    annotate는 인용문당 형광펜 주석 하나(여러 줄이면 quad 여럿을 한 주석에)를
    그리고, locate는 줄마다 마크 하나를 낸다. 그래서 개수는 다르지만 **전체를
    감싸는 사각형**은 같아야 한다 — 갈라지면 화면과 배포 PDF의 위치가 달라진다.
    """
    findings = [_finding("f1", QUOTE_3)]
    loc = locate(PDF.read_bytes(), findings)
    out = annotate(PDF.read_bytes(), findings)
    drawn = _highlights(out.pdf)
    assert len(drawn) == 1, "인용문 하나는 형광펜 주석 하나"
    marks = loc["items"][0]["marks"]
    assert marks
    # locate 마크들을 감싸는 사각형
    want = [min(m["rect"][0] for m in marks), min(m["rect"][1] for m in marks),
            max(m["rect"][2] for m in marks), max(m["rect"][3] for m in marks)]
    got = [float(v) for v in drawn[0]["/Rect"]]
    assert got == pytest.approx(want, abs=0.01)


def test_인용마다_자기_번호를_들고_나온다():
    """지적 하나에 인용이 여럿이면 형광펜도 여럿이고 번호도 여럿이다.

    예전에는 번호가 지적에만 달렸다(`"1, 2"`). 뷰어는 첫 형광펜에만 `1` 을 그리고
    나머지는 번호 없이 칠했다 — 카드는 둘이라는데 문서엔 하나만 보였다.
    """
    both = {"id": "F1", "sev": "minor", "checker": "consistency",
            "message": "응답시간이 3초와 5초로 상충된다", "section": "0", "page": 1,
            "evidence": [{"quote": QUOTE_3, "section": "0", "page": 1},
                         {"quote": QUOTE_5, "section": "0", "page": 1}]}
    out = locate(PDF.read_bytes(), [both])
    item = out["items"][0]
    assert item["no"] == "1, 2"
    nos = sorted({m["no"] for m in item["marks"]})
    assert nos == [1, 2], f"마크가 자기 번호를 안 들고 있다: {item['marks']}"


def test_같은_곳을_두_지적이_물면_번호를_따로_준다():
    """한 곳에 문제가 둘 이상일 수 있다 — 지적마다 제 번호를 준다.

    실측(SKN56 RVVR): `운영파일` 하나를 세 지적이 물었다(용어 혼용·띄어쓰기·표기).
    번호까지 공유하면 카드 번호가 `36, 29` 처럼 겹치고, 형광펜을 눌렀을 때 어느
    카드로 갈지가 안 정해지며, 반영 확인에서 하나를 정리해도 그 자리가 안 지워진다.
    """
    a = _finding("F1", QUOTE_3)
    b = _finding("F2", QUOTE_3)
    out = locate(PDF.read_bytes(), [a, b])
    assert [i["no"] for i in out["items"]] == ["1", "2"]
    assert {m["no"] for i in out["items"] for m in i["marks"]} == {1, 2}
    # 자리는 같다 — 같은 글자를 문 것이니 형광펜은 겹친다.
    assert out["items"][0]["marks"][0]["rect"] == out["items"][1]["marks"][0]["rect"]


def test_quote_nos_align_with_evidence():
    """인용별 번호는 evidence 순서와 나란하다 — 못 찾은 인용 자리는 None.

    카드가 "이 인용이 몇 번 형광펜인가"를 달려면 이 정렬이 계약이다. 같은 절의
    인용이 둘일 때(용어 모순) 번호 없이는 둘째 인용을 문서에서 찾을 길이 없다.
    """
    f = _finding("f1", QUOTE_3)
    f["evidence"].append({"quote": "이 문장은 문서에 없다 zzz", "section": "0", "page": 1})
    loc = locate(PDF.read_bytes(), [f])
    it = loc["items"][0]
    assert it["quote_nos"][0] == 1          # 첫 인용 = 1번 형광펜
    assert it["quote_nos"][1] is None       # 못 찾은 인용은 자리만 지킨다
    assert len(it["quote_nos"]) == 2


def test_table_quote_with_pipes_is_located():
    """표에서 나온 인용은 파서가 붙인 파이프(|)가 섞인다 — PDF 텍스트 레이어에는
    그 글자가 없으므로 지우고 대조해야 위치를 찾는다(실측: `| LIST OF TABLES |`)."""
    piped = "| RQ-SFR-PR-01-001 | 예측  응답시간은  3 초  이내여야  한다 . |"
    loc = locate(PDF.read_bytes(), [_finding("f1", piped)])
    assert loc["items"][0]["marks"], "파이프를 걷어내면 같은 문장을 찾아야 한다"


def test_header_evidence_is_not_hunted_in_the_body():
    """머릿말 인용은 **본문에 없다** — 파서가 본문에서 빼고 meta 로 옮긴다.

    그 인용을 본문에서 뒤지면 우연히 같은 글자가 있는 곳을 짚는다. 실측(제출물
    확인증): 머릿말의 `제출물 확인증` 이 본문 표의 같은 글자에 형광펜을 얹어,
    **문서 제목이 지적받은 것처럼** 보였다.

    짚지 않되 조용히 넘기지도 않는다 — 왜 못 짚는지 unlocated 가 말한다.
    """
    body_quote = QUOTE_3
    f = _finding("f1", body_quote)
    f["evidence"][0]["source"] = "머릿말"
    out = locate(PDF.read_bytes(), [f])
    assert not out["items"][0]["marks"], "본문에서 찾아 형광펜을 얹었다"
    assert out["unlocated"], "못 짚은 사실을 말하지 않았다"
    assert "머릿말에서 나왔습니다" in out["unlocated"][0]["reason"]


def test_body_evidence_still_gets_a_mark():
    """앞 시험의 뒷면. source 가 없는 근거는 지금처럼 본문에서 찾는다."""
    out = locate(PDF.read_bytes(), [_finding("f1", QUOTE_3)])
    assert out["items"][0]["marks"], "본문 인용까지 안 찾게 됐다"
