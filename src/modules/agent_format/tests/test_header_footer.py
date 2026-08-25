"""머릿말·꼬리말 검사.

머릿말은 **본문에 안 실린다** — 쪽마다 반복돼 일관성 검사를 오염시키기 때문이다
(app/parser_bridge.py). 그래서 파서가 `meta["headers"]`·`["footers"]` 로 옮기고
이 검사기가 그것을 본다. 본문에서 빼는 것과 통째로 버리는 것은 다르다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from modules.agent_format import HeaderFooterChecker


@dataclass
class _Doc:
    meta: dict = field(default_factory=dict)

    def iter_sections(self):
        return iter(())


def _run(meta: dict, **kw) -> list:
    return HeaderFooterChecker(**kw).check(_Doc(meta=meta))


_HDR = {"headers": ["의뢰번호: SST-26-999 성적서번호: SST-26-999-C01"]}


def test_finds_required_words() -> None:
    got = _run(_HDR, contains=("의뢰번호", "성적서번호"))
    assert not [f for f in got if not f.unreviewed]


def test_missing_words_are_one_finding_naming_all() -> None:
    """한때 라벨마다 카드를 냈다(2026-08-20 바꿈).

    "뭉치면 무엇을 고칠지 안 보인다"가 이유였는데, 그건 **메시지가 다 적으면**
    해결된다. 나누면 같은 머릿말 세 줄이 카드마다 실려 인용 칩이 배로 늘었다
    (실측: 제출물 확인증에서 칩이 1·2·3·4). 같은 곳을 보고 내린 판정이다.
    """
    got = [f for f in _run({"headers": ["문서 제목만 있음"]},
                           contains=("의뢰번호", "성적서번호")) if not f.unreviewed]
    assert len(got) == 1
    assert "의뢰번호" in got[0].message and "성적서번호" in got[0].message


def test_only_the_missing_ones_are_named() -> None:
    """있는 것까지 적으면 검토자가 멀쩡한 값을 고치러 간다."""
    got = [f for f in _run({"headers": ["의뢰번호: SST-26-999"]},
                           contains=("의뢰번호", "성적서번호")) if not f.unreviewed]
    assert len(got) == 1
    assert "성적서번호" in got[0].message
    assert "의뢰번호" not in got[0].message


def test_evidence_says_it_came_from_the_header() -> None:
    """머릿말 인용은 **본문에 없다**(파서가 meta 로 옮긴다). 출처를 안 적으면
    뷰어가 본문에서 같은 글자를 찾아 형광펜을 얹는다 — 실측(제출물 확인증)에서
    머릿말의 `제출물 확인증` 이 본문 표의 같은 글자를 짚었다."""
    got = [f for f in _run({"headers": ["의뢰 번호: SST-26-999", "제출물 확인증"]},
                           contains=("성적서번호",)) if not f.unreviewed]
    assert got and got[0].evidence
    assert all(e.source == "머릿말" for e in got[0].evidence)

    foot = [f for f in _run({"footers": ["SST-K-TP-7-04-01(02)"]},
                            where="footer", contains=("페이지",)) if not f.unreviewed]
    assert foot and all(e.source == "꼬리말" for e in foot[0].evidence)


def test_missing_finding_shows_what_it_read() -> None:
    """'없다'는 지적은 자리를 가리킬 수 없다. 대신 **무엇을 보고 그렇게 판정했는지**
    를 인용으로 보여줘야 검토자가 확인한다."""
    got = [f for f in _run({"headers": ["엉뚱한 머릿말"]},
                           contains=("의뢰번호",)) if not f.unreviewed]
    assert got[0].evidence and got[0].evidence[0].quote == "엉뚱한 머릿말"


def test_footer_pattern() -> None:
    ok = _run({"footers": ["SST-K-TI-03-04(08) 페이지 ( 6 ) / 총 ( 12 )"]},
              where="footer", pattern=r"페이지\s*\(\s*\d+\s*\)")
    assert not [f for f in ok if not f.unreviewed]
    bad = _run({"footers": ["SST-K-TI-03-04(08)"]},
               where="footer", pattern=r"페이지\s*\(\s*\d+\s*\)")
    assert [f for f in bad if not f.unreviewed]


def test_no_rule_is_unreviewed_not_clean() -> None:
    """찾을 것을 안 주면 검사한 척하지 않는다."""
    got = _run(_HDR)
    assert len(got) == 1 and got[0].unreviewed


def test_no_header_is_unreviewed_not_flagged() -> None:
    """머릿말이 **없는 문서**와 파서가 **못 읽은 문서**를 가를 수 없다. 없는 것을
    있다고 하는 것보다, 못 봤다고 말하는 쪽이 안전하다."""
    got = _run({"headers": []}, contains=("의뢰번호",))
    assert len(got) == 1 and got[0].unreviewed
    assert "읽지 못해" in got[0].message


def test_broken_pattern_is_reported_not_flagged() -> None:
    got = _run(_HDR, pattern=r"[unclosed")
    assert got[0].unreviewed and "정규식이 올바르지 않아" in got[0].message


def test_rule_id_is_carried() -> None:
    got = [f for f in _run({"headers": ["없음"]}, contains=("의뢰번호",),
                           rule_id="서식-2") if not f.unreviewed]
    assert got[0].rule_id == "서식-2"


def test_띄어쓰기가_달라도_찾는다():
    """실측(제출물 확인증): 머릿말이 `의뢰 번호: SST-26-999` 인데 기준은 `의뢰번호`
    라고 적혀 있어 "머릿말에 '의뢰번호' 이(가) 없습니다"로 떴다 — 있는데 없다고 한 것이다.

    한국어 라벨은 문서마다 띄어쓰기가 갈린다. 그 차이는 이 검사가 볼 것이 아니다
    (맞춤법은 공통 기준이 따로 본다).
    """
    got = [f for f in _run({"headers": ["의뢰 번호: SST-26-999", "제출물 확인증"]},
                           contains=("의뢰번호",)) if not f.unreviewed]
    assert not got, f"띄어 쓴 라벨을 못 찾았다 — {got[0].message if got else ''}"


def test_없는_것은_그대로_잡는다():
    """앞 시험의 뒷면. 공백을 지운다고 없는 말이 생기지는 않는다."""
    got = [f for f in _run({"headers": ["의뢰 번호: SST-26-999"]},
                           contains=("성적서번호",)) if not f.unreviewed]
    assert got and "성적서번호" in got[0].message
