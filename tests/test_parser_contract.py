"""파서 계약 — 파서를 갈아 끼워도 **검사기가 받는 값**이 같아야 한다.

이름의 "계약"은 문서 이력·재검토와 아무 상관이 없다. 파서와 검사기 사이의 약속이다.

왜 필요한가. 다른 테스트들은 검사기에 **손으로 쓴 표 텍스트**를 먹여 "검사기가 잘
도는가"를 본다. 그래서 진짜 문서를 파서가 그 형태로 내주는지는 아무도 안 봤다.
2026-08-13 에 실제로 그 사각지대에서 사고가 났다:

    옛 파서   | 접수번호 | RN-26-999 | 접수일 | 2026. 01. 01. |
    trkim    | 접수번호 |  | RN-26-999 | 접수일 |  | 2026. 01. 01. |

접수번호 칸이 2열 병합이라 trkim 은 이어짐 자리를 빈 칸으로 남긴다. 추출기는 라벨
바로 오른쪽을 값으로 읽으므로 빈 칸을 값으로 집었고, 문서에 값이 멀쩡히 있는데
`'접수번호' 이(가) 비어 있습니다` 가 major 로 나갔다. 검토자가 고칠 것이 없는
지적이 제일 나쁘다 — 게다가 인용 대조도 이걸 못 잡는다(근거로 다는 것이 값이 아니라
라벨이라 문서에 실재한다).

**두 파서의 텍스트가 글자까지 같기를 요구하지는 않는다.** 실측해 보면 연속 공백
압축·그림 자리표시(`[그림 N]`)·행 쪼개는 방식이 정당하게 다르다. 계약은 그보다
좁고 분명한 것이다 — *같은 문서에서 같은 값이 나오는가*. 검사기가 실제로 보는 것이
그것이고, 이번 사고가 깨뜨린 것도 그것이다.
"""
from __future__ import annotations

import re

import pytest
import yaml
from conftest import _ROOT, DATA

from app.case import _field_specs, output_spec_for
from app.parser_bridge import install_trkim_parser
from modules.doc_parser import load_document, normalize
from modules.doc_parser.fields.extract import extract_fields

TEAM = "ai-test-cert-1"
CASE_DIR = "AI시험인증1팀_시험산출물 샘플"


def _team_spec() -> dict:
    path = _ROOT / "presets" / "criteria" / "teams" / f"{TEAM}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _sample_outputs() -> list:
    """샘플 산출물 중 **칸 값 지도가 있는** 것만. data/ 가 없으면 빈 목록."""
    root = next(iter(sorted(DATA.rglob(CASE_DIR))), None) if DATA.is_dir() else None
    if root is None:
        return []
    spec = _team_spec()
    out = []
    for path in sorted(root.rglob("*.docx")):
        output_spec, _ = output_spec_for(path.name, spec)
        if output_spec and output_spec.get("fields"):
            out.append((path, _field_specs(output_spec)))
    return out


SAMPLES = _sample_outputs()


def _values(path, specs) -> dict[str, str | None]:
    doc = normalize(load_document(path), doc_type="generic")
    return {name: (v.value if v.found else None)
            for name, v in extract_fields(doc, specs).items()}


@pytest.mark.skipif(not SAMPLES, reason=f"{CASE_DIR} 없음 — data/ 에 두면 이 계약이 돈다")
@pytest.mark.parametrize("path,specs", SAMPLES, ids=lambda x: getattr(x, "name", ""))
def test_두_파서가_같은_값을_낸다(path, specs, monkeypatch):
    """옛 로더와 trkim 이 같은 문서에서 같은 칸 값을 내야 한다.

    한쪽만 값을 못 찾거나 빈 문자열을 내면 그 문서의 칸 값 검사가 통째로 거짓
    지적이 된다 — 파서를 바꾼 그 순간 여기서 잡힌다.
    """
    legacy = _values(path, specs)

    # EXTRA_LOADERS 는 conftest 의 _isolate_extra_loaders 가 테스트마다 되돌린다.
    install_trkim_parser("", "ocr", "")     # 이미지 OCR 은 끈다 — 값 대조에 안 쓰고 느리다
    trkim = _values(path, specs)

    assert trkim == legacy, (
        f"{path.name}: 파서에 따라 칸 값이 다르다.\n"
        + "\n".join(f"  {k}: 옛 파서 {legacy.get(k)!r} / trkim {trkim.get(k)!r}"
                    for k in sorted(set(legacy) | set(trkim))
                    if legacy.get(k) != trkim.get(k)))


@pytest.mark.skipif(not SAMPLES, reason=f"{CASE_DIR} 없음")
def test_필수_칸이_실제로_대조된다():
    """계약이 빈 껍데기가 아닌지 — 대조하는 칸이 하나라도 있어야 한다.

    산출물 판별이 조용히 어긋나면 SAMPLES 가 비고, 위 테스트는 "통과" 처럼 보인다.
    """
    names = {s.name for _, specs in SAMPLES for s in specs}
    assert "접수번호" in names, f"이번 사고의 그 칸이 대조에 안 들어 있다: {sorted(names)}"


_PDF_NAME = "SKN56_CDMS_RVVR_Rev05.pdf"
_PDF = next(iter(sorted(DATA.rglob(_PDF_NAME))), None) if DATA.is_dir() else None


@pytest.mark.skipif(_PDF is None, reason=f"{_PDF_NAME} 없음")
def test_PDF_표_셀에서_단어가_갈라지지_않는다(monkeypatch):
    """`Communication` 이 `Communicati on` 으로 갈리면 없는 용어 혼용이 지적된다.

    2026-08-06 `9dc0b63` 에서 옛 PDF 로더에 고쳤던 버그가 파서 교체와 함께 되살아났다
    (그 수정은 `ingestion/pdf_tables.py::cell_lines` 전용이라 trkim 경로에는 없었다).
    2026-08-14 에 trkim 쪽에도 같은 신호를 살려 고쳤다 — PDF 글자 흐름의 줄 끝 공백이
    "단어가 끝났나 / 폭 때문에 한가운데서 끊겼나"를 가른다
    (`pdf_backend._line_end_spaces` → `merge_wrapped_lines(trailing_space_known=True)`).

    한동안 xfail 로 두었고, 고쳐지자 XPASS 로 뒤집혀 알려줬다. 이제 정식 검사다.
    (느리다: 두 파서로 PDF 를 한 번씩 읽어 30초쯤 걸린다. 실문서가 없는 기계에서는
     애초에 skip 이다.)
    """
    legacy_text = load_document(_PDF).text
    install_trkim_parser("", "ocr", "")
    trkim_text = load_document(_PDF).text

    legacy_split = legacy_text.count("Communicati on")
    trkim_split = trkim_text.count("Communicati on")
    assert trkim_split <= legacy_split, (
        f"trkim 이 옛 파서에 없던 단어 쪼개짐을 만든다: "
        f"옛 파서 {legacy_split}건 / trkim {trkim_split}건")

    # §4-0 이슈㉓(2026-08-14): 문자열 기준 줄 끝 공백 대조가
    # 같은 y의 여러 PDF text-line을 놓쳐 정상 단어 경계를 붙였다.
    # 같은 문서의 병합 표에서는 가짜 행 경계가 단어 줄바꿈을 두 칸으로
    # 나눠 ``Communicati``/``on``, ``Ba``/``ckup)`` 조각도 남겼다.
    broken = ["softwarerequirements", "providesinformation", "managingchanges",
              "andmanaging", "accuratelyspecified", "tosoftware"]
    for bad in broken:
        assert bad not in trkim_text, f"trkim 검토 본문에 가짜 붙어쓰기가 남음: {bad}"
    # 불량 문자열을 지우면서 원문까지 유실한 것은 아닌지 정상형을 같이 본다.
    for expected in ["software requirements", "provides information", "managing changes",
                     "and managing", "Communication", "자기진단정보(Backup)"]:
        assert expected in trkim_text, f"trkim 검토 본문에 복원된 정상 표기가 없음: {expected}"
    # 파서 오탐과 달리 PDF 원문에 실재하는 후보는 보존해야 한다.
    assert "Dose each interface provides information" in trkim_text
    assert not re.search(r"Communicati(?!on)|Communicatio(?!n)", trkim_text), \
        "trkim 검토 본문에 Communication 단독 조각이 남음"
    assert not re.search(r"자기진단정보\(Ba\s*\n|^\s*ckup\)", trkim_text, re.MULTILINE), \
        "trkim 검토 본문에 Backup 단독 조각이 남음"
