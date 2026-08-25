"""파일명으로 산출물 종류를 판별한다.

케이스에는 파일이 10~14개 올라온다. 어느 파일이 갑지고 어느 것이 을지인지 알아야
필드맵을 고를 수 있다. 근거는 **파일명의 양식번호**다:

    SST-K-TP-7-08-06(00) 시험성적서(일반_국문)_SST-26-999(갑지).docx
    ^^^^^^^^^^^^^^^^ 어간          ^^ 개정번호

어간으로 종류를 찾고 개정번호는 **따로** 비교한다. 어간이 맞고 개정번호만 다르면
"판별 성공 + 구 양식 지적"이지 판별 실패가 아니다 — 실패로 다루면 그 문서를 통째로
검사하지 못한다.
"""
from modules.preset import classify_output

OUTPUTS = [
    {"key": "시험의뢰 검토기록서", "form_no": "SST-K-TP-7-01-01(02)"},
    {"key": "시험의뢰서", "form_no": "SST-K-TP-7-01-02(08)"},
    {"key": "시험설계서", "form_no": "SST-K-TI-03-02(05)"},
    {"key": "갑지", "form_no": "SST-K-TP-7-08-06(00)"},
]


def test_양식번호로_산출물을_찾는다():
    got = classify_output(
        "SST-K-TP-7-08-06(00) 시험성적서(일반_국문)_SST-26-999(갑지).docx", OUTPUTS)

    assert got.output_key == "갑지"
    assert got.revision_stale is False


def test_개정번호가_달라도_판별은_성공하고_구_양식으로_표시한다():
    # 실패로 다루면 그 문서를 통째로 검사하지 못한다. 판별은 되고 지적만 남는다.
    got = classify_output("SST-K-TI-03-02(04)-시험 설계서_SST-26-999.docx", OUTPUTS)

    assert got.output_key == "시험설계서"
    assert got.revision_stale is True
    assert got.form_no_found == "SST-K-TI-03-02(04)"
    assert got.form_no_expected == "SST-K-TI-03-02(05)"


def test_어간이_비슷한_것끼리_헷갈리지_않는다():
    # SST-K-TP-7-01-01 과 SST-K-TP-7-01-02 는 앞이 같다.
    got = classify_output("SST-K-TP-7-01-01(02) 시험 의뢰 검토 기록서.docx", OUTPUTS)

    assert got.output_key == "시험의뢰 검토기록서"


def test_양식번호가_없으면_추측하지_않는다():
    # 고객 제출물(접수 문서)에는 슈어 양식번호가 없다. 추측해서 배정하면 엉뚱한
    # 필드맵으로 검사해 거짓 지적이 난다.
    got = classify_output("시험 접수 문서(일반)_2026(문서 간 검토 시 사용).docx", OUTPUTS)

    assert got.output_key is None
    assert got.form_no_found == ""


def test_개정번호가_파일명에_없으면_판별만_하고_비교는_안_한다():
    got = classify_output("SST-K-TI-03-02-시험 설계서.docx", OUTPUTS)

    assert got.output_key == "시험설계서"
    assert got.form_no_found == ""
    assert got.revision_stale is False    # 없는 것을 틀렸다고 하지 않는다
