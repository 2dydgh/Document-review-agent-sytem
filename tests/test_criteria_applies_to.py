"""`applies_to` — 기준이 어느 산출물을 볼 때만 적용되는가.

없을 때 무슨 일이 났나: AI시험인증1팀은 산출물이 10종인데 "갑지의 비고문구 4개가
그대로인가" 같은 기준이 **시험의뢰서를 검토할 때도** 화면에 떴다. 검토자는 자기 일이
아닌 항목 스무 개를 매번 눈으로 걸러야 했다.

여기서 세 가지를 못박는다.

1. 대상 문서면 평소대로 검사한다.
2. 대상이 아니면 `na`(해당없음)다. `manual`(사람이 봐야 함)과 갈라야 한다 —
   앞은 정상이고 뒤는 할 일이 남은 것이다.
3. 문서가 어느 산출물인지 **못 가렸으면** `na` 가 아니다. 모르는 것을 해당없음으로
   두면 검사된 적 없는 기준이 "정상"으로 보인다.

그리고 걸러진 기준은 **검사기에 실리지도 않아야** 한다. 결과 자리에서만 거르면
갑지 전용 기준이 이미 LLM 프롬프트에 실려 나간 뒤다.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.orchestrator import _out_of_target, review_with_checklist  # noqa: E402
from modules.agent_checklist import llm_checkers_for, rule_checkers  # noqa: E402
from modules.preset import Criterion  # noqa: E402
from modules.shared import Config, ReviewConfig  # noqa: E402


def _c(no: str, targets: list[str] | None = None, **kw) -> Criterion:
    return Criterion(no=no, text=f"기준 {no}", applies_to=list(targets or ()), **kw)


def test_no_targets_applies_everywhere() -> None:
    """applies_to 를 안 적은 기준은 문서를 가리지 않는다 (대부분이 그렇다)."""
    assert _out_of_target(_c("1"), "갑지") == ""
    assert _out_of_target(_c("1"), "") == ""


def test_matching_output_applies() -> None:
    assert _out_of_target(_c("1", ["갑지"]), "갑지") == ""
    assert _out_of_target(_c("1", ["갑지", "을지"]), "을지") == ""


def test_other_output_is_excluded_with_reason() -> None:
    why = _out_of_target(_c("1", ["갑지"]), "시험의뢰서")
    assert why, "대상이 아니면 이유를 돌려줘야 한다"
    assert "갑지" in why and "시험의뢰서" in why, (
        f"어느 문서 전용인지와 이 문서가 무엇인지를 둘 다 말해야 한다: {why}")


def test_unknown_output_is_not_silently_excluded() -> None:
    """산출물을 못 가렸으면 '해당없음'이 아니다.

    이때도 걸러지긴 하지만(검사기에 안 실린다) 이유가 다르고, 조립 계층이
    `na` 가 아니라 `manual` 로 둔다 — 사람이 직접 봐야 한다는 뜻이다.
    """
    why = _out_of_target(_c("1", ["갑지"]), "")
    assert why
    assert "가리지 못" in why or "판단하지 못" in why, (
        f"모른다는 사실이 문구에 드러나야 한다: {why}")


def test_excluded_criteria_never_reach_a_checker() -> None:
    """대상 아닌 기준은 규칙에도 LLM 에도 실리지 않는다."""
    mine = _c("A", ["갑지"], agent="형식·완전성", mode="규칙", check="abbrev")
    theirs = _c("B", ["을지"], agent="형식·완전성", mode="규칙", check="reflist")
    everyone = _c("C", agent="표현·내용품질", mode="LLM-조각")
    only_theirs = _c("D", ["을지"], agent="표현·내용품질", mode="LLM-조각")

    items = [mine, theirs, everyone, only_theirs]
    applicable = [c for c in items if not _out_of_target(c, "갑지")]

    assert {c.no for c in applicable} == {"A", "C"}

    rules = rule_checkers(applicable)
    assert set(rules) == {"abbrev"}, (
        f"을지 전용 reflist 가 갑지 검토에 실렸다: {sorted(rules)}")

    llm = llm_checkers_for(applicable)
    asked = {str(c.no) for c in llm["LLM-조각"].criteria}
    assert asked == {"C"}, f"을지 전용 기준이 프롬프트에 실렸다: {sorted(asked)}"


@pytest.mark.parametrize("raw", [None, [], ()])
def test_empty_targets_are_treated_as_all(raw) -> None:
    """yaml 에서 빈 목록으로 와도 '전부 적용'이다 — 빈 목록을 '아무 문서도 아님'
    으로 읽으면 그 기준이 어디서도 안 돈다."""
    c = Criterion(no="1", text="t")
    c.applies_to = raw  # type: ignore[assignment]
    assert _out_of_target(c, "갑지") == ""


# ── 여기부터는 조립까지 통과시켜 본다 ────────────────────────────────
# 위 검사들은 판별 함수와 검사기 생성까지만 본다. 검토를 실제로 돌렸을 때
# **상태가 무엇으로 찍히는가**가 검토자가 보는 것이고, 거기까지 확인해야
# "화면에서 빠진다"고 말할 수 있다.

@dataclass
class _Item:
    no: str = ""
    text: str = ""
    group: str = ""
    note: str = ""
    agent: str = ""
    mode: str = ""
    check: str = ""
    params: dict = None
    applies_to: list = field(default_factory=list)

    def __post_init__(self):
        self.params = self.params or {}


@dataclass
class _Checklist:
    items: list


def _run(tmp_path, items, output_key=""):
    doc = tmp_path / "doc.md"
    doc.write_text("# 문서\n내용이 조금 있다.\n", encoding="utf-8")
    cfg = Config(llm_provider="echo", chunk_max_chars=4000,
                 review=ReviewConfig("generic"))
    res = review_with_checklist(doc, _Checklist(items=items), cfg,
                                output_key=output_key)
    return {it.no: it for it in res.items}


def test_other_document_becomes_na_not_manual(tmp_path) -> None:
    """대상이 아닌 기준은 `na`(해당없음)다.

    `manual` 로 두면 화면의 "사람 확인 필요" 숫자에 섞여, 검토자가 자기 일이
    아닌 항목을 세게 된다 — 이 칸을 만든 이유가 그것이다.
    """
    by_no = _run(tmp_path, [
        _Item(no="갑지것", text="비고문구 4개 유지", applies_to=["갑지"]),
        _Item(no="아무거나", text="오탈자가 없는가"),
    ], output_key="시험의뢰서")

    assert by_no["갑지것"].status == "na"
    assert by_no["아무거나"].status != "na", "대상 제한이 없는 기준까지 빠지면 안 된다"


def test_na_says_why_on_screen(tmp_path) -> None:
    """왜 해당없음인지 화면이 말해야 한다. 이유 없는 '해당없음'은 검토자가
    기준이 잘못 붙은 건지 정상인지 구분할 수 없다."""
    by_no = _run(tmp_path, [
        _Item(no="1", text="비고문구 4개 유지", applies_to=["갑지"]),
    ], output_key="시험의뢰서")
    note = by_no["1"].note
    assert "갑지" in note and "시험의뢰서" in note, (
        f"어느 문서 전용인지와 이 문서가 무엇인지가 note 에 있어야 한다: {note!r}")


def test_matching_document_is_reviewed_normally(tmp_path) -> None:
    """대상 문서면 평소대로 검사한다 — 규칙이 붙으면 규칙이 돈다."""
    by_no = _run(tmp_path, [
        _Item(no="1", text="약어가 정의되어 있는가", applies_to=["갑지"],
              agent="형식·완전성", mode="규칙", check="abbrev"),
    ], output_key="갑지")
    assert by_no["1"].status != "na", "대상 문서인데 빠졌다"
    assert by_no["1"].mode == "규칙"


def test_unclassified_document_is_manual_not_na(tmp_path) -> None:
    """산출물을 못 가렸으면 `na` 가 아니라 사람 몫이다.

    모르는 것을 해당없음으로 두면 검사된 적 없는 기준이 "고칠 것 없음"으로
    보인다. 그건 이 도구가 낼 수 있는 최악의 거짓말이다.
    """
    by_no = _run(tmp_path, [
        _Item(no="1", text="비고문구 4개 유지", applies_to=["갑지"]),
    ], output_key="")
    assert by_no["1"].status == "manual"
    assert "가리지 못" in by_no["1"].note or "판단하지 못" in by_no["1"].note
