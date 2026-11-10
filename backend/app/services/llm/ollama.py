import httpx

from app.services.llm.base import LLMProvider, LLMUnavailable


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def complete(self, system: str, user: str, json_mode: bool = False, temperature: float = 0.2) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": temperature},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            payload["format"] = "json"
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                return response.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMUnavailable(str(exc)) from exc
