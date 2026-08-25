"""기준이 이끄는 단일 문서 검토.

기준마다 mode 가 정해지고(규칙·조각·전체·사람), 조각 기준은 본문이 프롬프트에
실려 기준별 판정이 돌아온다. 지적은 **그 기준에만** 붙는다 — 예전에는 같은 agent
라벨의 기준 둘이 검사기의 지적을 통째로 공유해 건수가 늘 똑같았다.

"기본 검토" 합성 항목은 없앴다. 체크리스트와 무관하게 늘 도는 검사기를 두면,
기준 7개 중 0개가 검사되는 팀에서도 지적이 나와 검사된 것처럼 보인다. 그 자리는
공통 프리셋(common.yaml)이 가져갔고, 호출부가 items 에 합쳐 넘긴다.
"""
from dataclasses import dataclass

from modules.shared import Config, ReviewConfig
from app.orchestrator import review_with_checklist


@dataclass
class _Item:
    no: str = ""
    text: str = ""
    group: str = ""
    note: str = ""
    agent: str = ""    # 관점 라벨. mode 기본값을 정한다(라우팅은 이걸로 안 한다)
    mode: str = ""     # 비면 agent 라벨이 기본값을 정한다
    check: str = ""    # mode 가 규칙일 때 어느 검사가 이 기준을 보는가
    params: dict = None   # 그 검사에 줄 값(볼 칸 이름 등)

    def __post_init__(self):
        self.params = self.params or {}


@dataclass
class _Checklist:
    items: list


def _cfg():
    return Config(llm_provider="echo", chunk_max_chars=4000,
                  review=ReviewConfig("generic"))


def _write(tmp_path, text):
    p = tmp_path / "doc.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_unmapped_items_are_marked_manual(tmp_path):
    """어느 검사기에도 안 걸리는 기준은 사람 몫이다. 합성 항목은 만들지 않는다."""
    cl = _Checklist(items=[_Item(no="1", text="서명 페이지 스캔 여부"),
                           _Item(no="2", text="책갈피 작동 여부")])
    res = review_with_checklist(_write(tmp_path, "# 문서\n내용"), cl, _cfg())

    assert [i.status for i in res.items] == ["manual", "manual"]
    assert all(i.findings == [] for i in res.items)
    # 기준에서 나오지 않은 항목("기본 검토")을 지어내지 않는다.
    assert all(i.no != "" for i in res.items)


def test_consistency_item_with_echo_llm_is_unreviewed_not_clean(tmp_path):
    """EchoLLM 은 빈 응답이라 판정을 못 낸다 → clean 도 flagged 도 아니다.

    clean 으로 두면 검사하지 않은 항목이 "이상 없음"으로 보이고, flagged 로 두면
    "문제 발견"으로 보인다. 둘 다 거짓이라 별도 상태로 낸다.

    **호출 전부가 무응답이면 `noanswer`** 다(EchoLLM 이 그렇다). 응답은 왔는데 이
    기준 판정만 안 온 경우(`unreviewed`)와 가른다 — 앞은 서버·설정을 고쳐야 하고
    뒤는 다시 돌리면 나올 수 있어, 검토자가 할 일이 다르다.
    """
    cl = _Checklist(items=[_Item(no="1", text="용어가 일관되게 쓰였는가",
                                 agent="표현·내용품질")])
    res = review_with_checklist(_write(tmp_path, "# 문서\n본문 한 줄"), cl, _cfg())

    got = next(i for i in res.items if i.no == "1")
    assert got.status == "noanswer"
    assert got.status not in ("clean", "flagged"), "검사 못 한 것이 판정처럼 보인다"
    assert "답하지 않아" in got.note, "왜 판정이 없는지 항목이 말해주지 않는다"


def test_review_stage_emits_a_plan_for_the_progress_lanes(tmp_path):
    """review 이벤트에 plan 이 실려야 진행 화면이 레인을 그린다.

    안 실리면 화면은 "검토를 준비하는 중"만 띄우다 결과로 튄다(회귀 방지).
    """
    cl = _Checklist(items=[_Item(no="1", text="용어가 일관되게 쓰였는가",
                                 agent="표현·내용품질")])
    events = []
    review_with_checklist(_write(tmp_path, "# 문서\n본문 한 줄"), cl, _cfg(),
                          on_progress=events.append)

    with_plan = [e for e in events
                 if e.get("key") == "review" and e.get("status") == "running"
                 and "plan" in e]
    assert len(with_plan) == 1, "review running 이벤트에 plan 이 정확히 한 번 실려야 한다"
    assert with_plan[0]["plan"], "plan 은 비어 있으면 안 된다"


def test_rule_mode_criterion_gets_the_check_it_names(tmp_path):
    """규칙 기준은 **자기가 이름을 댄** 검사의 지적을 받는다. LLM 없이 돈다."""
    cl = _Checklist(items=[_Item(no="1", text="미작성 표시가 남아 있는가",
                                 agent="형식·완전성", check="placeholder")])
    res = review_with_checklist(_write(tmp_path, "# 문서\nTBD\n본문"), cl, _cfg())

    item = next(i for i in res.items if i.no == "1")
    assert item.status == "flagged"
    assert item.findings != []


def test_parser_warnings_become_unreviewed_info_findings(tmp_path, monkeypatch):
    """review_document 와 같은 계약: parser_warnings 는 어느 항목에도 안 붙고

    검토 findings 에 INFO unreviewed 로만 실린다(체크리스트 항목이 아니라
    파이프라인에 대한 보고라서 image_findings 와 같은 취급).
    """
    from modules.doc_parser import RawDoc

    def fake_load_document(path):
        return RawDoc(source_path=str(path), text="# 문서\n내용", meta={
            "format": "docx", "parser": "trkim",
            "parser_warnings": ["trkim 파서 경로: 표 글꼴 검사·그림 해석은 "
                                "메타 미지원으로 수행되지 않습니다"],
        })

    monkeypatch.setattr("app.orchestrator.load_document", fake_load_document)
    cl = _Checklist(items=[_Item(no="1", text="서명 스캔")])
    res = review_with_checklist(tmp_path / "d.docx", cl, _cfg())

    parser_info = [f for f in res.findings if f.checker == "parser"]
    assert len(parser_info) == 1
    assert parser_info[0].unreviewed is True
    assert "표 글꼴 검사" in parser_info[0].message
    # 어느 체크리스트 항목에도 붙지 않는다(파이프라인 보고).
    assert all(f.checker != "parser" for i in res.items for f in i.findings)


def test_no_synthetic_base_item_is_created(tmp_path):
    """체크리스트가 안 걸리는 항목뿐이면 지적도 없어야 한다.

    예전에는 base_checkers 가 늘 돌아 "TBD (기본 검토)" 항목이 flagged 로 떴다.
    기준 하나도 그것을 요구하지 않았는데 검사된 것처럼 보이는 것이 문제였다.
    """
    cl = _Checklist(items=[_Item(no="1", text="서명 스캔")])
    res = review_with_checklist(_write(tmp_path, "# 문서\nTBD\n본문 한 줄"), cl, _cfg())

    assert [i.status for i in res.items] == ["manual"]
    assert all("기본 검토" not in i.text for i in res.items)
    assert res.findings == []


def test_two_criteria_same_agent_get_different_findings(tmp_path, monkeypatch):
    """같은 agent 라벨의 기준 둘이 서로 다른 지적을 받는다.

    지금까지는 둘 다 그 검사기의 지적 전부를 통째로 받아, 오탈자 기준 아래에
    모호성 지적이 뜨고 둘의 건수가 똑같았다. 화면이 사실과 달랐던 자리다.
    """
    import json

    from modules.llm_client import Response

    class _LLM:
        """기준 15 는 위반, 20 은 통과로 답한다."""

        def complete(self, prompt, **opts):
            return Response(text=json.dumps({"results": [
                {"no": "15", "verdict": "위반", "issue": "오탈자가 있다",
                 "quotes": ["본문 한 줄"]},
                {"no": "20", "verdict": "통과"},
            ]}, ensure_ascii=False))

        def chat(self, messages, **opts):
            raise AssertionError("표현 점검은 complete() 를 쓴다")

    cl = _Checklist(items=[_Item(no="15", text="오탈자", agent="표현·내용품질"),
                           _Item(no="20", text="모호 표현", agent="표현·내용품질")])
    monkeypatch.setattr("app.orchestrator.build_llm", lambda cfg: _LLM())
    res = review_with_checklist(_write(tmp_path, "# 문서\n본문 한 줄"), cl, _cfg())
    by = {i.no: i for i in res.items}

    assert by["15"].status == "flagged"
    assert [f.message for f in by["15"].findings] == ["오탈자가 있다"]
    # 물어봤고 통과했다 — 안 물어본 unreviewed 와 다른 말이다.
    assert by["20"].status == "clean"
    assert by["20"].findings == []


def test_one_checker_runs_once_even_for_many_criteria(tmp_path, monkeypatch):
    """조각 기준이 여럿이어도 검사기는 하나다 — 청크를 기준 수만큼 다시 읽지 않는다."""
    import json

    from modules.llm_client import Response

    calls = {"n": 0}

    class _LLM:
        def complete(self, prompt, **opts):
            calls["n"] += 1
            # 한 프롬프트에 기준 둘이 함께 실린다.
            assert "No.1" in prompt and "No.2" in prompt
            return Response(text=json.dumps({"results": [
                {"no": "1", "verdict": "통과"}, {"no": "2", "verdict": "통과"}]}))

        def chat(self, messages, **opts):
            raise AssertionError("표현 점검은 complete() 를 쓴다")

    cl = _Checklist(items=[_Item(no="1", text="용어 A", agent="표현·내용품질"),
                           _Item(no="2", text="용어 B", agent="표현·내용품질")])
    monkeypatch.setattr("app.orchestrator.build_llm", lambda cfg: _LLM())
    res = review_with_checklist(_write(tmp_path, "# 문서\n본문"), cl, _cfg())

    assert calls["n"] == 1
    assert all(i.status == "clean" for i in res.items)


def test_rule_criterion_without_a_check_falls_to_manual(tmp_path):
    """"규칙"이라고 적혀 있어도 검사할 규칙이 없으면 사람 몫이다.

    예전에는 agent 라벨로 이어서, 규칙 검사기 둘이 낸 지적이 그 라벨을 단 기준
    전부에 복사됐다(EV2 는 15개). TBD 하나가 열다섯 건으로 보이고, 실제로는
    검사되지 않은 열네 개가 "검사됨"으로 표시됐다.
    """
    cl = _Checklist(items=[
        _Item(no="1", text="미작성 표시", agent="형식·완전성", check="placeholder"),
        _Item(no="2", text="PDF 책갈피 구조", agent="형식·완전성"),
    ])
    res = review_with_checklist(_write(tmp_path, "# 문서\nTBD\n본문"), cl, _cfg())

    got = {i.no: i for i in res.items}
    assert got["1"].status == "flagged" and got["1"].findings != []
    # 검사기가 없는 쪽은 지적을 물려받지 않는다. 왜 수동인지도 말해 준다.
    assert got["2"].status == "manual" and got["2"].findings == []
    assert "검사하는 규칙이 아직 없습니다" in got["2"].note


def test_two_field_presence_criteria_do_not_share_findings(tmp_path):
    """같은 검사(field_presence)를 대도 보는 칸이 다르면 지적도 갈린다.

    EV2 20(표지 결재란)과 21(개정기록)이 실제로 그 모양이다. 검사기 한 벌을
    나눠 가지면 표지 지적이 개정기록 항목에도 뜬다 — 이 리팩터링이 없애려던
    바로 그 모습이다.
    """
    from modules.doc_parser import FieldSpec

    specs = [FieldSpec(name="작성자", labels=("작성자 :",), required=True),
             FieldSpec(name="발행일", labels=("발행일 :",), required=True)]
    cl = _Checklist(items=[
        _Item(no="20", text="표지 정보", agent="형식·완전성", mode="규칙",
              check="field_presence", params={"fields": ["작성자"]}),
        _Item(no="21", text="발행 정보", agent="형식·완전성", mode="규칙",
              check="field_presence", params={"fields": ["발행일"]}),
    ])
    doc = _write(tmp_path, "# 문서\n\n| 작성자 : |  | 발행일 : | 2026. 01. 02. |")
    res = review_with_checklist(doc, cl, _cfg(), field_specs=specs)

    got = {i.no: i for i in res.items}
    # 작성자 칸이 비었다 → 20번만 지적. 발행일은 채워져 있다 → 21번은 통과.
    assert got["20"].status == "flagged"
    assert all("작성자" in f.message for f in got["20"].findings)
    assert got["21"].status == "clean" and got["21"].findings == []


def test_manual_says_whether_a_human_chose_it_or_nobody_did(tmp_path):
    """"사람이 그렇게 정했다" 와 "아무도 안 정했다" 는 다르다.

    업로드 체크리스트(엑셀)에는 mode 칸이 아예 없어 전부 사람 몫으로 떨어지는데,
    화면은 그것들까지 "이 기준은 문서만으로 판정할 수 없습니다" 라고 말했다.
    "PDF 필드오류 문자열이 있는가" 처럼 기계가 그대로 볼 수 있는 항목에도 그랬다 —
    검사기를 안 만든 것을 못 만드는 것처럼 말하는 것이라 거짓말이다.
    """
    cl = _Checklist(items=[
        _Item(no="1", text="서명 페이지 스캔 여부", mode="사람"),   # 사람이 정했다
        _Item(no="2", text="PDF 필드오류 문자열 확인"),            # 아무도 안 정했다
    ])
    got = {i.no: i for i in review_with_checklist(
        _write(tmp_path, "# 문서\n본문"), cl, _cfg()).items}

    assert got["1"].status == "manual" and got["1"].mode_declared is True
    assert got["2"].status == "manual" and got["2"].mode_declared is False


def test_rule_without_its_criterion_value_becomes_a_human_check(tmp_path):
    """검사할 규칙은 있는데 **잴 값**을 기준이 안 주면 사람 몫이다.

    예전에는 검사기를 만들어 돌리고 "필수 절 목록이 검토 기준에 없어 …" 를 지적
    카드로 냈다. 그건 문서 이야기가 아니라 기준이 비었다는 이야기라 지적 목록에
    있을 것이 아니고, 목록을 안 준 팀(일곱 팀)의 모든 검토에 매번 떴다.
    값을 적은 팀에서는 그대로 자동으로 돈다(아래 두 번째 단언).
    """
    cl = _Checklist(items=[
        _Item(no="1", text="필수 절이 다 있어야 한다",
              agent="형식·완전성", mode="규칙", check="required_sections"),
    ])
    doc = _write(tmp_path, "# 문서\n## 2.0 Scope\n본문")

    res = review_with_checklist(doc, cl, _cfg())
    got = res.items[0]
    assert got.status == "manual", "값이 없으면 사람 몫"
    assert "자동으로 검사하지 못합니다" in got.note
    assert res.findings == [], "기준이 비었다는 말을 지적 카드로 내지 않는다"

    cfg = _cfg()
    cfg.review.required_sections = ["1.0 Purpose", "2.0 Scope"]
    got2 = review_with_checklist(doc, cl, cfg).items[0]
    assert got2.status == "flagged", "값이 있으면 그대로 자동으로 돈다"
