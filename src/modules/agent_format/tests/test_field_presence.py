"""칸 값 검사 — 필드가 채워졌나, 형식이 맞나.

팀 기준 80항목 중 8항목이 이 검사기를 요구한다(`docs/checker-inventory.md` A).
EV2 표지정보·개정기록·평가표·참조문서목록·MEMO·목적범위, AI시험인증1 문서양식·시험환경.

**추출과 판정은 다른 일이다.** `extract_fields` 가 값을 꺼내고 여기서 판정한다.
그래서 "못 찾았다"(라벨맵이 문서와 어긋남 → 사람이 봐야 함)와 "비었다"(문서 결함)가
섞이지 않는다.
"""
from modules.agent_format import FieldPresenceChecker, SignatureSpec
from modules.doc_parser import FieldSpec, RawDoc, normalize
from modules.shared import Severity


def _doc(*lines):
    return normalize(RawDoc(source_path="t.docx", text="\n".join(lines)))


def _run(doc, fields=(), **kw):
    return FieldPresenceChecker(fields=list(fields), **kw).check(doc, None)


# ── required ─────────────────────────────────────────────────────────────

def test_필드가_채워져_있으면_지적하지_않는다():
    doc = _doc("| 기관명 | 한국소프트웨어시험연구소 |")

    got = _run(doc, [FieldSpec(name="의뢰기관명", labels=("기관명",), required=True)])

    assert got == []


def test_필수_필드가_비어_있으면_지적한다():
    doc = _doc("| 기관명 |  |")

    got = _run(doc, [FieldSpec(name="의뢰기관명", labels=("기관명",), required=True)])

    assert len(got) == 1
    assert got[0].severity is Severity.MAJOR
    assert "의뢰기관명" in got[0].message
    assert got[0].unreviewed is False


def test_필수가_아니면_비어도_지적하지_않는다():
    doc = _doc("| 기관명 |  |")

    got = _run(doc, [FieldSpec(name="의뢰기관명", labels=("기관명",))])

    assert got == []


def test_라벨을_못_찾으면_미검토다():
    """라벨맵이 실제 문서와 어긋났을 수 있다. "비었다"로 내면 문서 결함이
    아닌 것을 결함으로 위장한다."""
    doc = _doc("| 의뢰기관 | 한국소프트웨어시험연구소 |")

    got = _run(doc, [FieldSpec(name="의뢰기관명", labels=("기관명",), required=True)])

    assert len(got) == 1
    assert got[0].unreviewed is True
    assert got[0].severity is Severity.INFO


def test_필드_목록이_비면_검사_못_했다고_말한다():
    """조용한 0건은 "칸이 다 채워져 있더라"로 읽힌다.

    이 검사기는 못 찾은 칸도 미검토로 밝히면서, 정작 볼 칸을 하나도 못 받았을
    때만 입을 다물고 있었다. 기준이 `check: field_presence` 를 댔는데 어느 칸을
    볼지 아무도 안 알려준 경우가 그것이다.
    """
    got = _run(_doc("| 기관명 | 값 |"))
    assert [f.severity for f in got] == [Severity.INFO]
    assert got[0].unreviewed


# ── pattern ──────────────────────────────────────────────────────────────

def test_pattern_에_맞으면_통과다():
    doc = _doc("| 성적서번호 | SST-26-999-C01 |")

    got = _run(doc, [FieldSpec(name="성적서번호", labels=("성적서번호",),
                               pattern=r"SST-\d{2}-\d{3}-C\d+")])

    assert got == []


def test_pattern_에_어긋나면_지적한다():
    """실측: 을지가 `SST-26-999-C01`, 갑지가 `SST-26-999C01` — 하이픈이 빠졌다."""
    doc = _doc("| 성적서번호 | SST-26-999C01 |")

    got = _run(doc, [FieldSpec(name="성적서번호", labels=("성적서번호",),
                               pattern=r"SST-\d{2}-\d{3}-C\d+")])

    assert len(got) == 1
    assert got[0].severity is Severity.MAJOR
    assert "SST-26-999C01" in got[0].message


def test_pattern_은_전체가_맞아야_한다():
    """부분일치를 허용하면 `XXSST-26-999-C01YY` 가 통과한다."""
    doc = _doc("| 성적서번호 | 번호 SST-26-999-C01 입니다 |")

    got = _run(doc, [FieldSpec(name="성적서번호", labels=("성적서번호",),
                               pattern=r"SST-\d{2}-\d{3}-C\d+")])

    assert len(got) == 1


def test_빈_값에는_pattern_지적을_겹쳐_내지_않는다():
    """비었으면 "비었다" 하나면 된다. 형식까지 지적하면 한 결함이 두 건이 된다."""
    doc = _doc("| 성적서번호 |  |")

    got = _run(doc, [FieldSpec(name="성적서번호", labels=("성적서번호",),
                               pattern=r"SST-\d{2}-\d{3}-C\d+", required=True)])

    assert len(got) == 1
    assert "비어" in got[0].message


# ── format ───────────────────────────────────────────────────────────────

def test_date_형식이_맞으면_통과다():
    doc = _doc("| 작성일자 | 2026. 01. 05. |")

    got = _run(doc, [FieldSpec(name="작성일자", labels=("작성일자",), format="date")])

    assert got == []


def test_미작성_날짜를_지적한다():
    """실측: 의뢰서 `| 일자 | 2026.    .    . |` × 3, 동의서 `| 일자 | 20    .    . |` × 2."""
    doc = _doc("| 일자 | 2026.    .    . |")

    got = _run(doc, [FieldSpec(name="작성일자", labels=("일자",), format="date")])

    assert len(got) == 1
    assert got[0].severity is Severity.MAJOR


def test_date_range_형식이_맞으면_통과다():
    doc = _doc("| 시험 기간 | 2026. 01. 05. ~ 2026. 01. 15. |")

    got = _run(doc, [FieldSpec(name="시험기간", labels=("시험 기간",),
                               format="date_range")])

    assert got == []


def test_date_range_는_공백이_달라도_통과다():
    """실측: 을지 `~2026. 01. 15.` ↔ 갑지 `~ 2026. 01. 15.` — 공백 한 칸 차이.
    이건 대조(compare_pair)가 잡을 일이지 형식 위반이 아니다."""
    doc = _doc("| 시험 기간 | 2026. 01. 05.~2026. 01. 15. |")

    got = _run(doc, [FieldSpec(name="시험기간", labels=("시험 기간",),
                               format="date_range")])

    assert got == []


def test_시작이_종료보다_늦으면_지적한다():
    doc = _doc("| 시험 기간 | 2026. 01. 15. ~ 2026. 01. 05. |")

    got = _run(doc, [FieldSpec(name="시험기간", labels=("시험 기간",),
                               format="date_range")])

    assert len(got) == 1
    assert "순서" in got[0].message


def test_없는_날짜는_형식_위반이다():
    doc = _doc("| 작성일자 | 2026. 02. 30. |")

    got = _run(doc, [FieldSpec(name="작성일자", labels=("작성일자",), format="date")])

    assert len(got) == 1


# ── equals ───────────────────────────────────────────────────────────────

def test_equals_와_다르면_지적한다():
    doc = _doc("| 시험소명 | 슈어소프트테크 |")

    got = _run(doc, [FieldSpec(name="시험소명", labels=("시험소명",),
                               equals="슈어소프트테크㈜")])

    assert len(got) == 1
    assert "슈어소프트테크㈜" in got[0].message


def test_equals_는_공백을_무시한다():
    doc = _doc("| 시험소명 | 슈어소프트테크 ㈜ |")

    got = _run(doc, [FieldSpec(name="시험소명", labels=("시험소명",),
                               equals="슈어소프트테크㈜")])

    assert got == []


# ── select: one ──────────────────────────────────────────────────────────

def test_하나만_고르면_통과다():
    doc = _doc("| 시험 방법 | ■ 고정 시험실 | □ 현장 시험 |")

    got = _run(doc, [FieldSpec(name="시험방법", labels=("시험 방법",),
                               source="checkbox_group", select="one",
                               options=("고정 시험실", "현장 시험"))])

    assert got == []


def test_아무것도_안_고르면_지적한다():
    doc = _doc("| 시험 방법 | □ 고정 시험실 | □ 현장 시험 |")

    got = _run(doc, [FieldSpec(name="시험방법", labels=("시험 방법",),
                               source="checkbox_group", select="one",
                               options=("고정 시험실", "현장 시험"))])

    assert len(got) == 1
    assert got[0].severity is Severity.MAJOR


def test_둘_이상_고르면_지적한다():
    doc = _doc("| 시험 방법 | ■ 고정 시험실 | ■ 현장 시험 |")

    got = _run(doc, [FieldSpec(name="시험방법", labels=("시험 방법",),
                               source="checkbox_group", select="one",
                               options=("고정 시험실", "현장 시험"))])

    assert len(got) == 1
    assert "하나" in got[0].message


# ── fixed_text ───────────────────────────────────────────────────────────

def test_고정_문구가_있으면_통과다():
    doc = _doc("본문", "슈어소프트테크㈜", "031-606-2000")

    got = _run(doc, fixed_text=["슈어소프트테크㈜", "031-606-2000"])

    assert got == []


def test_고정_문구가_없으면_지적한다():
    doc = _doc("본문", "슈어소프트테크㈜")

    got = _run(doc, fixed_text=["슈어소프트테크㈜", "031-606-2000"])

    assert len(got) == 1
    assert "031-606-2000" in got[0].message


def test_고정_문구는_공백_차이를_무시한다():
    """PDF 추출은 자간 때문에 공백을 흘린다. 공백으로 지적하면 소음이 된다."""
    doc = _doc("1. 이 성적서는  시험의뢰인에 의해 제공된 시료에 한정됩니다.")

    got = _run(doc, fixed_text=["1. 이 성적서는 시험의뢰인에 의해 제공된 시료에 한정됩니다."])

    assert got == []


# ── signatures ───────────────────────────────────────────────────────────

def test_서명란이_미작성이면_지적한다():
    """실측: 샘플 갑지가 `성명                          (서명)` 그대로였다."""
    doc = _doc("| 시험실무자 | 성명                (서명) |")

    got = _run(doc, signatures=[SignatureSpec(role="시험실무자", placeholder="성명")])

    assert len(got) == 1
    assert got[0].severity is Severity.MAJOR
    assert "시험실무자" in got[0].message


def test_서명란이_작성됐으면_통과다():
    doc = _doc("| 시험실무자 | 홍길동                (서명) |")

    got = _run(doc, signatures=[SignatureSpec(role="시험실무자", placeholder="성명")])

    assert got == []


def test_서명란_자체를_못_찾으면_미검토다():
    doc = _doc("| 기술책임자 | 홍길동 |")

    got = _run(doc, signatures=[SignatureSpec(role="시험실무자", placeholder="성명")])

    assert len(got) == 1
    assert got[0].unreviewed is True


# ── 지적 위치 ────────────────────────────────────────────────────────────

def test_지적에_위치가_실린다():
    """리포트가 하이라이트하려면 어느 표 몇 행인지 알아야 한다."""
    doc = _doc("| 머리 |", "| 성적서번호 |  |")

    got = _run(doc, [FieldSpec(name="성적서번호", labels=("성적서번호",), required=True)])

    assert got[0].anchor.section == "표1 2행"


def test_필드마다_rule_id_가_붙는다():
    doc = _doc("| 성적서번호 |  |")

    got = _run(doc, [FieldSpec(name="성적서번호", labels=("성적서번호",), required=True)])

    assert got[0].rule_id == "F-성적서번호"


def test_가로_표_서명란도_읽는다():
    """실측: 갑지의 서명란은 세로가 아니라 가로다.

        | 확인 | 시험실무자 | 기술책임자 |
        |      | 성명  (서명) | 성명  (서명) |

    at 을 못 주면 시험실무자의 값으로 옆 칸('기술책임자')을 읽어 **미작성을
    놓친다**. 실문서로 돌려보고서야 드러났다.
    """
    doc = _doc("| 확인 | 시험실무자 | 기술책임자 |",
               "|  | 성명                (서명) | 성명                (서명) |")

    got = _run(doc, signatures=[
        SignatureSpec(role="시험실무자", placeholder="성명", at="below"),
        SignatureSpec(role="기술책임자", placeholder="성명", at="below")])

    assert sorted(f.rule_id for f in got) == ["F-서명-기술책임자", "F-서명-시험실무자"]
    assert all(not f.unreviewed for f in got)


def test_가로_표_서명란이_작성됐으면_통과다():
    doc = _doc("| 확인 | 시험실무자 | 기술책임자 |",
               "|  | 홍길동                (서명) | 김철수                (서명) |")

    got = _run(doc, signatures=[
        SignatureSpec(role="시험실무자", placeholder="성명", at="below"),
        SignatureSpec(role="기술책임자", placeholder="성명", at="below")])

    assert got == []


# ── 표의 모든 행 (table_rows) ────────────────────────────────────────────

def _table(*lines):
    return _doc(*lines)


def test_필수_열이_빈_행을_지적한다():
    """EV2 항목 21 — 개정기록 표에 개정번호·개정일자·작성자·변경 내용·승인 정보가
    누락 없이 작성되었는지."""
    doc = _table("| 개정번호 | 일시 | 담당자 |",
                 "| 00 | 2021. 06. 21. | 정연석 |",
                 "| 01 |  | 정연석 |")

    got = _run(doc, [FieldSpec(name="개정기록", source="table_rows",
                               columns=("개정번호", "일시", "담당자"),
                               required_columns=("일시", "담당자"))])

    assert len(got) == 1
    assert got[0].severity is Severity.MAJOR
    assert "일시" in got[0].message
    assert got[0].anchor.section == "표1 3행"


def test_행마다_따로_지적한다():
    doc = _table("| 개정번호 | 담당자 |", "| 00 |  |", "| 01 |  |")

    got = _run(doc, [FieldSpec(name="개정기록", source="table_rows",
                               columns=("개정번호", "담당자"),
                               required_columns=("담당자",))])

    assert [f.anchor.section for f in got] == ["표1 2행", "표1 3행"]


def test_다_채워져_있으면_지적하지_않는다():
    doc = _table("| 개정번호 | 담당자 |", "| 00 | 정연석 |")

    got = _run(doc, [FieldSpec(name="개정기록", source="table_rows",
                               columns=("개정번호", "담당자"),
                               required_columns=("담당자",))])

    assert got == []


def test_표를_못_찾으면_미검토다():
    """빈 표와 없는 표를 섞으면 안 된다. 후자는 열 이름이 문서와 어긋난 것이라
    사람이 봐야 한다."""
    doc = _table("| 다른 | 표 |", "| a | b |")

    got = _run(doc, [FieldSpec(name="개정기록", source="table_rows",
                               columns=("개정번호", "담당자"), required=True)])

    assert len(got) == 1
    assert got[0].unreviewed is True


def test_표는_있는데_행이_없으면_지적이다():
    """머리행만 있고 값이 한 줄도 없다 — 문서 결함이지 검사 못 한 게 아니다."""
    doc = _table("| 개정번호 | 담당자 |")

    got = _run(doc, [FieldSpec(name="개정기록", source="table_rows",
                               columns=("개정번호", "담당자"), required=True)])

    assert len(got) == 1
    assert got[0].unreviewed is False
    assert "비어" in got[0].message


def test_required_가_아니면_빈_표를_지적하지_않는다():
    doc = _table("| 개정번호 | 담당자 |")

    got = _run(doc, [FieldSpec(name="개정기록", source="table_rows",
                               columns=("개정번호", "담당자"))])

    assert got == []


# ── 근거 ─────────────────────────────────────────────────────────────────
# 근거가 없으면 뷰어가 PDF 에서 짚을 자리를 못 찾는다. 번호도 형광펜도 안 생기고,
# 카드를 눌러도 아무 데도 안 간다. 실측: `'성적서번호' 의 형식이 규칙과 다릅니다:
# SST-26-999C01` 이 근거 0개였다. 값은 그 칸에서 읽어온 글자라 그대로 인용이 된다.


def test_형식_지적은_읽어온_값을_근거로_든다():
    doc = _doc("| 성적서번호 | SST-26-999C01 |")

    got = _run(doc, [FieldSpec(name="성적서번호", labels=("성적서번호",),
                               pattern=r"SST-\d{2}-\d{3}-C\d{2}", required=True)])

    assert len(got) == 1
    assert [e.quote for e in got[0].evidence] == \
        ["성적서번호 | SST-26-999C01"]


def test_빈_칸은_라벨을_근거로_든다():
    """값이 없으니 인용할 값도 없다. 검토자가 채워야 할 라벨 칸을 짚는다."""
    doc = _doc("| 기관명 |  |")

    got = _run(doc, [FieldSpec(name="의뢰기관명", labels=("기관명",), required=True)])

    assert [e.quote for e in got[0].evidence] == ["기관명"]


def test_날짜_형식_지적도_값을_근거로_든다():
    doc = _doc("| 접수일 | 2026-01-05 |")

    got = _run(doc, [FieldSpec(name="접수일", labels=("접수일",),
                               format="date", required=True)])

    assert len(got) == 1
    assert [e.quote for e in got[0].evidence] == ["접수일 | 2026-01-05"]


def test_서명_지적도_근거를_든다():
    """근거가 없으면 뷰어가 짚을 자리를 못 찾는다 — 번호도 형광펜도 안 생긴다.

    자리표시자(`성명 (서명)`)가 아니라 **역할 라벨**을 짚는다. 자리표시자는 여러
    서명란에 똑같이 있어 엉뚱한 줄로 간다.
    """
    doc = _doc("| 시험실무자 | 성명                (서명) |")

    got = _run(doc, signatures=[SignatureSpec(role="시험실무자",
                                              placeholder="성명", at="right")])

    assert len(got) == 1 and "작성되지 않았습니다" in got[0].message
    assert [e.quote for e in got[0].evidence] == ["시험실무자"]
