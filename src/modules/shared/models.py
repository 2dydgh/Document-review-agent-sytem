"""DocReview 내부 문서모델.

모든 지적사항은 Anchor(page/section)로 원문 위치를 추적한다.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class Anchor:
    page: int | None
    section: str | None


@dataclass
class Section:
    id: str
    title: str
    level: int
    text: str
    anchor: Anchor
    children: list[Section] = field(default_factory=list)


@dataclass
class Document:
    source_path: str
    doc_type: str | None
    sections: list[Section] = field(default_factory=list)
    # 본문으로는 안 남는 것. 지금은 표별 글꼴 크기뿐이다(docx).
    #
    # 서식 검사(글꼴·크기)는 sections 로는 못 한다 — 거기 남는 것은 렌더된
    # 글자뿐이라 "이 표의 이 글자가 8pt" 라는 사실이 파싱 중에 사라진다.
    # 책갈피도 같은 이유로 사라져 있다(아직 자리를 안 냈다).
    #
    # **여기 아무거나 담지 않는다.** 검사기가 읽어야 하는데 sections 로 표현할 수
    # 없는 것만 온다. 그렇지 않으면 문서 모델이 파서마다 다른 잡동사니가 된다.
    meta: dict = field(default_factory=dict)

    def iter_sections(self) -> Iterator[Section]:
        def walk(sections: list[Section]) -> Iterator[Section]:
            for s in sections:
                yield s
                yield from walk(s.children)

        yield from walk(self.sections)


@dataclass
class Chunk:
    id: str
    text: str
    anchor: Anchor
    section_id: str


class Severity(str, Enum):
    """지적의 **확실성** 3단. 낮은 것부터 적는다 — 정렬은 report/collector 가 뒤집는다.

    - MAJOR  판정이 확실하다. 문자열 대조로 결론이 나 사람이 다시 볼 필요가 없다.
    - MINOR  판정에 여지가 있다. 근거는 있지만 사람이 확인해야 한다.
    - INFO   검토 과정 보고. 지적이 아니다(`unreviewed` 가 그 사실을 따로 진다).

    **"얼마나 나쁜가"(중대성)는 여기 담지 않는다.** 그건 팀이 정할 값이지 도구가
    정할 값이 아니다 — 근거 없이 매기면 점수를 뺄 때와 같은 문제가 된다(CLAUDE.md
    "기능 방침 — 점수"). 반면 확실성은 도구가 안다.

    **규칙 체커도 MINOR 를 낸다.** "규칙=MAJOR · LLM=MINOR" 가 아니다 — 같은
    검사 안에서도 확신이 갈린다:

      · CompletenessChecker  절이 없다(MAJOR) vs 절은 있는데 제목이 다르다(MINOR)
                             — 후자는 의도적 변형일 수 있다
      · AbbrevChecker        대문자 토큰이 진짜 약어인지 도메인 명사인지 못 가린다
      · RefListChecker       인용 안 된 참조문서가 정말 불필요한지는 사람이 안다

    한때 독스트링만 "중대성"이라 적혀 있었는데 값을 매기는 코드는 확실성을 따랐다.
    2026-08-05 에 코드 쪽으로 맞추면서 FontSizeChecker 만 MINOR→MAJOR 로 올렸다 —
    거기만 근거 주석 없이 "글꼴은 덜 중대하다"는 중대성 판단이 섞여 있었다.

    **한 화면 안에서 값이 안 갈리면 화면에 내지 않는다.** 폴더 검토는 규칙만 돌아서
    지적이 전부 MAJOR 다 — 거기서 심각도 뱃지·분포 바는 정보를 안 나른다(web/views.js
    caseDocView 참고). 아래 CRITICAL 을 지운 것과 같은 이유다.

    CRITICAL 은 없다. 한때 정의돼 있었지만 **어느 체커도 내지 않았고**(지정 45곳 중
    0곳 · 실측 200건 중 0건), 화면 범례에는 늘 "Critical 0" 이 떠서 "심각한 문제를
    찾아봤고 없었다"는 거짓말을 했다. 최상위 등급이 필요해지면 **그것을 내는 체커와
    함께** 다시 넣는다.
    """

    INFO = "info"
    MINOR = "minor"
    MAJOR = "major"


@dataclass(frozen=True)
class Evidence:
    """지적의 근거 한 조각. quote는 원문 그대로여야 한다.

    verify.verify_quotes가 이 문자열이 문서에 실재하는지 대조한다. 실재하지
    않으면 그 지적은 폐기된다 — 환각을 코드로 막는 자리다. 실재하더라도
    너무 짧거나(공백뿐 포함) 문장부호뿐인 인용은 근거로 세지 않는다 —
    substring 대조는 짧을수록 우연히 맞아떨어지기 쉬워 지어낸 message에
    아무 글자나 붙여도 통과해버리기 때문이다.
    """
    anchor: Anchor
    quote: str
    # 이 근거가 **그림 설명**에서 나왔으면 그 그림 번호. 본문 글에서 나왔으면 None.
    # 뷰어는 이것으로 형광펜을 그림 자체에 얹는다 — 그림 설명은 파싱 본문에만 있고
    # PDF 텍스트 레이어에는 없어서, 인용문으로는 위치를 찾을 수 없다.
    image_no: int | None = None
    # 본문이 아닌 곳에서 나온 근거의 출처 이름("머릿말"·"꼬리말"). 본문이면 "".
    #
    # image_no 와 같은 문제를 푼다 — **본문에서 찾을 수 없는 근거**다. 머릿말은
    # 쪽마다 반복돼 본문에서 빼고 meta 로 옮기므로(app/parser_bridge), 그 인용을
    # 본문에서 뒤지면 우연히 맞는 곳을 짚는다. 실측(제출물 확인증): 머릿말의
    # `제출물 확인증` 이 본문 표의 같은 글자에 형광펜을 얹어, 문서 제목이 지적받은
    # 것처럼 보였다.
    #
    # 값이 있으면 위치를 찾지 않고, 화면은 "무엇을 보고 판정했나"로 그린다.
    source: str = ""


@dataclass
class Finding:
    checker: str
    severity: Severity
    message: str
    anchor: Anchor
    suggestion: str | None = None
    document: str | None = None
    # **무엇이 잡았나**를 사람 말로. checker 는 관점 묶음이라 못 가린다 — 일곱
    # 검사기가 "completeness" 를, 셋이 "consistency" 를 나눠 쓴다(리포트에서
    # 형식·완전성 / 표현·내용품질로 모으려고 일부러 겹친 이름이다).
    #
    # 화면 뱃지가 이걸 쓴다. `MAJOR` 만 줄줄이 뜨면 무엇을 봐야 하는지 안 보이지만,
    # `약어 목록 대조` · `파일명 규칙 검사` 는 바로 읽힌다. 심각도는 남는다 —
    # 정렬(collector)과 PDF 형광펜 색(pdfview.js)이 그걸로 돈다.
    #
    # 체커가 스스로 채우지 않는다. 자기 label 을 Finding 마다 적으면 아홉 군데에
    # 같은 말을 되풀이하게 되므로, 체커를 **아는 자리**(조립 계층)가 찍는다.
    label: str = ""
    # 어느 기준 항목이 이 지적을 냈나("1-5/성적서번호"). checker 는 검사기 이름
    # ("field_match")이라 항목까지는 못 가리킨다 — 리포트가 지적을 기준 항목 아래로
    # 되접으려면 이게 있어야 한다. 비어 있으면 항목에 매이지 않은 지적이다.
    rule_id: str = ""
    # **어떤 종류의 잘못인가.** label 이 "무엇이 잡았나"라면 이건 "무엇이 잘못됐나"다.
    #
    # 표현 점검이 낸 스물몇 건이 화면에서 전부 `표현 점검` 한 가지로 보였다. 오타와
    # 앞뒤 모순이 같은 뱃지를 달고, 갈리는 것은 뱃지 **색**뿐이었다(주황=major,
    # 노랑=minor). 검토자가 색의 뜻을 알 리 없다.
    #
    # 값은 검사기가 정한다 — 표현 점검은 모델이 답한 것(모순·표기·모호)을 그대로
    # 싣는다. 그 답으로 severity 를 고르고는 값 자체를 버리고 있었다. 다른 검사기는
    # 아직 안 채운다(빈 값이면 화면이 label 로 되돌아간다).
    kind: str = ""
    # 일관성 지적은 본질적으로 "여기와 저기"다. anchor 하나로는 부족해서
    # 근거를 여러 개 싣는다. anchor에는 첫 근거의 위치를 넣는다 —
    # 기존 리포트·UI·RTM은 anchor만 읽으므로 그대로 동작한다.
    evidence: list[Evidence] = field(default_factory=list)
    # "문제를 찾았다"가 아니라 "검사를 못 했다"는 보고다(LLM 미연결·응답 실패·요건
    # ID 0건 등). 지적 0건과 구분해야 한다 — 안 구분하면 검사하지 않은 항목이
    # "이상 없음"으로 보이고, INFO 라고 지적에 섞으면 "문제 발견"으로 보인다.
    unreviewed: bool = False
    # 1차 인용이 대조에 실패해 **재질의 왕복 끝에** 근거를 다시 찾은 지적
    # (agent_quality/rescue.py). 근거 자체는 원문 대조를 통과했지만, 한 번에
    # 근거를 댄 지적과는 온 길이 다르다 — 출처를 숨기면 검토자가 신뢰 무게를
    # 달리 줄 수 없고, 실측(복원 지적만 골라 검수)도 어려워진다.
    rescued: bool = False
    # rescued 지적의 재확인 여정: {"failed_quotes": [...], "searched": [...]}.
    # 처음 인용(대조 실패)과 모델이 쓴 검색어다 — 확정 근거는 evidence 가 담는다.
    # 화면이 "처음 인용 → 검색 → 확정 근거"를 그릴 수 있어야, 에이전트가 도구를
    # 들고 문서를 뒤진 과정이 결과에서 사라지지 않는다. rescued 가 아니면 None.
    rescue_trace: dict | None = None


@dataclass
class RtmRow:
    """추적성 매트릭스 1행. 연결된 항목까지 전부 표현한다.

    - linked : 상위 ID가 하위에 존재 (upper_id, lower_ids=[해당 ID])
    - missing: 상위 ID가 하위에 없음 (upper_id, lower_ids=[])
    - orphan : 하위에만 있는 ID (upper_id=None, lower_ids=[해당 ID])
    """
    upper_id: str | None
    lower_ids: list[str]
    status: str  # linked | missing | orphan
    anchor: Anchor
