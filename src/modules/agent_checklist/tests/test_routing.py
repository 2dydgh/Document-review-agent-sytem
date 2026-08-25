from modules.agent_checklist import checkers_for, mode_for
from modules.agent_quality import ChunkCriteriaChecker
from modules.preset import Criterion


def test_rule_criterion_routes_by_the_check_it_names():
    from modules.agent_format import CompletenessChecker

    cks = checkers_for([Criterion(no="9", text="필수 장절", agent="형식·완전성",
                                  check="required_sections")])
    assert [type(c) for c in cks] == [CompletenessChecker]


def test_rule_criterion_without_a_check_gets_no_checker():
    """agent 라벨만으로는 라우팅하지 않는다.

    라벨은 여섯 개인데 기준은 팀마다 수십 개다. 라벨로 이으면 EV2 의 규칙 기준
    15개가 검사기 두 개에 매달려, 그 둘의 지적이 15개 전부에 복사됐다.
    """
    assert checkers_for([Criterion(no="1", text="파일명 규칙",
                                   agent="형식·완전성")]) == []


def test_unknown_check_name_is_not_guessed():
    """오타를 조용히 넘기면 그 기준이 검사되지 않은 채 통과한다."""
    assert checkers_for([Criterion(no="1", text="a", agent="형식·완전성",
                                   check="plceholder")]) == []


def test_same_check_is_not_built_twice():
    # 기준 둘이 같은 검사를 대면 한 번만 만든다 — 두 번 돌리면 낭비이자
    # 같은 지적이 두 번 뜬다.
    cks = checkers_for([Criterion(no="1", text="a", agent="형식·완전성",
                                  check="placeholder"),
                        Criterion(no="2", text="b", agent="형식·완전성",
                                  check="placeholder")])
    assert len(cks) == 1


def test_quality_agent_routes_to_consistency():
    cks = checkers_for([Criterion(no="1", text="용어 흔들림", agent="표현·내용품질")])
    assert len(cks) == 1


def test_slice_mode_criteria_go_into_one_checker():
    # 조각 기준이 여럿이어도 검사기는 하나다 — 청크마다 묶어 묻기 위함이다.
    crits = [Criterion(no="15", text="오탈자", agent="표현·내용품질"),
             Criterion(no="20", text="모호한 표현", agent="표현·내용품질")]
    cks = checkers_for(crits)

    consistency = [c for c in cks if isinstance(c, ChunkCriteriaChecker)]
    assert len(consistency) == 1
    assert [c.no for c in consistency[0].criteria] == ["15", "20"]


def test_empty_agent_gives_no_checker():
    assert checkers_for([Criterion(no="1", text="아무거나", agent="")]) == []


def test_rule_checkers_are_keyed_by_check_name():
    """이름당 검사기 하나 — 그래야 그 검사기의 지적이 어느 기준의 것인지 안다."""
    from modules.agent_checklist import rule_checkers

    got = rule_checkers([Criterion(no="9", agent="형식·완전성",
                                   check="required_sections"),
                         Criterion(no="12", agent="형식·완전성",
                                   check="placeholder"),
                         Criterion(no="13", agent="형식·완전성")])
    assert set(got) == {"required_sections", "placeholder"}


def test_trace_agent_routes_to_whole_doc_checker():
    # 정합성·추적성은 LLM-문서다 — 멀리 떨어진 두 곳을 맞대야 해서 조각으로는
    # 원리상 못 잡는다(3쪽 표 제목 vs 40쪽 본문 참조).
    from modules.agent_quality import WholeDocCriteriaChecker

    cks = checkers_for([Criterion(no="1", text="추적성", agent="정합성·추적성")])
    assert [type(c) for c in cks] == [WholeDocCriteriaChecker]


def test_slice_and_doc_criteria_get_separate_checkers():
    # 둘이 같은 타입이면 orchestrator 의 type 별 수집에서 하나가 다른 하나를 덮는다.
    from modules.agent_quality import ChunkCriteriaChecker, WholeDocCriteriaChecker

    cks = checkers_for([Criterion(no="1", text="오탈자", agent="표현·내용품질"),
                        Criterion(no="2", text="표·그림", agent="정합성·추적성")])
    kinds = {type(c) for c in cks}
    assert kinds == {ChunkCriteriaChecker, WholeDocCriteriaChecker}


def test_agent_without_checker_gives_none():
    # 생성·이력은 사람 몫 — 검사기가 없다.
    assert checkers_for([Criterion(no="2", text="이력", agent="검토의견·이력")]) == []


def test_person_mode_produces_no_checker():
    assert checkers_for([Criterion(no="14", text="용어 정의 생성",
                                   agent="문서작성·생성")]) == []


def test_no_keyword_guessing():
    # text 에 "일관"이 있어도 agent 가 비면 라우팅 안 한다(키워드 추측 없음).
    assert checkers_for([Criterion(no="1", text="일관성 점검", agent="")]) == []


# ── mode — 기준 하나를 어떻게 검사할 것인가 ──────────────────────────────
# checkers_for 가 "어느 검사기를 켤지"라면 mode_for 는 "어떻게 물을지"다.
# 규칙은 LLM 없이, 조각은 청크마다 묶어 묻고, 전체는 문서를 통째로, 사람은
# 검사기가 없어 확인 목록으로만 나간다.

def test_mode_falls_back_to_agent_label():
    # 기준에 mode 가 없으면 agent 라벨이 기본값을 정한다.
    assert mode_for(Criterion(no="1", agent="형식·완전성")) == "규칙"
    assert mode_for(Criterion(no="2", agent="표현·내용품질")) == "LLM-조각"
    assert mode_for(Criterion(no="3", agent="정합성·추적성")) == "LLM-문서"
    assert mode_for(Criterion(no="4", agent="표준·체크리스트")) == "LLM-조각"


def test_mode_on_criterion_overrides_agent_default():
    # 데이터가 코드보다 세다 — yaml 에 적힌 mode 가 라벨 기본값을 덮는다.
    c = Criterion(no="13", agent="표현·내용품질", mode="LLM-문서")
    assert mode_for(c) == "LLM-문서"


def test_unknown_or_missing_agent_is_person():
    # 검사기가 없는 agent 와 미지정은 사람 몫이다. 추측하지 않는다.
    assert mode_for(Criterion(no="5", agent="문서작성·생성")) == "사람"
    assert mode_for(Criterion(no="6", agent="검토의견·이력")) == "사람"
    assert mode_for(Criterion(no="7", agent="")) == "사람"
    assert mode_for(Criterion(no="8", agent="없는라벨")) == "사람"


def test_invalid_mode_value_is_rejected_not_guessed():
    # 오타를 조용히 통과시키면 그 기준이 검사된 것처럼 보인다.
    c = Criterion(no="9", agent="표현·내용품질", mode="쪼각")
    assert mode_for(c) == "사람"


def test_mode_always_returns_a_known_value():
    # 반환값이 어휘 밖으로 새면 아래 라우팅이 조용히 아무것도 안 하게 된다.
    from modules.preset import MODES

    for agent in ("형식·완전성", "표현·내용품질", "정합성·추적성",
                  "표준·체크리스트", "문서작성·생성", "검토의견·이력", "", "없는라벨"):
        assert mode_for(Criterion(no="x", agent=agent)) in MODES


# ── 문서 검토 항목이 아닌 계열 ──────────────────────────────────────────────
# AI시험인증1팀 기준 13개 중 6개가 `문서작성·생성` 이다 — 수식 도출 · 시험환경
# 이미지 · 용어 설명 · 표 그리기 · 코드 수정. 문서를 **보는** 검사가 아니라
# **만들어 주는** 기능이라, 검토 결과 화면에 판정이 있을 수 없다.
#
# 예전엔 이것들이 "사람 확인 필요" 로 떨어졌다. 그러면 검토자가 "이 문서에서
# 사람이 봐야 할 게 19건" 으로 읽는데 그중 6건은 자기 일이 아니다.

def test_생성_이력_계열은_검토_항목이_아니다():
    from modules.agent_checklist import out_of_scope

    for agent in ("문서작성·생성", "검토의견·이력"):
        assert out_of_scope(
            Criterion(no="1", text="x", agent=agent)
        ), f"{agent} 를 검토 항목으로 센다"


def test_검사하는_계열은_검토_항목이다():
    from modules.agent_checklist import out_of_scope

    for agent in ("형식·완전성", "표현·내용품질", "정합성·추적성", "표준·체크리스트"):
        assert not out_of_scope(
            Criterion(no="1", text="x", agent=agent)
        ), f"{agent} 가 검토에서 빠졌다"


def test_라벨이_없으면_검토_항목으로_둔다():
    """모르는 것을 조용히 빼지 않는다 — 빼면 검사된 척이 된다."""
    from modules.agent_checklist import out_of_scope

    assert not out_of_scope(Criterion(no="1", text="x", agent=""))
    assert not out_of_scope(Criterion(no="1", text="x", agent="모르는라벨"))
