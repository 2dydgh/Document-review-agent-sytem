"""근거 검증 — agent가 인용한 문장이 원문에 실재하는지 문자열로 대조한다.

환각을 LLM으로 막지 않고 코드로 막는다. self-critique(LLM을 한 번 더 부르기)
보다 싸고, 무엇보다 결정적이다. confidence 숫자를 모델에게 물어보는 것은
근거가 약하다.

실질적인 근거(substantive quote)가 하나도 없거나, 실질적인 인용인데 원문에서
못 찾은 게 있으면 그 지적은 폐기하고 '판단불가'로 강등한다(loop.py). 지적을
지어내는 것보다 모른다고 말하는 편이 낫다.

문서에 실재하는지 substring으로만 대조하면 구멍이 하나 남는다: 아무리
짧은 인용이라도 원문 어딘가와 우연히 겹치면 "확인됨"으로 통과한다. 모델이
지어낸 message에 "예" 한 글자나 "|" 한 글자를 근거로 붙이면 그게 실제로
문서에 있으니 통과해버려 지어낸 지적이 그대로 새어나간다. 그래서 최소
길이와 문자/숫자 포함 여부를 함께 본다(`_MIN_QUOTE`, `_is_substantive`).

다만 이 문턱은 "인용 하나하나"가 아니라 "지적 전체"에 적용돼야 한다. 모델이
문장 전체와 핵심 단어를 나란히 인용하는 것("무엇이 어긋나는지 + 원문 인용"의
정상적인 응답 모양)까지 막으면 검증된 진짜 근거까지 함께 버려진다. 그래서
너무 짧은 인용은 애초에 검색하지 않고 조용히 버린다 — 근거로도 안 세지만,
검색하지 않았으므로 "원문에서 확인 못 함"(missing)으로도 보고하지 않는다.
missing에 넣으면 실제로는 존재할 수도 있는 문자열을 "없다"고 거짓 보고하는
셈이 된다. 지적 전체를 버릴지는 loop.py가 `found`(실질적으로 확인된 근거)가
비어 있는지로 판단한다.
"""
from __future__ import annotations

import re

from ..models import Document, Evidence

_WS = re.compile(r"\s+")

# 인용이 "근거"로 인정받아 검색·채택되려면 최소 이 길이는 돼야 한다.
# substring 대조는 짧을수록 우연히 맞아떨어지기 쉽다 — "예" 한 글자, "|"
# 한 글자는 문서 어디에나 있어서 지어낸 message에 아무 글자나 붙이면
# 검증을 통과해 환각이 그대로 새어나간다. 반대로 문턱을 너무 높이면
# "3초"처럼 정말 짧은 진짜 근거(예: "3초" vs "5초" 같은 수치 불일치)가
# 근거 부족으로 버려진다. 그래서 이 문턱 미만인 인용은 "그 지적의 유일한
# 근거"였을 때만 지적 전체를 죽인다(loop.py의 `found` 확인) — 다른 실질적인
# 인용이 이미 검증됐다면 짧은 인용 하나 때문에 지적 전체를 버리지 않는다.
# 4는 잠정값이고, 실제 코퍼스로는 scripts/eval_agent.py(추후 과제)가
# 재조정한다.
_MIN_QUOTE = 4

# 순수 문장부호(표 구분선 "|", 구분선 "---" 등)는 아무리 길어도 "근거"가
# 아니다 — 문서 어디에나 우연히 있을 뿐 지적의 내용을 담지 못한다.
_HAS_ALNUM = re.compile(r"[^\W_]", re.UNICODE)


def _norm(text: str) -> str:
    """공백만 눌러 비교한다.

    모델이 공백을 다르게 옮겨 적는 것까지 환각으로 볼 필요는 없다. 다만 글자를
    바꾸는 것은 환각이다 — 그래서 공백 외에는 아무것도 건드리지 않는다.
    """
    return _WS.sub(" ", text).strip()


def _is_substantive(needle: str) -> bool:
    """근거로 쓸 만큼 실질적인 인용인지 판정한다.

    빈 문자열(공백만 있던 인용 포함)은 길이 0이라 이미 문턱 미달이다 —
    별도 분기 없이 이 함수 하나로 "비어있음/너무 짧음/문장부호뿐임"을
    한꺼번에 잡아낸다.
    """
    return len(needle) >= _MIN_QUOTE and bool(_HAS_ALNUM.search(needle))


_IMAGE_MARK = re.compile(r"^\s*\[그림\s+(\d+)\s*[:\]]")


def _image_no(line: str) -> int | None:
    """`[그림 3: 설명]` 줄이면 3. 아니면 None.

    그림 설명은 파싱 본문에만 있고 뷰어용 PDF 의 텍스트 레이어에는 없다(거기엔
    이미지가 있다). 그래서 그 설명에서 나온 지적은 인용문으로 위치를 찾을 수 없고,
    **그림 자체에** 형광펜을 얹어야 한다. 그 연결을 여기서 만든다 — 인용문이 어느
    줄에서 확인됐는지 아는 곳이 여기뿐이다.
    """
    m = _IMAGE_MARK.match(line)
    return int(m.group(1)) if m else None


def verify_quotes(doc: Document,
                  quotes: list[str]) -> tuple[list[Evidence], list[str]]:
    """(확인된 근거, 확인 실패한 인용문).

    두 번째 값(missing)에는 "실질적인 인용인데 문서에서 찾지 못한 것"만
    들어간다. 너무 짧거나(공백뿐 포함) 문장부호뿐인 인용은 검색조차 하지
    않고 조용히 버린다 — 근거로 세지 않지만, missing에 넣지도 않는다.
    검색하지 않은 문자열을 "원문에서 확인 못 함"이라 보고하면 거짓이기
    때문이다(실제로는 문서 어딘가에 있을 수도 있다). 그 결과 짧은 인용이
    다른 실질적인 인용까지 missing으로 끌고 가 지적 전체를 죽이는 일이
    없다 — loop.py는 found가 비어 있을 때만(=실질적인 근거가 하나도
    없을 때만) 지적을 강등한다.
    """
    lines: list[tuple[str, object, int | None]] = []
    sections_norm: list[tuple[str, object]] = []
    for section in doc.iter_sections():
        for line in (section.text or "").split("\n"):
            norm = _norm(line)
            if norm:
                lines.append((norm, section.anchor, _image_no(line)))
        sec_norm = _norm(section.text or "")
        if sec_norm:
            sections_norm.append((sec_norm, section.anchor))

    found: list[Evidence] = []
    missing: list[str] = []
    for quote in quotes:
        needle = _norm(quote)
        if not _is_substantive(needle):
            # 너무 짧거나(공백뿐 포함) 문장부호뿐이면 근거로 세지 않는다.
            # 다만 검색조차 하지 않았으므로 missing에도 넣지 않는다 — 다른
            # 인용까지 이 때문에 죽이지는 않는다.
            continue
        for norm_line, anchor, image_no in lines:
            if needle in norm_line:
                found.append(Evidence(anchor=anchor, quote=quote,
                                      image_no=image_no))
                break
        else:
            # 수정 2026-08-06: 줄 단위 대조만으로는 줄 경계를 걸치는 인용
            # (PDF 하드 줄바꿈으로 나뉜 문장, 표 행을 이어 읽은 인용)이 원문에
            # 실재해도 missing 으로 떨어져 진짜 지적이 오폐기됐다. 절 전체를
            # 공백 정규화한 문자열에서 한 번 더 찾는다 — 글자는 그대로 대조하므로
            # 환각 방어력은 같고, 개행 위치만 용서한다. (그림 연결(image_no)은
            # 줄 단위에서만 알 수 있어 이 경로에서는 None.)
            for sec_norm, anchor in sections_norm:
                if needle in sec_norm:
                    found.append(Evidence(anchor=anchor, quote=quote,
                                          image_no=None))
                    break
            else:
                missing.append(quote)
    return found, missing
