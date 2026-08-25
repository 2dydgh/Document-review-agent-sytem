"""LLM 응답에서 유일한 JSON 결과를 안전하게 고르는 공용 파서."""
from __future__ import annotations

import json

from .verify import _norm

# 매 턴 새 디코더를 만들 필요가 없다 — raw_decode는 상태를 갖지 않는다.
_DECODER = json.JSONDecoder()

# 연속으로 실패한 raw_decode 시도를 이 횟수에서 끊는다(성공하면 0으로
# 리셋된다 — 아래 _scan 참고). 성공한 자리는 i=end로 건너뛰어 값싸지만,
# 실패는 그렇지 않다 — max_tokens에 잘려 닫히지 않은 중첩(`'{"a":' * 16000`
# 처럼 실제로 나오는 응답)은 모든 여는 '{'마다 매번 끝까지 깊게 재시도하다
# 실패하므로, 상한이 없으면 사실상 O(n²)이 된다(실측: 8만자에서 4.6초).
# 상한을 넘으면 스캔을 그 자리에서 포기한다 — 그 뒤에 진짜 판정이 남아
# 있었다면 놓칠 수 있다. 다만 놓친 결과는 "빈 후보"이지 "틀린 판정"이
# 아니다: `_parse`가 None을 돌려주면 호출부는 응답을 채택하지 않는다.
_MAX_FAILED_DECODES = 500


def _candidate_key(obj: dict) -> str:
    """후보의 내용을 비교 가능한 문자열로 정규화한다(딕셔너리는 해시 불가).

    reasoning 모델이 fenced code block의 JSON을 요약 문장에서 다시 옮겨
    적을 때 문자열 값 안의 공백이 한 칸 어긋나는 일이 흔하다. 그 정도
    차이까지 "다른 후보"로 세면 진짜 모호함이 아닌데 재시도로 밀려나
    검증까지 끝난 판정이 버려진다 — verify._norm이 인용 대조에서 공백
    차이를 이미 봐주는 것과 같은 이유로, 여기서도 공백만 눌러 비교한다.
    """
    return _norm(json.dumps(obj, sort_keys=True, ensure_ascii=False))


def _dedupe(objs: list[dict]) -> list[dict]:
    """내용이 같은 후보는 하나로 합친다.

    reasoning 모델은 fenced code block에 답을 낸 뒤 "요약하면 ~입니다"로
    같은 JSON을 한 번 더 되풀이하는 일이 흔하다. 모호함은 "서로 다른 답이
    둘"이지 "같은 답의 반복"이 아니다 — 내용이 같은 객체를 여러 개로 세면
    재시도로 밀려나 검증까지 끝난 진짜 판정이 버려진다.
    """
    seen: dict[str, dict] = {}
    for obj in objs:
        seen.setdefault(_candidate_key(obj), obj)
    return list(seen.values())


def _scan(text: str, keys: tuple[str, ...] = ("verdict", "tool")) -> tuple[list[dict], list[dict]]:
    """text에 등장하는 '{' 위치마다 raw_decode를 시도해 골라낸다.

    keys 중 하나라도 가진 객체는 candidates로, 디코드는 됐지만 그 키가 없는
    객체("thought" 같은 추론 객체, 혹은 {"result": {...}} 같은 래퍼)는
    others로 따로 모은다 — 최상위에 후보가 없을 때 others 안을 한 단계만
    들여다보기 위해서다. keys를 인자로 받는 이유는 agent 말고 다른 체커도
    같은 파서를 써야 하기 때문이다(표현 점검은 {"issue": ...}를 낸다) —
    환각 방지 파서가 두 벌이 되면 한쪽만 고쳐지고 다른 쪽은 뚫린다.

    raw_decode는 재귀 하강 파서라 중첩이 깊으면 RecursionError를 낸다(예:
    `'{"a":' * 10000 + '1' + '}' * 10000`). JSONDecodeError의 하위 클래스가
    아니라서 따로 잡아야 한다 — 안 그러면 검사기 밖으로 예외가 샌다.

    성공적으로 디코드된 지점은 그 끝(end)까지 건너뛴다 — 이미 소비한 구간의
    접미사들을 계속 다시 파싱하지 않는다. 하지만 이건 성공한 자리에만
    해당한다: 실패하면 i += 1로 한 글자만 전진하므로, 닫히지 않은 중첩
    (max_tokens에 잘린 응답, 예: `'{"a":' * 16000`)은 모든 여는 '{'마다
    매번 끝까지 깊게 재시도하다 실패해 사실상 O(n²)이 된다. 그래서 *연속*
    실패 횟수를 _MAX_FAILED_DECODES로 별도로 막는다 — i=end 스킵은 성공
    경로만 값싸게 만들 뿐, 실패 경로의 반복 재파싱까지 막아주지 않는다.
    성공할 때마다 실패 카운터를 0으로 되돌린다: 프로즈 속에 중괄호가
    여기저기 흩어진 정상적인 긴 응답도 실패가 누적될 수 있으므로, 상한을
    "연속" 실패에만 걸어야 그 사이사이의 성공(예: 앞쪽의 추론 객체)이
    카운터를 갉아먹지 않는다.
    """
    candidates: list[dict] = []
    others: list[dict] = []
    i, n = 0, len(text)
    failed = 0
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        try:
            obj, end = _DECODER.raw_decode(text, i)
        except (json.JSONDecodeError, RecursionError):
            failed += 1
            if failed > _MAX_FAILED_DECODES:
                break  # 연속 실패 상한 — 닫히지 않은 중첩으로 보고 스캔을 포기한다
            i += 1
            continue
        failed = 0  # 성공했으니 연속 실패 카운트를 리셋한다
        if isinstance(obj, dict):
            if any(k in obj for k in keys):
                candidates.append(obj)
            else:
                others.append(obj)
        i = end  # 성공한 자리는 끝까지 건너뛴다 — 재파싱 방지
    return candidates, others


def _parse(text: str, keys: tuple[str, ...] = ("verdict", "tool")) -> dict | None:
    """모델 응답에서 JSON 하나를 꺼낸다. 설명이 붙어 있어도 골라낸다.

    옛 구현(탐욕적 정규식 `\\{.*\\}`)은 첫 '{'부터 마지막 '}'까지를 통째로
    잡아먹는다. reasoning 모델이 "생각: {검토중} 입니다.\\n{실제 JSON}"처럼
    프로즈 속에 중괄호를 흘리거나 JSON 객체를 두 개 내면 그 통짜가 파싱에
    실패해 재시도 1회를 날리고 그룹째 판단불가로 떨어진다 — 배포 대상인
    reasoning 계열 로컬 Qwen이 실제로 이렇게 답한다.

    대신 `_scan`으로 '{' 위치마다 실제로 파싱되는 조각만 골라내고, 그중
    "verdict"나 "tool" 키를 가진 것만 후보로 삼는다. 최상위에 후보가
    하나도 없으면 — 흔한 래퍼 `{"result": {...}}`나 `{"action": {...}}`
    안에 진짜 판정/도구 호출이 숨어 있을 수 있으므로 — others의 각 값을
    한 단계만 더 들여다봐 candidates 여부를 다시 검사한다. 더 깊이는
    내려가지 않는다: 재귀적으로 내려가면 모델이 "만약 ~였다면 이렇게
    답했을 것"이라며 덧붙인 예시 JSON이 어느 래퍼 안에 중첩돼 있을 때
    그 illustrative aside까지 후보로 되살아나 모호함 감지를 우회한다.

    후보를 내용으로 중복 제거(`_dedupe`)한 뒤 정확히 하나면 그것을 쓴다.
    0개(파싱 실패, 혹은 verdict/tool 키를 가진 객체가 하나도 없음)면 None을
    돌려줘 재시도 경로를 타게 한다. 서로 다른 내용의 후보가 둘 이상이면
    "마지막 객체가 이긴다"는 규칙을 쓰지 않는다 — 검증까지 끝난 진짜 판정이
    예시로 조용히 대체될 수 있기 때문이다. 어느 쪽이 진짜인지 코드가
    추측하지 않고 None을 돌려줘, 모델에게 JSON 하나만 요구하는 재시도로
    넘긴다 — 재시도 후에도 모호하면 판단불가로 끝난다. 반면 같은 내용을
    두 번 반복한 것은 모호함이 아니다 — 하나로 합쳐 그대로 쓴다.
    """
    if not text:
        return None
    candidates, others = _scan(text, keys)
    if not candidates:
        # 최상위 후보가 없을 때만 한 단계 내려간다 — 이미 후보가 있으면
        # 래퍼 속에 숨은 예시까지 끌어올려 모호함을 만들 이유가 없다.
        for obj in others:
            for value in obj.values():
                if isinstance(value, dict) and any(k in value for k in keys):
                    candidates.append(value)
    unique = _dedupe(candidates)
    if len(unique) == 1:
        return unique[0]
    return None  # 0개(파싱 실패) 또는 서로 다른 후보 2개 이상(모호)
