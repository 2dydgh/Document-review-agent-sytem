import pytest

from modules.llm_client import build_llm
from modules.llm_client import EchoLLM, Response


def test_echo_llm_returns_empty():
    resp = EchoLLM().complete("무엇이든")
    assert isinstance(resp, Response)
    assert resp.text == ""


def test_echo_chat_returns_empty():
    """기본 클라이언트는 다중 턴에서도 지적을 지어내지 않는다."""
    resp = EchoLLM().chat([{"role": "user", "content": "안녕"}])
    assert resp.text == ""
    assert resp.error is None


class _Cfg:
    def __init__(self, provider):
        self.llm_provider = provider


def test_build_llm_echo():
    assert isinstance(build_llm(_Cfg("echo")), EchoLLM)


def test_build_llm_unknown_raises():
    with pytest.raises(ValueError):
        build_llm(_Cfg("nope"))


def test_claude_stub_raises():
    from modules.llm_client.claude import ClaudeClient
    with pytest.raises(NotImplementedError):
        ClaudeClient().complete("x")


def test_build_llm_claude_passes_model():
    class _C:
        llm_provider = "claude"
        llm_model = "claude-x"
    from modules.llm_client.claude import ClaudeClient
    client = build_llm(_C())
    assert isinstance(client, ClaudeClient)
    assert client.model == "claude-x"
