"""같은 근거·같은 종류의 중복 지적 병합(collector.merge_duplicates).

LLM 은 청크×기준묶음마다 따로 불려서 같은 문장을 같은 이유로 두세 번 지적한다
(실측 SKN56 RVVR: '운영권 조정/운영권조정' 모순 두 장). 카드가 두 장이면 검토자는
서로 다른 문제로 읽는다 — 내용이 같으면 카드도 하나다.
"""
from modules.report import merge_duplicates
from modules.shared import Anchor, Evidence, Finding, Severity


def _f(kind, quotes, section="22.2", message="용어 불일치", checker="consistency"):
    a = Anchor(page=1, section=section)
    return Finding(checker=checker, severity=Severity.MAJOR, message=message,
                   anchor=a, kind=kind,
                   evidence=[Evidence(anchor=a, quote=q) for q in quotes])


def test_같은_종류_같은_절_같은_인용이면_하나로_합친다():
    a = _f("모순", ["운영권 조정", "운영권조정"], message="표기가 일관되지 않다")
    b = _f("모순", ["운영권 조정", "운영권조정"], message="띄어쓰기가 갈린다")
    out, replaced = merge_duplicates([a, b])
    assert out == [a]
    assert replaced == {id(b): a}


def test_검사기가_달라도_내용이_같으면_합친다():
    a = _f("모순", ["운영권 조정", "운영권조정"], checker="consistency")
    b = _f("모순", ["운영권조정", "운영권 조정"], checker="consistency_doc")
    out, _ = merge_duplicates([a, b])
    assert out == [a], "인용 순서·검사기가 달라도 내용은 같다"


def test_종류나_절이_다르면_안_합친다():
    a = _f("모순", ["운영권 조정"])
    b = _f("표기", ["운영권 조정"])
    c = _f("모순", ["운영권 조정"], section="3.1")
    out, replaced = merge_duplicates([a, b, c])
    assert out == [a, b, c] and not replaced


def test_근거나_종류가_없으면_건드리지_않는다():
    # 규칙 검사(kind 없음)·미검토 INFO(근거 없음)는 동일성을 주장할 신호가 없다.
    a = Finding(checker="completeness", severity=Severity.MAJOR,
                message="필수 항목 누락: 1.0 Purpose", anchor=Anchor(page=None, section=None))
    b = Finding(checker="completeness", severity=Severity.MAJOR,
                message="필수 항목 누락: 1.0 Purpose", anchor=Anchor(page=None, section=None))
    out, replaced = merge_duplicates([a, b])
    assert out == [a, b] and not replaced
