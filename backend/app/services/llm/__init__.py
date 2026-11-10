from functools import lru_cache

from app.config import get_settings
from app.services.llm.base import LLMProvider, LLMUnavailable
from app.services.llm.gigachat import GigaChatProvider
from app.services.llm.ollama import OllamaProvider
from app.services.llm.openai_compat import OpenAICompatProvider
from app.services.llm.yandex import YandexGPTProvider
from app.services.pii import mask_pii


class MaskedLLM(LLMProvider):
    def __init__(self, inner: LLMProvider):
        self.inner = inner

    async def complete(self, system: str, user: str, json_mode: bool = False, temperature: float = 0.2) -> str:
        return await self.inner.complete(system, mask_pii(user), json_mode=json_mode, temperature=temperature)


@lru_cache
def get_llm() -> LLMProvider:
    s = get_settings()
    provider = s.llm_provider.lower()
    if provider == "ollama":
        inner: LLMProvider = OllamaProvider(s.ollama_base_url, s.ollama_model)
    elif provider == "openai":
        inner = OpenAICompatProvider(s.openai_base_url, s.openai_api_key, s.openai_model)
    elif provider == "gigachat":
        inner = GigaChatProvider(s.gigachat_auth_key, s.gigachat_scope, s.gigachat_model)
    elif provider == "yandex":
        inner = YandexGPTProvider(s.yandex_api_key, s.yandex_folder_id, s.yandex_model)
    else:
        raise ValueError(f"unknown LLM_PROVIDER: {s.llm_provider}")
    return MaskedLLM(inner)


__all__ = ["LLMProvider", "LLMUnavailable", "get_llm"]
