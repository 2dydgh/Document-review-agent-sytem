"""라벨 없는 칸 하나 뽑기 (`from: table_cell`).

`table` 은 라벨을 찾고 그 옆/아래를 집는다. 그런데 라벨이 **아예 없는** 칸이 있다.
실측(AI시험인증1 시험 계획서·설계서 결재란):

    | 의뢰번호    | 시험 실무자        | 기술 책임자       |
    | SST-26-999 |  | 2026. 01. 02. |  | 2026. 01. 02. |

머리행 3칸 · 값 행 5칸이라 칸 번호로는 못 맞춘다. `table_rows` 도 칸 번호로
맞추므로 여기서는 어긋난다. **빈 칸을 걷어내면 1:1 로 맞는다** — 그 규칙으로 집는다.

이 값이 없으면 "작성일자 선후 관계"(의뢰서 → 계획서 → 설계서)를 판정할 수 없다.
"""
from modules.doc_parser import FieldSpec, RawDoc, extract_fields, normalize


def _doc(*lines):
    return normalize(RawDoc(source_path="t.docx", text="\n".join(lines)))


def _cell(doc, **kw):
    kw.setdefault("name", "작성일자")
    kw.setdefault("source", "table_cell")
    kw.setdefault("columns", ("의뢰번호", "시험 실무자", "기술 책임자"))
    kw.setdefault("key", "시험 실무자")
    return extract_fields(doc, [FieldSpec(**kw)])[kw["name"]]


def test_빈_칸이_끼어도_순번으로_맞춘다():
    doc = _doc("| 의뢰번호 | 시험 실무자 | 기술 책임자 |",
               "| SST-26-999 |  | 2026. 01. 02. |  | 2026. 01. 03. |")
    v = _cell(doc)
    assert v.found and v.value == "2026. 01. 02."


def test_다른_열도_집는다():
    doc = _doc("| 의뢰번호 | 시험 실무자 | 기술 책임자 |",
               "| SST-26-999 |  | 2026. 01. 02. |  | 2026. 01. 03. |")
    assert _cell(doc, key="기술 책임자").value == "2026. 01. 03."


def test_빈_칸이_없어도_된다():
    doc = _doc("| 의뢰번호 | 시험 실무자 | 기술 책임자 |",
               "| SST-26-999 | 2026. 01. 02. | 2026. 01. 03. |")
    assert _cell(doc).value == "2026. 01. 02."


def test_열_조합이_안_맞으면_못_찾은_것이다():
    """일부만 맞으면 다른 표일 수 있다. 엉뚱한 표를 집으면 거짓 지적이 난다."""
    doc = _doc("| 의뢰번호 | 담당자 |", "| SST-26-999 | 김슈어 |")
    assert not _cell(doc).found


def test_걷어낸_뒤_길이가_다르면_집지_않는다():
    """대응을 확신할 수 없으면 아무 칸이나 집지 않는다 — 조용히 집으면 엉뚱한 값을
    그 필드의 값이라고 우기게 된다."""
    doc = _doc("| 의뢰번호 | 시험 실무자 | 기술 책임자 |",
               "| SST-26-999 | 2026. 01. 02. |")
    assert not _cell(doc).found


def test_표별_글꼴_크기를_모은다():
    """서식 검사(글꼴)는 sections 로는 못 한다 — 거기 남는 것은 렌더된 글자뿐이라
    "이 표의 이 글자가 8pt" 라는 사실이 파싱 중에 사라진다. meta 로 실어 나른다.

    **표 안만 모은다.** 실측(시험 설계서) 표지 제목이 40pt 로 직접 박혀 있는데,
    표 밖까지 재면 그것을 "8~9pt 가 아니다"로 지적하게 된다.
    """
    import sys
    import zipfile
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tests"))
    import pytest
    from conftest import sample

    from modules.doc_parser import load_document, normalize

    z = sample("AI시험인증1팀_시험산출물 샘플.zip")
    if z is None:
        pytest.skip("실산출물 샘플 없음")
    import tempfile
    with zipfile.ZipFile(z) as zf:
        name = next(x for x in zf.namelist()
                    if "시험 설계서" in Path(x).name and x.endswith(".docx")
                    and "__MACOSX" not in x)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "d.docx"
            p.write_bytes(zf.read(name))
            doc = normalize(load_document(p))

    tables = doc.meta.get("tables") or []
    sizes = {s for tb in tables for s in (tb.get("fontSizes") or {})}
    assert sizes == {8.0}, f"테스트케이스 8pt 만 나와야 한다 (표지 40pt 는 표 밖): {sizes}"


def test_길이가_다르면_아래_행까지_훑지_않는다():
    """계약대로 **거기서** 포기한다.

    예전에는 길이가 어긋나면 표 끝까지 훑어 내려가, 우연히 칸 수가 맞는 한참
    아래 행(비고·서명 줄)의 칸을 그 필드의 값이라고 우겼다. 그 틀린 작성일자가
    선후 관계 검사까지 오염시켜 멀쩡한 문서 세트에 MAJOR 지적을 냈다.
    """
    doc = _doc("| 의뢰번호 | 시험 실무자 | 기술 책임자 |",
               "| SST-26-999 | 2026. 01. 02. |",          # 칸 수 어긋남 → 포기
               "| 비고 | 2099. 12. 31. | 서명 |")          # 우연히 3칸
    assert not _cell(doc).found


def test_표_안의_빈_줄은_건너뛴다():
    """포기는 '칸 수가 다를 때'다. 아무것도 없는 줄은 값 행이 아직 아래라는 뜻이다."""
    doc = _doc("| 의뢰번호 | 시험 실무자 | 기술 책임자 |",
               "|  |  |  |",
               "| SST-26-999 | 2026. 01. 02. | 2026. 01. 03. |")
    assert _cell(doc).value == "2026. 01. 02."
