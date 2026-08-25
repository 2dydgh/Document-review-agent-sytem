"""한 값이 N곳에서 같아야 하는 대조 (문서 간 md §3).

쌍으로 대조하면 지적이 부풀어 오른다. 의뢰번호는 18쌍 중 12쌍에 등장해서, 하나가
틀리면 **같은 지적이 12번** 나온다. md §3 이 이미 답을 줬다 —
"2개 문서만으로는 부분 판정만 가능하다. 아래는 전체 검토에서 반드시 다시 확인한다."

    성적서번호 3곳 · 시험환경정보 5곳 · 시험합격기준 4곳 · 시험항목명 4곳
    제품명·버전 6곳 · 의뢰번호 전 문서 · 시험일자 3곳

그래서 **지적은 1건이고 근거가 N개**다. 그리고 맞은 곳까지 남긴다 — 검토자는
"6곳 다 봤고 1곳이 틀렸다"를 알아야지 "1곳이 틀렸다"만 알면 안 된다.
"""
from modules.agent_trace import CaseWideRule, compare_case_wide
from modules.doc_parser import FieldValue
from modules.shared import Anchor, Severity


def _v(name, value, section="표1 1행", found=True, label=""):
    return FieldValue(name=name, value=value, anchor=Anchor(None, section),
                      found=found, matched_label=label,
                      source_quote=f"{label} | {value}" if label else "")


def _rule(**kw):
    kw.setdefault("id", "W-의뢰번호")
    kw.setdefault("field", "의뢰번호")
    kw.setdefault("outputs", ("의뢰서", "계획서", "갑지"))
    return CaseWideRule(**kw)


def _vals(**by_output):
    return {k: {"의뢰번호": _v("의뢰번호", v)} for k, v in by_output.items()}


def test_전부_같으면_지적하지_않는다():
    got = compare_case_wide(
        _vals(의뢰서="SST-26-999", 계획서="SST-26-999", 갑지="SST-26-999"), _rule())

    assert got.status == "일치"
    assert got.finding is None


def test_하나만_달라도_지적한다():
    got = compare_case_wide(
        _vals(의뢰서="SST-26-999", 계획서="SST-26-999", 갑지="SST-26-998"), _rule())

    assert got.status == "불일치"
    assert got.finding.severity is Severity.MAJOR
    assert got.finding.rule_id == "W-의뢰번호"


def test_지적은_N건이_아니라_1건이고_근거가_N개다():
    """쌍마다 대조하면 같은 지적이 12번 난다. 그걸 막으려고 이 층이 있다."""
    got = compare_case_wide(
        _vals(의뢰서="SST-26-999", 계획서="SST-26-999", 갑지="SST-26-998"), _rule())

    assert [e.quote for e in got.finding.evidence] == \
        ["SST-26-999", "SST-26-999", "SST-26-998"]


def test_전체대조도_표_라벨을_근거_문맥으로_보존한다():
    vals = {
        "계획서": {"버전": _v("버전", "1.0", label="버전")},
        "설계서": {"버전": _v("버전", "1.0.1", label="버전")},
    }

    got = compare_case_wide(vals, CaseWideRule(
        id="W-버전", field="버전", outputs=("계획서", "설계서")))

    assert [e.quote for e in got.finding.evidence] == ["버전 | 1.0", "버전 | 1.0.1"]
    assert [c.matched_label for c in got.cells] == ["버전", "버전"]


def test_맞은_곳도_남긴다():
    """지적만 남기면 "몇 곳을 봤고 몇 곳이 통과인지"를 알 수 없다. 리포트의
    필드 × 산출물 매트릭스가 이 cells 로 그려진다."""
    got = compare_case_wide(
        _vals(의뢰서="SST-26-999", 계획서="SST-26-999", 갑지="SST-26-999"), _rule())

    assert [(c.output, c.value) for c in got.cells] == [
        ("의뢰서", "SST-26-999"), ("계획서", "SST-26-999"), ("갑지", "SST-26-999")]
    assert all(c.present and c.found for c in got.cells)


def test_안_올라온_산출물은_미검토로_남는다():
    got = compare_case_wide(_vals(의뢰서="SST-26-999", 계획서="SST-26-999"), _rule())

    assert got.status == "미검토"
    assert got.finding.unreviewed is True
    assert "갑지" in got.finding.message
    missing = [c for c in got.cells if not c.present]
    assert [c.output for c in missing] == ["갑지"]


def test_값을_못_찾은_산출물도_미검토다():
    """라벨맵이 문서와 어긋났을 수 있다. 못 찾은 것을 빼고 "나머지는 같다"고
    판정하면 검사하지 않은 것이 통과로 보인다."""
    vals = _vals(의뢰서="SST-26-999", 계획서="SST-26-999")
    vals["갑지"] = {"의뢰번호": _v("의뢰번호", None, found=False)}

    got = compare_case_wide(vals, _rule())

    assert got.status == "미검토"
    assert [c.output for c in got.cells if c.present and not c.found] == ["갑지"]
    assert got.cells[-1].configured is True


def test_추출_규칙이_없는_것과_값을_못_찾은_것을_구분한다():
    vals = _vals(의뢰서="SST-26-999", 계획서="SST-26-999")
    vals["갑지"] = {}

    got = compare_case_wide(vals, _rule())

    assert got.cells[-1].present is True
    assert got.cells[-1].configured is False
    assert got.cells[-1].found is False


def test_문서를_못_읽어도_주입한_필드맵은_설정됨으로_남는다():
    vals = _vals(의뢰서="SST-26-999", 계획서="SST-26-999")
    vals["갑지"] = {}

    got = compare_case_wide(
        vals, _rule(), configured_fields={"갑지": {"의뢰번호"}})

    assert got.cells[-1].configured is True
    assert got.cells[-1].found is False


def test_안_올라온_것이_있어도_이미_어긋났으면_불일치다():
    """미검토가 불일치를 덮으면 안 된다 — 이미 틀린 것은 틀렸다."""
    got = compare_case_wide(
        _vals(의뢰서="SST-26-999", 계획서="SST-26-998"), _rule())

    assert got.status == "불일치"


def test_outputs_all_은_케이스의_전_산출물이다():
    got = compare_case_wide(
        _vals(의뢰서="SST-26-999", 갑지="SST-26-999"),
        _rule(outputs="all"), all_outputs=("의뢰서", "갑지"))

    assert [c.output for c in got.cells] == ["의뢰서", "갑지"]
    assert got.status == "일치"


def test_버전을_빼고_대조할_수_있다():
    """제품명은 6곳에서 같아야 하는데 갑지만 버전을 포함해 쓴다
    (문서 간 §1-5 "갑지는 버전 포함 전체, 을지는 버전 제외")."""
    vals = {"을지": {"제품명": _v("제품명", "Apple")},
            "갑지": {"제품명": _v("제품명", "Apple (Ver 1.0.1 )")}}

    got = compare_case_wide(vals, CaseWideRule(
        id="W-제품명", field="제품명", outputs=("을지", "갑지"), ignoring="version"))

    assert got.status == "일치"
    # 매트릭스에는 **원문 그대로** 남긴다 — 검토자가 실제 값을 봐야 한다.
    assert [c.value for c in got.cells] == ["Apple", "Apple (Ver 1.0.1 )"]


def test_어느_칸이_틀렸는지_표시한다():
    """매트릭스가 [제품명 × 기록서] 교차점만 붉게 칠하려면 칸마다 판정이 있어야
    한다. 화면이 다시 계산하면 버전 무시 같은 정규화가 두 곳으로 갈린다."""
    got = compare_case_wide(
        _vals(의뢰서="SST-26-999", 계획서="SST-26-999", 갑지="SST-26-998"), _rule())

    assert [(c.output, c.ok) for c in got.cells] == [
        ("의뢰서", True), ("계획서", True), ("갑지", False)]


def test_값이_동률이면_한쪽을_임의의_정답으로_삼지_않는다():
    """1:1 충돌에서 문서 순서는 어느 쪽이 맞는지 판단할 근거가 아니다."""
    got = compare_case_wide(
        _vals(의뢰서="(26.0 ± 0.6) °C", 갑지="26.0 ± 0.6 °C"),
        _rule(outputs=("의뢰서", "갑지")))

    assert got.status == "불일치"
    assert [(c.value, c.ok) for c in got.cells] == [
        ("(26.0 ± 0.6) °C", False), ("26.0 ± 0.6 °C", False)]


def test_못_본_칸은_ok_가_None_이다():
    got = compare_case_wide(_vals(의뢰서="SST-26-999", 계획서="SST-26-999"), _rule())

    assert [c.ok for c in got.cells] == [True, True, None]


def test_버전만_다른_칸은_틀린_것이_아니다():
    vals = {"을지": {"제품명": _v("제품명", "Apple")},
            "갑지": {"제품명": _v("제품명", "Apple (Ver 1.0.1 )")}}

    got = compare_case_wide(vals, CaseWideRule(
        id="W-제품명", field="제품명", outputs=("을지", "갑지"), ignoring="version"))

    assert all(c.ok for c in got.cells)
