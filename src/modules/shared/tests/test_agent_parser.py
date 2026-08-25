"""표현 점검과 근거 재확인이 공유하는 LLM JSON 응답 파서."""
import json

from modules.shared import _parse


def test_parse_accepts_one_result_object_with_surrounding_text():
    text = '설명\n' + json.dumps({"results": []}, ensure_ascii=False) + '\n끝'
    assert _parse(text, keys=("results",)) == {"results": []}


def test_parse_accepts_one_level_wrapper():
    text = json.dumps({"result": {"quotes": ["원문 근거"]}}, ensure_ascii=False)
    assert _parse(text, keys=("quotes",)) == {"quotes": ["원문 근거"]}


def test_parse_deduplicates_repeated_same_answer():
    answer = json.dumps({"verdict": "철회"}, ensure_ascii=False)
    assert _parse(f"{answer}\n{answer}") == {"verdict": "철회"}


def test_parse_rejects_two_different_answers():
    text = '{"verdict":"철회"}\n{"quotes":["다른 답"]}'
    assert _parse(text, keys=("verdict", "quotes")) is None


def test_parse_rejects_broken_or_empty_output():
    assert _parse("") is None
    assert _parse('{"verdict":') is None


def test_parse_handles_pathologically_deep_json_without_raising():
    text = '{"a":' * 2_000 + "1" + "}" * 2_000
    assert _parse(text) is None
