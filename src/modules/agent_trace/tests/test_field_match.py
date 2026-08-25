"""산출물 간 필드 대조.

문서를 받지 않는다 — 추출된 값(dict) 두 개면 판정된다. 그래서 테스트가 dict 두 개로
끝나고, 문서 파싱이 바뀌어도 이 판정은 흔들리지 않는다.

이 층이 단일 문서 형식 검사보다 신뢰도가 높다. 기준이 "서로 같아야 한다"라서 규정
해석 여지가 없기 때문이다 — "특정 형식이어야 한다"는 규정 원문 해석이 갈린다.
"""
from modules.agent_trace import PairRow, PairRule, compare_pair
from modules.doc_parser import FieldValue
from modules.shared import Anchor, Severity


def _v(name, value, section="표1 1행", found=True, label=""):
    return FieldValue(name=name, value=value, anchor=Anchor(None, section),
                      found=found, matched_label=label,
                      source_quote=f"{label} | {value}" if label else "")


def _pair(*rows, left="을지", right="갑지", pid="1-5"):
    return PairRule(id=pid, left=left, right=right, rows=tuple(rows))


def test_같으면_지적하지_않는다():
    left = {"성적서번호": _v("성적서번호", "SST-26-999-C01")}
    right = {"성적서번호": _v("성적서번호", "SST-26-999-C01")}

    assert compare_pair(left, right, _pair(PairRow(field="성적서번호"))) == []


def test_한_글자만_달라도_지적한다():
    # 실측: 을지 SST-26-999-C01 ↔ 갑지 SST-26-999C01. 사람이 읽으면 같은 값이다.
    left = {"성적서번호": _v("성적서번호", "SST-26-999-C01", "표1 2행")}
    right = {"성적서번호": _v("성적서번호", "SST-26-999C01", "표1 1행")}

    findings = compare_pair(left, right, _pair(PairRow(field="성적서번호")))

    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "1-5/성적서번호"
    assert f.document == "을지 ↔ 갑지"
    assert "SST-26-999-C01" in f.message and "SST-26-999C01" in f.message
    assert f.unreviewed is False


def test_공백_한_칸_차이도_지적한다():
    # 실측: 을지 `~2026` ↔ 갑지 `~ 2026`.
    left = {"시험기간": _v("시험기간", "2026. 01. 01.~2026. 01. 15.")}
    right = {"시험기간": _v("시험기간", "2026. 01. 01.~ 2026. 01. 15.")}

    assert len(compare_pair(left, right, _pair(PairRow(field="시험기간")))) == 1


def test_근거를_양쪽_다_싣는다():
    # 대조 지적은 본질적으로 "여기와 저기"다. anchor 하나로는 어디를 고칠지 모른다.
    left = {"성적서번호": _v("성적서번호", "A", "표1 2행")}
    right = {"성적서번호": _v("성적서번호", "B", "표3 5행")}

    f = compare_pair(left, right, _pair(PairRow(field="성적서번호")))[0]

    assert [e.anchor.section for e in f.evidence] == ["표1 2행", "표3 5행"]
    assert [e.quote for e in f.evidence] == ["A", "B"]
    assert f.anchor.section == "표1 2행"      # 첫 근거의 위치


def test_표에서_뽑은_근거는_라벨과_값을_함께_싣는다():
    """짧은 값 `1.0`만 넘기면 PDF에서 날짜의 일부를 버전으로 잘못 짚는다."""
    left = {"버전": _v("버전", "1.0", label="버전")}
    right = {"버전": _v("버전", "1.0.1", label="버전")}

    f = compare_pair(left, right, _pair(PairRow(field="버전")))[0]

    assert [e.quote for e in f.evidence] == ["버전 | 1.0", "버전 | 1.0.1"]


def test_한쪽을_못_찾으면_불일치가_아니라_미검토():
    # 라벨맵이 문서와 어긋났을 수 있다. 못 찾은 것을 "다르다"로 판정하면 거짓 지적이
    # 되고, 조용히 넘기면 검사하지 않은 것이 "이상 없음"으로 보인다.
    left = {"성적서번호": _v("성적서번호", "SST-26-999-C01")}
    right = {"성적서번호": _v("성적서번호", None, found=False)}

    f = compare_pair(left, right, _pair(PairRow(field="성적서번호")))[0]

    assert f.unreviewed is True
    assert "갑지" in f.message      # 어느 쪽을 못 찾았는지 말한다


def test_양쪽_다_없는_필드는_미검토():
    left = {"없는것": _v("없는것", None, found=False)}
    right = {"없는것": _v("없는것", None, found=False)}

    assert compare_pair(left, right, _pair(PairRow(field="없는것")))[0].unreviewed


def test_명세에_없는_필드는_미검토():
    # 필드맵에 아직 안 넣은 필드를 대조표가 가리키면, 조용히 건너뛰면 안 된다.
    assert compare_pair({}, {}, _pair(PairRow(field="아직없음")))[0].unreviewed


def test_이름이_다른_필드를_맞대볼_수_있다():
    # md §1-1 "요구 사항 ↔ 시험합격기준" 처럼 양쪽 이름이 다른 대조가 있다.
    left = {"요구사항": _v("요구사항", "A")}
    right = {"시험합격기준": _v("시험합격기준", "B")}

    findings = compare_pair(left, right,
                            _pair(PairRow(field="요구사항", right_field="시험합격기준")))

    assert len(findings) == 1


def test_심각도는_major():
    # 값이 어긋난 성적서가 고객에게 나간다. 사소한 표기 문제와 같은 무게일 수 없다.
    left = {"성적서번호": _v("성적서번호", "A")}
    right = {"성적서번호": _v("성적서번호", "B")}

    assert compare_pair(left, right, _pair(PairRow(field="성적서번호")))[0].severity \
        is Severity.MAJOR
