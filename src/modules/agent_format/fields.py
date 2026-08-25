"""규칙기반 체커: 칸 값 검사. 필드가 채워졌나, 형식이 맞나.

팀 기준 80항목 중 8항목이 이 검사기를 요구한다(`docs/checker-inventory.md` A) —
EV2 표지정보·개정기록·평가표·참조문서목록·MEMO·목적범위, AI시험인증1 문서양식·시험환경.
가장 많은 항목이 걸려 있어 제일 먼저 만든다.

**추출과 판정은 다른 일이다.** `doc_parser.extract_fields` 가 값을 꺼내고 여기서
판정만 한다. 그래서 두 가지가 섞이지 않는다:

    못 찾았다   라벨맵이 실제 문서와 어긋남 → 사람이 봐야 함 → 미검토(INFO)
    비어 있다   문서 결함                  → 지적(MAJOR)

기준은 주입받는다. 이 모듈은 팀 이름도 문서 이름도 모른다 — `src/app/` 이
프리셋에서 읽어 넣는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from modules.doc_parser import FieldSpec, FieldValue, extract_fields
from modules.shared import Anchor, Document, Evidence, Finding, Severity


@dataclass(frozen=True)
class SignatureSpec:
    """서명이 들어갈 자리. placeholder 가 그대로 남아 있으면 미작성이다.

    실측: 샘플 갑지가 `성명                          (서명)` 그대로였다.

    at 은 값이 라벨의 어느 쪽인지다. 갑지의 서명란은 가로 표라 `below` 다 —
    기본값(`right`)으로 두면 시험실무자의 값으로 옆 칸('기술책임자')을 읽어
    **미작성을 놓친다**.

        | 확인 | 시험실무자 | 기술책임자 |
        |      | 성명  (서명) | 성명  (서명) |
    """
    role: str
    placeholder: str
    at: str = "right"


# `2026. 01. 05.` — 이 팀 문서의 날짜 표기. 마지막 점은 있어도 없어도 받는다.
# 구분자를 `.` 로 못박는다. 다른 표기를 쓰는 팀이 나오면 그때 어휘를 늘린다 —
# 미리 넓히면 `20    .    .`(동의서 미작성) 같은 것이 통과한다.
_DATE = r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?"
_DATE_RX = re.compile(rf"^{_DATE}$")
_RANGE_RX = re.compile(rf"^{_DATE}\s*~\s*{_DATE}$")


def _squash(text: str) -> str:
    """공백을 지운다. 표기가 문서마다 흔들려도 맞추기 위함이다."""
    return "".join(str(text or "").split())


def _field_quote(got: FieldValue, value: str) -> str:
    """짧은 값은 실제 표 행 문맥을 쓰되, 원문에 없는 문자열은 만들지 않는다."""
    return got.source_quote or value


def _to_date(y: str, m: str, d: str) -> date | None:
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None       # 2026. 02. 30. — 달력에 없는 날


class FieldPresenceChecker:
    """산출물 양식 하나를 받아 그 문서의 칸들을 판정한다.

    name 은 `PlaceholderChecker` 와 같은 `completeness` 다 — 리포트에서 형식·완전성
    묶음으로 모인다.
    """

    name = "completeness"
    label = "칸 값 검사"

    def __init__(self, fields: list[FieldSpec] | None = None,
                 fixed_text: list[str] | None = None,
                 signatures: list[SignatureSpec] | None = None,
                 document: str | None = None) -> None:
        self.fields = list(fields or [])
        self.fixed_text = list(fixed_text or [])
        self.signatures = list(signatures or [])
        # 2문서 비교에서 어느 쪽 문서의 문제인지 표시할 때 쓴다.
        self.document = document

    def check(self, doc: Document, ctx: object = None) -> list[Finding]:
        if not (self.fields or self.fixed_text or self.signatures):
            # 볼 칸을 아무도 안 알려줬다. 조용한 0건은 "칸이 다 채워져 있더라"로
            # 읽힌다 — 이 검사기는 못 찾은 칸도 미검토로 밝히면서, 정작 아무것도
            # 안 받았을 때만 입을 다물고 있었다.
            return [Finding(
                checker=self.name,
                severity=Severity.INFO,
                message="이 문서에서 볼 칸이 기준에 정해져 있지 않아 칸 값 검사를 "
                        "하지 않았습니다.",
                anchor=Anchor(page=None, section=None),
                # 검토자가 화면에서 읽는 줄이다. 예전에는 "팀 기준의 outputs 절에
                # … params.fields 에 그 이름을 고르세요" 라고 적혀 있었다 — 문서를
                # 보러 온 사람에게 yaml 편집 지시를 내린 것이다. 할 사람을 먼저
                # 말하고, 무엇을 고쳐야 하는지는 그 사람이 알아볼 만큼만 남긴다.
                suggestion=("검토자가 할 일은 아닙니다 — 기준 관리자에게 이 산출물의 "
                            "칸 목록을 기준에 추가해 달라고 알려주세요"
                            "(팀 기준 outputs 절 · 항목의 params.fields)."),
                document=self.document,
                unreviewed=True,
            )]
        findings: list[Finding] = []
        if self.fields:
            values = extract_fields(doc, self.fields)
            for spec in self.fields:
                findings.extend(self._judge(spec, values[spec.name]))
        findings.extend(self._judge_fixed_text(doc))
        findings.extend(self._judge_signatures(doc))
        return findings

    # ── 필드 하나 ────────────────────────────────────────────────────────

    def _judge(self, spec: FieldSpec, got: FieldValue) -> list[Finding]:
        if spec.source == "checkbox_group":
            return self._judge_checkbox(spec, got)
        if spec.source == "table_rows":
            return self._judge_table_rows(spec, got)

        if not got.found:
            return [self._unreviewed(
                f"'{spec.name}' 을(를) 문서에서 찾지 못해 검사하지 않았습니다 "
                f"(찾아본 라벨: {' / '.join(spec.labels) or '없음'}).",
                spec, got.anchor,
                "라벨이 문서와 다른지 확인하고 검토 기준의 labels 를 고치세요.")]

        value = (got.value or "").strip()
        if not _squash(value):
            # 비었으면 "비었다" 하나면 된다. 형식까지 겹쳐 지적하면 한 결함이
            # 두 건으로 불어난다.
            if not spec.required:
                return []
            # 값이 없으니 라벨 칸을 짚는다 — 검토자가 어디를 채워야 하는지다.
            return [self._defect(f"'{spec.name}' 이(가) 비어 있습니다.", spec,
                                 got.anchor, f"'{got.matched_label}' 칸을 작성하세요.",
                                 quote=got.matched_label or "")]

        out: list[Finding] = []
        if spec.pattern and not re.fullmatch(spec.pattern, value):
            out.append(self._defect(
                f"'{spec.name}' 의 형식이 규칙과 다릅니다: {value}", spec, got.anchor,
                "검토 기준의 표기 규칙에 맞게 고치세요.",
                quote=_field_quote(got, value)))
        if spec.format:
            out.extend(self._judge_format(
                spec, value, got.anchor, quote=_field_quote(got, value)))
        if spec.equals and _squash(value) != _squash(spec.equals):
            out.append(self._defect(
                f"'{spec.name}' 이(가) 정해진 문구와 다릅니다: {value} "
                f"(정해진 문구: {spec.equals})", spec, got.anchor,
                f"'{spec.equals}' 로 고치세요.",
                quote=_field_quote(got, value)))
        return out

    def _judge_format(self, spec: FieldSpec, value: str,
                      anchor: Anchor, quote: str = "") -> list[Finding]:
        quote = quote or value
        if spec.format == "date":
            m = _DATE_RX.match(value)
            if m is None or _to_date(*m.groups()) is None:
                return [self._defect(
                    f"'{spec.name}' 의 날짜 형식이 올바르지 않습니다: {value}",
                    spec, anchor, "`2026. 01. 05.` 형태로 작성하세요.", quote=quote)]
            return []

        if spec.format == "date_range":
            m = _RANGE_RX.match(value)
            if m is None:
                return [self._defect(
                    f"'{spec.name}' 의 기간 형식이 올바르지 않습니다: {value}",
                    spec, anchor,
                    "`2026. 01. 05. ~ 2026. 01. 15.` 형태로 작성하세요.", quote=quote)]
            start = _to_date(*m.groups()[:3])
            end = _to_date(*m.groups()[3:])
            if start is None or end is None:
                return [self._defect(
                    f"'{spec.name}' 에 달력에 없는 날짜가 있습니다: {value}",
                    spec, anchor, "날짜를 확인하세요.", quote=quote)]
            if start > end:
                return [self._defect(
                    f"'{spec.name}' 의 시작일과 종료일 순서가 뒤바뀌었습니다: {value}",
                    spec, anchor, "시작일을 종료일보다 앞 날짜로 고치세요.", quote=quote)]
            return []

        # 모르는 format 은 조용히 통과시키지 않는다 — 기준에 오타가 나면
        # 그 항목이 영원히 검사되지 않는 것처럼 보인다.
        return [self._unreviewed(
            f"'{spec.name}' 의 format '{spec.format}' 을(를) 알지 못해 "
            f"검사하지 않았습니다.", spec, anchor,
            "검토 기준의 format 값을 확인하세요 (date · date_range).")]

    def _judge_checkbox(self, spec: FieldSpec, got: FieldValue) -> list[Finding]:
        if not got.found:
            return [self._unreviewed(
                f"'{spec.name}' 의 선택지를 문서에서 찾지 못해 검사하지 "
                f"않았습니다 (선택지: {' / '.join(spec.options) or '없음'}).",
                spec, got.anchor,
                "검토 기준의 options 가 문서 표기와 같은지 확인하세요.")]
        if spec.select != "one":
            return []
        picked = list(got.selected)
        if not picked:
            return [self._defect(
                f"'{spec.name}' 에서 아무것도 선택하지 않았습니다 "
                f"(선택지: {' / '.join(spec.options)}).", spec, got.anchor,
                "하나를 선택하세요.")]
        if len(picked) > 1:
            return [self._defect(
                f"'{spec.name}' 은(는) 하나만 선택해야 하는데 "
                f"{len(picked)}개가 선택되었습니다: {' / '.join(picked)}",
                spec, got.anchor, "하나만 남기세요.")]
        return []

    def _judge_table_rows(self, spec: FieldSpec, got: FieldValue) -> list[Finding]:
        """표의 모든 행. 행마다 필수 열이 채워졌는지 본다.

        "표를 못 찾았다"(열 이름이 문서와 어긋남 → 사람이 봐야 함)와 "표가
        비었다"(문서 결함)를 섞지 않는다.
        """
        if not got.found:
            return [self._unreviewed(
                f"'{spec.name}' 표를 문서에서 찾지 못해 검사하지 않았습니다 "
                f"(찾아본 열: {' / '.join(spec.columns) or '없음'}).",
                spec, got.anchor,
                "검토 기준의 columns 가 문서의 머리행과 같은지 확인하세요.")]

        if not got.rows:
            if not spec.required:
                return []
            return [self._defect(f"'{spec.name}' 표가 비어 있습니다.", spec,
                                 got.anchor, "표에 내용을 작성하세요.")]

        out: list[Finding] = []
        for n, row in enumerate(got.rows, start=1):
            blank = [c for c in spec.required_columns
                     if not _squash(row.cells.get(c, ""))]
            for column in blank:
                out.append(self._defect(
                    f"'{spec.name}' {n}번째 행의 '{column}' 이(가) 비어 있습니다.",
                    spec, row.anchor, f"'{column}' 칸을 작성하세요."))
        return out

    # ── 고정 문구 · 서명 ─────────────────────────────────────────────────

    def _judge_fixed_text(self, doc: Document) -> list[Finding]:
        if not self.fixed_text:
            return []
        # 공백 차이는 무시한다. PDF 추출이 자간 때문에 공백을 흘리므로
        # 공백으로 지적하면 소음이 된다 (CompletenessChecker._norm 과 같은 규칙).
        body = _squash("\n".join(s.text for s in doc.iter_sections()))
        out: list[Finding] = []
        for phrase in self.fixed_text:
            if _squash(phrase) not in body:
                out.append(Finding(
                    checker=self.name, severity=Severity.MAJOR,
                    message=f"양식의 고정 문구가 없습니다: {phrase}",
                    anchor=Anchor(page=None, section=None),
                    suggestion="최신 양식의 문구를 그대로 넣으세요.",
                    document=self.document, rule_id="F-고정문구"))
        return out

    def _judge_signatures(self, doc: Document) -> list[Finding]:
        if not self.signatures:
            return []
        specs = [FieldSpec(name=s.role, labels=(s.role,), at=s.at)
                 for s in self.signatures]
        values = extract_fields(doc, specs)
        out: list[Finding] = []
        for sig in self.signatures:
            got = values[sig.role]
            rule_id = f"F-서명-{sig.role}"
            if not got.found:
                out.append(Finding(
                    checker=self.name, severity=Severity.INFO, unreviewed=True,
                    message=(f"'{sig.role}' 서명란을 문서에서 찾지 못해 "
                             f"검사하지 않았습니다."),
                    anchor=Anchor(page=None, section=None),
                    suggestion="검토 기준의 서명 role 이 문서 표기와 같은지 확인하세요.",
                    document=self.document, rule_id=rule_id))
                continue
            # 자리표시자가 그대로 앞에 남아 있으면 미작성이다. `(서명)` 같은
            # 뒤따르는 장식은 작성 여부와 무관하므로 앞부분만 본다.
            if _squash(got.value or "").startswith(_squash(sig.placeholder)):
                # 근거는 **역할 라벨**이다. 자리표시자(`성명   (서명)`)를 짚으면
                # 여러 서명란에 똑같이 있어 엉뚱한 줄로 간다. 라벨은 그 줄에만 있다.
                # 근거가 없으면 뷰어가 짚을 자리를 못 찾아 번호도 형광펜도 안 생긴다.
                label = got.matched_label or sig.role
                out.append(Finding(
                    checker=self.name, severity=Severity.MAJOR,
                    message=f"'{sig.role}' 서명란이 작성되지 않았습니다.",
                    anchor=got.anchor,
                    suggestion=f"'{sig.placeholder}' 자리에 이름을 적고 서명하세요.",
                    document=self.document, rule_id=rule_id,
                    evidence=[Evidence(anchor=got.anchor, quote=label)]))
        return out

    # ── Finding 만들기 ───────────────────────────────────────────────────

    def _defect(self, message: str, spec: FieldSpec, anchor: Anchor,
                suggestion: str, quote: str = "") -> Finding:
        """지적 하나. quote 는 **문서에서 읽어온 글자**여야 한다.

        근거가 없으면 뷰어가 PDF 에서 짚을 자리를 못 찾는다 — 번호도 형광펜도 안
        생기고, 카드를 눌러도 아무 데도 안 간다. 실측: `'성적서번호' 의 형식이
        규칙과 다릅니다: SST-26-999C01` 이 그랬다. 값은 우리가 그 칸에서 읽어온
        글자라 그대로 인용이 된다(지어낸 것이 아니다).
        """
        return Finding(checker=self.name, severity=Severity.MAJOR,
                       message=message, anchor=anchor, suggestion=suggestion,
                       document=self.document, rule_id=f"F-{spec.name}",
                       evidence=[Evidence(anchor=anchor, quote=quote)] if quote else [])

    def _unreviewed(self, message: str, spec: FieldSpec, anchor: Anchor,
                    suggestion: str) -> Finding:
        return Finding(checker=self.name, severity=Severity.INFO, unreviewed=True,
                       message=message, anchor=anchor, suggestion=suggestion,
                       document=self.document, rule_id=f"F-{spec.name}")
