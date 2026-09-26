from collections.abc import Iterator
from openai import OpenAI
from pydantic import BaseModel
from config import config

Messages = list[dict[str, str]]


class LLMClient:
    def __init__(
        self,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        if not config.AI_GATEWAY_API_KEY:
            raise RuntimeError("缺少 AI_GATEWAY_API_KEY，請在 config/.env 設定")
        self.model = model or config.LLM_MODEL
        self.max_tokens = max_tokens or config.LLM_MAX_TOKENS
        self._client = OpenAI(api_key=config.AI_GATEWAY_API_KEY, base_url=config.LLM_BASE_URL)

    def chat(self, prompt: str | Messages, system: str | None = None) -> str:
        """一次拿回完整回答。"""
        response = self._client.chat.completions.create(**self._params(prompt, system))
        return response.choices[0].message.content or ""

    def stream(self, prompt: str | Messages, system: str | None = None) -> Iterator[str]:
        """邊生成邊回傳文字片段。"""
        for chunk in self._client.chat.completions.create(**self._params(prompt, system), stream=True):
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def parse[T: BaseModel](self, prompt: str | Messages, schema: type[T], system: str | None = None) -> T:
        """Structured Outputs：回答保證符合 schema（pydantic 模型），直接回傳解析好的物件。"""
        response = self._client.chat.completions.parse(**self._params(prompt, system), response_format=schema)
        message = response.choices[0].message
        if message.parsed is None:
            raise RuntimeError(f"LLM 沒有回傳結構化結果：{message.refusal or response.choices[0].finish_reason}")
        return message.parsed

    def _params(self, prompt: str | Messages, system: str | None) -> dict:
        messages = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else list(prompt)
        if system:
            messages.insert(0, {"role": "system", "content": system})
        return {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens": self.max_tokens,
        }
