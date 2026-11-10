import json
import re
from abc import ABC, abstractmethod


class LLMUnavailable(Exception):
    pass


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, system: str, user: str, json_mode: bool = False, temperature: float = 0.2) -> str: ...

    async def complete_json(self, system: str, user: str) -> dict:
        raw = await self.complete(system, user, json_mode=True, temperature=0.0)
        return parse_json(raw)


def parse_json(raw: str) -> dict:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMUnavailable("invalid json from model") from exc
    if not isinstance(value, dict):
        raise LLMUnavailable("json is not an object")
    return value
