import httpx

from app.services.llm.base import LLMProvider, LLMUnavailable

URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


class YandexGPTProvider(LLMProvider):
    def __init__(self, api_key: str, folder_id: str, model: str):
        self.api_key = api_key
        self.model_uri = f"gpt://{folder_id}/{model}/latest"

    async def complete(self, system: str, user: str, json_mode: bool = False, temperature: float = 0.2) -> str:
        suffix = "\nОтветь только валидным JSON." if json_mode else ""
        payload = {
            "modelUri": self.model_uri,
            "completionOptions": {"stream": False, "temperature": temperature, "maxTokens": "1500"},
            "messages": [
                {"role": "system", "text": system + suffix},
                {"role": "user", "text": user},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(URL, json=payload, headers={"Authorization": f"Api-Key {self.api_key}"})
                response.raise_for_status()
                return response.json()["result"]["alternatives"][0]["message"]["text"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMUnavailable(str(exc)) from exc
