import json

from app.registry import default_checkers
from modules.agent_format import CompletenessChecker
from modules.agent_quality import ChunkCriteriaChecker
from modules.llm_client import EchoLLM, Response
from modules.shared import Anchor, Chunk, Context, Document, Section, Severity


class _Review:
    def __init__(self, required):
        self.required_sections = required


def _doc(titles):
    secs = [Section(id=str(i), title=t, level=1, text="x",
                    anchor=Anchor(page=None, section=str(i)), children=[])
            for i, t in enumerate(titles, 1)]
    return Document(source_path="d.md", doc_type=None, sections=secs)


def test_completeness_flags_missing_required_section():
    doc = _doc(["개요"])
    ctx = Context(review=_Review(["개요", "요구사항"]), llm=EchoLLM(), chunks=[])
    findings = CompletenessChecker().check(doc, ctx)
    assert len(findings) == 1
    assert findings[0].severity == Severity.MAJOR
    assert "요구사항" in findings[0].message


def test_completeness_passes_when_all_present():
    doc = _doc(["개요", "요구사항"])
    ctx = Context(review=_Review(["개요", "요구사항"]), llm=EchoLLM(), chunks=[])
    assert CompletenessChecker().check(doc, ctx) == []


class _StubLLM:
    """지적과 함께 원문을 인용한다 — 그 인용은 아래 _quoted_doc에 실제로 있다."""

    def __init__(self, quotes=("성공률은 99% 이상이어야 한다",)):
        self._quotes = list(quotes)

    def complete(self, prompt, **opts):
        return Response(text=json.dumps(
            {"results": [{"no": "1", "verdict": "위반",
                          "issue": "모호한 표현 발견", "quotes": self._quotes}]},
            ensure_ascii=False))


def _crit(no="1", text="모호한 표현이 있는가"):
    """체커는 기준을 no·text 로만 읽는다. preset 을 끌어오지 않고 여기서 만든다."""
    from modules.preset import Criterion
    return Criterion(no=no, text=text, agent="표현·내용품질")


def _quoted_doc():
    sec = Section(id="1", title="개요", level=1,
                  text="성공률은 99% 이상이어야 한다\n응답은 빨라야 한다",
                  anchor=Anchor(page=None, section="1"), children=[])
    return Document(source_path="d.md", doc_type=None, sections=[sec])


def test_consistency_flags_issue_when_the_quote_is_in_the_document():
    doc = _quoted_doc()
    chunk = Chunk(id="1#0", text="본문", anchor=Anchor(None, "1"), section_id="1")
    ctx = Context(review=_Review([]), llm=_StubLLM(), chunks=[chunk])
    findings = ChunkCriteriaChecker(criteria=[_crit()]).check(doc, ctx)
    assert len(findings) == 1
    assert findings[0].severity == Severity.MINOR
    assert "모호한" in findings[0].message
    # 근거가 붙어야 한다 — 근거 없는 지적은 지어낸 것과 구분되지 않는다.
    assert findings[0].evidence
    assert "99%" in findings[0].evidence[0].quote


def test_consistency_drops_an_issue_whose_quote_is_not_in_the_document():
    # 모델이 그럴듯한 문장을 지어냈다. 원문에 없으므로 지적으로 올리면 안 된다.
    doc = _quoted_doc()
    chunk = Chunk(id="1#0", text="본문", anchor=Anchor(None, "1"), section_id="1")
    ctx = Context(review=_Review([]), llm=_StubLLM(quotes=["문서에 없는 지어낸 문장이다"]),
                  chunks=[chunk])
    findings = ChunkCriteriaChecker(criteria=[_crit()]).check(doc, ctx)

    assert [f for f in findings if f.severity == Severity.MINOR] == []
    # 조용히 지우면 "지적이 없다"는 거짓말이 된다. 몇 건을 버렸는지 드러낸다.
    info = [f for f in findings if f.severity == Severity.INFO]
    assert len(info) == 1
    assert "1건" in info[0].message


def test_consistency_drops_an_issue_with_no_quote_at_all():
    doc = _quoted_doc()
    chunk = Chunk(id="1#0", text="본문", anchor=Anchor(None, "1"), section_id="1")
    ctx = Context(review=_Review([]), llm=_StubLLM(quotes=[]), chunks=[chunk])
    findings = ChunkCriteriaChecker(criteria=[_crit()]).check(doc, ctx)

    assert [f for f in findings if f.severity == Severity.MINOR] == []
    assert [f for f in findings if f.severity == Severity.INFO]


def test_consistency_says_it_did_not_review_on_empty_llm():
    """빈 LLM 은 "문제 없음"이 아니라 "검사 못 함"이다.

    예전에는 빈 응답을 그냥 넘겨 0건을 냈다. 그러면 LLM 을 안 붙였을 때도, 주소를
    잘못 넣었을 때도 결과가 "지적 없음"으로 같아 검토를 통과한 것처럼 보였다.
    """
    doc = _doc(["개요"])
    chunk = Chunk(id="1#0", text="본문", anchor=Anchor(None, "1"), section_id="1")
    ctx = Context(review=_Review([]), llm=EchoLLM(), chunks=[chunk])

    findings = ChunkCriteriaChecker(criteria=[_crit()]).check(doc, ctx)

    assert not [f for f in findings if f.severity != Severity.INFO], "지적을 지어내지 않는다"
    unreviewed = [f for f in findings if f.unreviewed]
    assert len(unreviewed) == 1
    assert "수행되지 않았습니다" in unreviewed[0].message


def test_consistency_reports_progress_per_chunk():
    doc = _doc(["개요"])
    chunks = [Chunk(id=f"1#{i}", text="본문", anchor=Anchor(None, "1"), section_id="1")
              for i in range(3)]
    events = []
    ctx = Context(review=_Review([]), llm=EchoLLM(), chunks=chunks,
                  on_progress=events.append)
    ChunkCriteriaChecker(criteria=[_crit()]).check(doc, ctx)

    running = [e for e in events if e["key"] == "review" and e["status"] == "running"]
    assert [e["detail"] for e in running] == [
        # 문구에 청크가 아니라 레인 이름을 싣는다 — 화면이 이걸 그대로 그린다.
        "표현 점검 1/3 검사 중", "표현 점검 2/3 검사 중", "표현 점검 3/3 검사 중",
    ]


def test_consistency_progress_does_not_change_findings():
    doc = _quoted_doc()
    chunk = Chunk(id="1#0", text="본문", anchor=Anchor(None, "1"), section_id="1")
    events = []
    ctx = Context(review=_Review([]), llm=_StubLLM(), chunks=[chunk],
                  on_progress=events.append)
    findings = ChunkCriteriaChecker(criteria=[_crit()]).check(doc, ctx)

    # 진척 보고를 켜도 판정 로직(test_consistency_flags_issue_when_the_quote_is_in_
    # the_document)과 결과가 같아야 한다.
    assert len(findings) == 1
    assert findings[0].severity == Severity.MINOR
    assert "모호한" in findings[0].message
    assert events  # 진척을 실제로 보고했다


def test_checker_labels_dont_change_names():
    # label을 추가해도 Finding.checker와 리포트/필터가 쓰는 name은 그대로여야 한다.
    from modules.agent_format import PlaceholderChecker
    assert CompletenessChecker.name == "completeness"
    assert PlaceholderChecker.name == "completeness"
    assert ChunkCriteriaChecker.name == "consistency"


def _all_modes():
    """mode 네 가지를 모두 덮는 기준 묶음. 라우팅이 무엇을 만드는지 본다.

    규칙 기준은 **자기를 검사할 규칙의 이름을 댄다**(check). 안 대면 검사기가
    안 붙는다 — 라벨만으로 잇던 예전 방식이 기준 수십 개를 검사기 두 개에 매달아
    같은 지적을 전부에 복사했다.
    """
    from modules.preset import Criterion
    return [Criterion(no="9", text="필수 구성", agent="형식·완전성", mode="규칙",
                      check="required_sections"),
            Criterion(no="12", text="미작성 표시", agent="형식·완전성", mode="규칙",
                      check="placeholder"),
            Criterion(no="16", text="오탈자", agent="표현·내용품질", mode="LLM-조각"),
            Criterion(no="13", text="표·그림", agent="정합성·추적성", mode="LLM-문서"),
            Criterion(no="4", text="표준 적합성", agent="표준·체크리스트", mode="사람")]


def test_default_checkers_names():
    # PlaceholderChecker(TBD 검사)도 완전성 문제라 이름이 "completeness"다.
    # 문서 전체 검사기는 type 이 갈려야 해서 이름도 따로다.
    names = [c.name for c in default_checkers(_all_modes())]
    assert names == ["completeness", "completeness", "consistency",
                     "consistency_doc"]


def test_no_criteria_means_no_checking():
    """기준을 안 넘기면 규칙 검사기도 안 만든다.

    예전에는 체크리스트와 무관하게 늘 돌았다 — 기준 하나도 그걸 요구하지 않았는데
    지적이 나와 검사된 것처럼 보였다. 이제 기준이 검사를 이끈다.
    """
    from modules.agent_format import CompletenessChecker, PlaceholderChecker

    kinds = {type(c) for c in default_checkers()}
    assert CompletenessChecker not in kinds
    assert PlaceholderChecker not in kinds


def test_rule_criterion_brings_the_placeholder_check():
    from modules.agent_format import PlaceholderChecker
    assert any(isinstance(c, PlaceholderChecker)
               for c in default_checkers(_all_modes()))


def test_completeness_title_mismatch_carries_evidence():
    """절 제목이 표준과 다르다는 지적은 실제 제목 줄을 근거로 든다.

    근거가 없으면 형광펜·번호가 안 붙어 카드에서 그 자리로 갈 수 없다.
    제목은 문서에서 읽은 값이라 인용 계약(원문 실재)을 그대로 지킨다.
    """
    doc = _doc(["4.0 Definition of Terms"])
    ctx = Context(review=_Review(["4.0 Definitions and Abbreviations"]),
                  llm=EchoLLM(), chunks=[])
    findings = CompletenessChecker().check(doc, ctx)
    assert len(findings) == 1
    assert "절 제목이 표준과 다릅니다" in findings[0].message
    assert findings[0].evidence, "제목 줄이 근거로 실려야 한다"
    assert findings[0].evidence[0].quote == "4.0 Definition of Terms"
