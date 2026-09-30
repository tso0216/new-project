import json
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
        reasoning_effort: str | None = None,
    ) -> None:
        self.manual = config.LLM_MANUAL
        self.model = model or config.LLM_MODEL
        self.max_tokens = max_tokens or config.LLM_MAX_TOKENS
        self.reasoning_effort = reasoning_effort or config.LLM_REASONING_EFFORT
        if self.manual:
            return
        if not config.OPENAI_API_KEY:
            raise RuntimeError("缺少 OPENAI_API_KEY，請在 config/.env 設定，或把 config.py 的 LLM_MANUAL 改成 True 改用人工貼上回答")
        self._client = OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.LLM_BASE_URL)

    def chat(self, prompt: str | Messages, system: str | None = None) -> str:
        """一次拿回完整回答。"""
        if self.manual:
            return self._ask_human(prompt, system)
        response = self._client.chat.completions.create(**self._params(prompt, system))
        return response.choices[0].message.content or ""

    def stream(self, prompt: str | Messages, system: str | None = None) -> Iterator[str]:
        """邊生成邊回傳文字片段。"""
        if self.manual:
            yield self._ask_human(prompt, system)
            return
        for chunk in self._client.chat.completions.create(**self._params(prompt, system), stream=True):
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def parse[T: BaseModel](self, prompt: str | Messages, schema: type[T], system: str | None = None) -> T:
        """JSON 模式：回答必須是 JSON，再用 schema（pydantic 模型）解析。格式細節寫在提示詞裡，
        不用 Structured Outputs，所以欄位改了不用動程式。JSON 或 schema 不符時丟 ValueError（含 pydantic ValidationError）。"""
        if self.manual:
            return self._ask_human_parse(prompt, schema, system)
        response = self._client.chat.completions.create(**self._params(prompt, system),
                                                        response_format={"type": "json_object"})
        choice = response.choices[0]
        if not choice.message.content:
            raise RuntimeError(f"LLM 沒有回傳內容：{choice.message.refusal or choice.finish_reason}")
        return schema.model_validate_json(choice.message.content)

    def _ask_human(self, prompt: str | Messages, system: str | None, extra: str = "") -> str:
        """人工模式：印出完整提示詞，讀使用者貼回的回答（多行，單獨一行 END 結束）。"""
        params = self._params(prompt, system)
        print("\n" + "=" * 20 + " 複製以下提示詞給 LLM " + "=" * 20)
        for m in params["messages"]:
            print(f"\n[{m['role']}]\n{m['content']}")
        if extra:
            print(f"\n{extra}")
        print("=" * 20 + " 提示詞結束 " + "=" * 20)
        print("貼上 LLM 的回答，最後單獨一行輸入 END：")
        lines = []
        while True:
            line = input()  # 沒有更多輸入時讓 EOFError 往外丟；吞掉會讓 _ask_human_parse 對著空字串無限重問
            if line.strip() == "END":
                break
            lines.append(line)
        return "\n".join(lines).strip()

    def _ask_human_parse[T: BaseModel](self, prompt: str | Messages, schema: type[T], system: str | None) -> T:
        extra = ("請只輸出符合下列 JSON Schema 的 JSON（不要加說明文字）：\n"
                 + json.dumps(schema.model_json_schema(), ensure_ascii=False))
        while True:
            text = self._ask_human(prompt, system, extra)
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            try:
                return schema.model_validate_json(text)
            except ValueError as e:  # pydantic ValidationError 是 ValueError 子類
                print(f"回答不符合 schema，請重新貼上：{e}")

    def _params(self, prompt: str | Messages, system: str | None) -> dict:
        messages = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else list(prompt)
        if system:
            messages.insert(0, {"role": "system", "content": system})
        return {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens": self.max_tokens,
            "reasoning_effort": self.reasoning_effort,
        }
