"""파일명으로 산출물 종류를 판별한다.

케이스에는 파일이 10~14개 올라온다. 어느 것이 갑지고 어느 것이 을지인지 알아야
필드맵을 고른다. 근거는 파일명의 양식번호다:

    SST-K-TP-7-08-06(00) 시험성적서(일반_국문)_SST-26-999(갑지).docx
    └─── 어간 ────┘└┘ 개정번호

**어간으로 종류를 찾고 개정번호는 따로 비교한다.** 어간이 맞고 개정번호만 다르면
"판별 성공 + 구 양식 지적"이지 판별 실패가 아니다 — 실패로 다루면 개정번호 하나
때문에 그 문서를 통째로 검사하지 못한다(단일문서 md §1.1 이 요구하는 것도 "파일명의
양식 번호가 최신 개정본과 일치"하는지이지, 못 읽겠다는 게 아니다).

양식번호가 아예 없으면 **추측하지 않는다.** 고객 제출물(접수 문서)이 그렇다.
추측해서 배정하면 엉뚱한 필드맵으로 검사해 거짓 지적이 난다 — 사람에게 묻는다.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

# "SST-K-TP-7-08-06(00)" → 어간과 개정번호
_FORM_NO = re.compile(r"^(?P<stem>.+?)\((?P<rev>\d+)\)$")


@dataclass(frozen=True)
class Classification:
    """파일 하나의 판별 결과.

    output_key 가 None 이면 판별 실패다 — 사람이 지정하거나 제외해야 한다.
    """
    output_key: str | None
    form_no_found: str = ""      # 파일명에서 읽은 것 (개정번호까지)
    form_no_expected: str = ""   # 기준이 말하는 최신본
    revision_stale: bool = False


def _split(form_no: str) -> tuple[str, str]:
    """'SST-K-TP-7-08-06(00)' → ('SST-K-TP-7-08-06', '00'). 개정번호가 없으면 ('…', '')."""
    m = _FORM_NO.match(form_no.strip())
    return (m.group("stem"), m.group("rev")) if m else (form_no.strip(), "")


def classify_output(filename: str,
                    outputs: Sequence[dict]) -> Classification:
    """파일명 → 어느 산출물인가.

    outputs 는 기준 파일의 `outputs` 절이다({key, form_no, ...} 목록).
    """
    best: Classification | None = None
    for spec in outputs:
        expected = str(spec.get("form_no", "") or "")
        stem, want_rev = _split(expected)
        if not stem or stem not in filename:
            continue
        # 어간 뒤에 붙은 개정번호를 파일명에서 읽는다. 없을 수도 있다.
        m = re.search(re.escape(stem) + r"\((\d+)\)", filename)
        found_rev = m.group(1) if m else ""
        candidate = Classification(
            output_key=str(spec.get("key", "")),
            form_no_found=f"{stem}({found_rev})" if found_rev else "",
            form_no_expected=expected,
            revision_stale=bool(found_rev and want_rev and found_rev != want_rev))
        # 어간이 긴 쪽이 더 구체적이다 — 앞이 같은 양식번호끼리 헷갈리지 않게.
        if best is None or len(stem) > len(_split(best.form_no_expected)[0]):
            best = candidate
    return best or Classification(output_key=None)
