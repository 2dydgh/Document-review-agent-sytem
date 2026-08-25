"""로컬 LLM 어댑터 — OpenAI 호환 `/v1/chat/completions`.

vLLM(사내 서버), Ollama, LM Studio가 모두 이 규격을 낸다. 그래서 Ollama 전용
`/api/chat` 대신 이쪽을 쓴다. 서버를 바꿔도 base_url/model만 고치면 된다.

의존성을 늘리지 않으려고 표준 라이브러리(urllib)만 쓴다. 호출량이 요건 수만큼
(수십~수백 회)이라 커넥션 풀링이 필요할 정도는 아니다.

**실패는 반드시 드러낸다.** 예전에는 타임아웃/서버다운을 빈 응답으로 바꿔
돌려줬는데, 체커가 그걸 "모순 없음"으로 읽어 지적사항이 조용히 사라졌다.
지금은 Response.error에 이유를 담고, 체커가 "검토되지 않음"으로 리포트한다.

사고(reasoning) 끄기:
  - vLLM: chat_template_kwargs로 꺼진다. 27B 기준 4케이스 76.8s → 1.1s (정확도 동일).
  - Ollama의 /v1: 이 옵션을 무시한다 (think/reasoning_effort/no_think 모두 무효).
    사고가 켜진 채 폭주해 타임아웃이 나기도 한다 → max_tokens와 error로 막는다.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import Response


class LocalLLMError(RuntimeError):
    """설정이 잘못된 경우처럼, 조용히 넘기면 안 되는 오류."""


class LocalClient:
    def __init__(self, model: str, base_url: str = "http://127.0.0.1:11434/v1",
                 timeout: float = 120.0, temperature: float = 0.0,
                 api_key: str = "", thinking: bool = False,
                 max_tokens: int = 1024) -> None:
        if not model:
            raise LocalLLMError(
                "settings.toml의 [llm] model이 비어 있습니다. "
                '예: model = "Qwen/Qwen3.6-27B"')
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # 같은 문서를 두 번 돌리면 같은 결과가 나와야 검토 결과를 신뢰할 수 있다.
        self.temperature = temperature
        self.api_key = api_key
        self.thinking = thinking
        # 사고가 켜진 모델이 폭주해 응답 없이 끝나는 것을 막는 상한.
        self.max_tokens = max_tokens

    def _payload(self, messages: list[dict]) -> dict:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if not self.thinking:
            # vLLM은 이걸로 사고를 끈다. 모르는 서버는 무시하므로 보내도 안전하다.
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        return payload

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def complete(self, prompt: str, **opts) -> Response:
        return self.chat([{"role": "user", "content": prompt}], **opts)

    def chat(self, messages: list[dict], **opts) -> Response:
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(self._payload(messages)).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return Response(text="", error=f"HTTP {exc.code}")
        except TimeoutError:
            return Response(text="", error=f"{self.timeout:.0f}초 안에 응답 없음")
        except urllib.error.URLError as exc:
            return Response(text="", error=f"{self.base_url} 에 연결할 수 없음 ({exc.reason})")
        except OSError as exc:
            return Response(text="", error=f"{self.base_url} 에 연결할 수 없음 ({exc})")
        except json.JSONDecodeError:
            return Response(text="", error="응답이 JSON이 아님")

        try:
            choice = body["choices"][0]
            text = choice["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return Response(text="", error="응답 형식이 예상과 다름")

        text = _clean(text)
        # 사고에 토큰을 다 쓰고 답을 못 낸 경우. 빈 응답으로 넘기면 "이상 없음"이 된다.
        if not text and choice.get("finish_reason") == "length":
            return Response(text="", error=f"출력 한도({self.max_tokens} 토큰) 초과")
        return Response(text=text)


def _clean(text: str) -> str:
    """모델이 답 대신 내놓는 껍데기를 걷어낸다.

    - Ollama의 qwen3는 사고를 <think>...</think>로 본문에 섞는다. 남겨두면
      응답이 'ISSUE:'로 시작하지 않아 정상 지적까지 버려진다.
    - 사내 Qwen3.6은 "모순 없음"을 빈 문자열이 아니라 따옴표 두 개(`""`)로 답한다.
    """
    close = "</think>"
    if close in text:
        text = text.rsplit(close, 1)[1]
    text = text.strip()
    if text in ('""', "''", '""""'):
        return ""
    return text
