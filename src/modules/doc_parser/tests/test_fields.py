"""라벨 기반 필드 추출.

이 문서들은 거의 전부 표다(실측: 검토기록서 11줄 중 10, 제출물확인증 30줄 중 29).
그래서 "어느 칸이 라벨이고 그 값이 어디 있나"만 알면 값을 꺼낼 수 있다.

표는 두 모양으로 온다:

    갑지 (세로)                       을지 머리표 (가로)
    | 기관명 | 한국소프트웨어시험연구소 |   | 의뢰번호 | 성적서번호 |
             ↑ at: right              | SST-26-999 | SST-26-999-C01 |
                                                   ↑ at: below
"""
from modules.doc_parser import FieldSpec, RawDoc, extract_fields, normalize


def _doc(*lines):
    return normalize(RawDoc(source_path="t.docx", text="\n".join(lines)))


def test_라벨_오른쪽_칸을_값으로_읽는다():
    doc = _doc("| 기관명 | 한국소프트웨어시험연구소 |")

    got = extract_fields(doc, [FieldSpec(name="의뢰기관명", labels=("기관명",))])

    assert got["의뢰기관명"].value == "한국소프트웨어시험연구소"
    assert got["의뢰기관명"].found is True


def test_라벨_아래_칸을_값으로_읽는다():
    doc = _doc("| 의뢰번호 | 성적서번호 | 시험기간 |",
               "| SST-26-999 | SST-26-999-C01 | 2026. 01. 01.~2026. 01. 15. |")

    got = extract_fields(doc, [FieldSpec(name="성적서번호", labels=("성적서번호",),
                                         at="below")])

    assert got["성적서번호"].value == "SST-26-999-C01"
    assert got["성적서번호"].source_quote == (
        "SST-26-999 | SST-26-999-C01 | 2026. 01. 01.~2026. 01. 15.")


def test_라벨은_셀_전체가_같아야_한다():
    # 갑지에는 `주소 :`(슈어 주소)와 `주소`(의뢰기관 주소)가 둘 다 있다. 부분일치로
    # 찾으면 회사 주소를 의뢰기관 주소로 읽고, 그 값이 문서 간 대조에 들어가
    # 거짓 불일치를 만든다.
    doc = _doc("| 주소 : | 경기 성남시 수정구 금토로 |",
               "| 주소 | 서울시 강남구 논현로 |")

    got = extract_fields(doc, [FieldSpec(name="의뢰기관주소", labels=("주소",))])

    assert got["의뢰기관주소"].value == "서울시 강남구 논현로"


def test_라벨_후보를_여러_개_준다():
    # 같은 필드의 라벨이 문서마다 다르다(실측): "의뢰번호 :" vs "의뢰 번호:".
    doc = _doc("| 의뢰 번호: | SST-26-999 |")

    got = extract_fields(doc, [FieldSpec(name="의뢰번호",
                                         labels=("의뢰번호 :", "의뢰 번호:"))])

    assert got["의뢰번호"].value == "SST-26-999"
    assert got["의뢰번호"].matched_label == "의뢰 번호:"


def test_공백은_무시하고_맞춘다():
    doc = _doc("| 시험  대상   품목 | Apple |")

    got = extract_fields(doc, [FieldSpec(name="제품명", labels=("시험 대상 품목",))])

    assert got["제품명"].value == "Apple"


def test_못_찾으면_빈_문자열이_아니라_found_False():
    # "필드가 비었다"와 "필드를 못 찾았다"는 다른 지적이다. 후자는 라벨맵이 틀렸을
    # 가능성이라 사람이 봐야 한다 — 빈 문자열로 뭉개면 그 구분이 사라진다.
    doc = _doc("| 기관명 | 한국소프트웨어시험연구소 |")

    got = extract_fields(doc, [FieldSpec(name="대표자", labels=("대표자",))])

    assert got["대표자"].found is False
    assert got["대표자"].value is None


def test_값_칸이_비어_있으면_찾았지만_빈_값():
    doc = _doc("| 대표자 |  |")

    got = extract_fields(doc, [FieldSpec(name="대표자", labels=("대표자",))])

    assert got["대표자"].found is True
    assert got["대표자"].value == ""


def test_한_칸에_합쳐진_값을_capture로_나눠_읽는다():
    doc = _doc("| 시험 환경 | - 온도: (26.0 ± 0.6) °C - 습도: (52.5 ± 3.5) % R.H. |")

    got = extract_fields(doc, [
        FieldSpec(name="시험환경_온도", labels=("시험 환경",),
                  capture=r"온도\s*:\s*(?P<value>\([^)]*\)\s*°C)"),
        FieldSpec(name="시험환경_습도", labels=("시험 환경",),
                  capture=r"습도\s*:\s*(?P<value>\([^)]*\)\s*%\s*R\.H\.)"),
    ])

    assert got["시험환경_온도"].value == "(26.0 ± 0.6) °C"
    assert got["시험환경_습도"].value == "(52.5 ± 3.5) % R.H."
    assert got["시험환경_온도"].source_quote == (
        "시험 환경 | - 온도: (26.0 ± 0.6) °C - 습도: (52.5 ± 3.5) % R.H.")


def test_capture가_맞지_않으면_필드를_찾지_못한_것이다():
    doc = _doc("| 시험 환경 | 의뢰 기관에서 제시한 환경 |")

    got = extract_fields(doc, [FieldSpec(
        name="시험환경_온도", labels=("시험 환경",), capture=r"온도:\s*(.+)")])

    assert got["시험환경_온도"].found is False
    assert got["시험환경_온도"].anchor.section == "표1 1행"


def test_지적_위치를_표와_행으로_남긴다():
    # 이 문서들은 제목이 0개라 normalize 가 섹션 하나(section="0")만 만든다.
    # 위치가 전부 "0"이면 리포트가 쓸모없다.
    doc = _doc("| 머리 | 값 |",
               "",
               "| 기관명 | 한국소프트웨어시험연구소 |")

    got = extract_fields(doc, [FieldSpec(name="의뢰기관명", labels=("기관명",))])

    assert "표2" in got["의뢰기관명"].anchor.section


def test_체크박스는_선택된_것을_돌려준다():
    doc = _doc("| 시험 장소 | □ 고정 시험실 | ■ 현장 시험 |")

    got = extract_fields(doc, [FieldSpec(name="시험장소", source="checkbox_group",
                                         options=("고정 시험실", "현장 시험"))])

    assert got["시험장소"].selected == ("현장 시험",)


def test_체크박스가_하나도_선택되지_않으면_빈_튜플():
    doc = _doc("| 시험 장소 | □ 고정 시험실 | □ 현장 시험 |")

    got = extract_fields(doc, [FieldSpec(name="시험장소", source="checkbox_group",
                                         options=("고정 시험실", "현장 시험"))])

    assert got["시험장소"].selected == ()
    assert got["시험장소"].found is True     # 그룹은 찾았다. 선택이 없을 뿐이다


def test_체크박스가_둘_선택되면_둘_다_돌려준다():
    # "항목당 하나만" 위반을 판정하려면 개수를 알아야 한다.
    doc = _doc("| 시험 장소 | ■ 고정 시험실 | ■ 현장 시험 |")

    got = extract_fields(doc, [FieldSpec(name="시험장소", source="checkbox_group",
                                         options=("고정 시험실", "현장 시험"))])

    assert got["시험장소"].selected == ("고정 시험실", "현장 시험")


# ── 값이 있는 자리를 고른다 ────────────────────────────────────────────────
# 실측(SST-K-TP-7-01-01 시험 의뢰 검토 기록서): 접수번호가 문서에 멀쩡히 적혀
# 있는데 `'접수번호' 이(가) 비어 있습니다` 가 major 로 나갔다. 라벨이 나온 첫
# 자리에서 그냥 끝내던 탓이다 — 검토자가 고칠 것이 없는 지적이라 제일 나쁘다.


def test_라벨이_여러_번_나오면_값이_있는_자리를_고른다():
    # 쪽 넘김에 머리행이 되풀이되거나, 위에 빈 서식 행이 놓인 양식.
    doc = _doc("| 접수번호 |  |",
               "| 접수번호 | RN-26-001 |")

    got = extract_fields(doc, [FieldSpec(name="접수번호", labels=("접수번호",))])

    assert got["접수번호"].value == "RN-26-001"
    assert got["접수번호"].anchor.section == "표1 2행"   # 값이 있는 자리를 짚는다


def test_여백_칸을_건너뛰지_않는다():
    # 라벨과 값 사이에 빈 칸이 끼는 양식이 있어 한 칸 건너뛰어 봤다가 되돌렸다.
    # 실문서(SKN56_CDMS_RVVR_Rev08 표지 결재란)가 `| 작성자 : |  | Date : |` 라,
    # 건너뛰면 옆 라벨 `Date :` 를 작성자 값으로 집는다 — 안 채운 칸을 지적해야
    # 하는 자리가 조용히 통과했다. 문서의 어떤 말이 라벨인지 우리는 모른다.
    doc = _doc("| 작성자 : |  | Date : |  |")

    got = extract_fields(doc, [FieldSpec(name="작성자", labels=("작성자 :",))])

    assert got["작성자"].value == ""      # 'Date :' 를 값이라 하지 않는다


def test_어디에도_값이_없으면_비어_있다고_낸다():
    # required 검사가 잡아야 하는 진짜 빈 칸까지 삼키면 안 된다.
    doc = _doc("| 접수번호 |  |")

    got = extract_fields(doc, [FieldSpec(name="접수번호", labels=("접수번호",))])

    assert got["접수번호"].found is True
    assert got["접수번호"].value == ""
