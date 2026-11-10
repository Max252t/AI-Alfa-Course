import time
import uuid

import httpx

from app.services.llm.base import LLMProvider, LLMUnavailable

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"


class GigaChatProvider(LLMProvider):
    def __init__(self, auth_key: str, scope: str, model: str):
        self.auth_key = auth_key
        self.scope = scope
        self.model = model
        self._token = ""
        self._expires_at = 0.0

    async def _ensure_token(self, client: httpx.AsyncClient) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token
        response = await client.post(
            OAUTH_URL,
            headers={
                "Authorization": f"Basic {self.auth_key}",
                "RqUID": str(uuid.uuid4()),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"scope": self.scope},
        )
        response.raise_for_status()
        data = response.json()
        self._token = data["access_token"]
        self._expires_at = data["expires_at"] / 1000
        return self._token

    async def complete(self, system: str, user: str, json_mode: bool = False, temperature: float = 0.2) -> str:
        suffix = "\nОтветь только валидным JSON." if json_mode else ""
        payload = {
            "model": self.model,
            "temperature": max(temperature, 0.01),
            "messages": [
                {"role": "system", "content": system + suffix},
                {"role": "user", "content": user},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=60, verify=False) as client:
                token = await self._ensure_token(client)
                response = await client.post(
                    CHAT_URL, json=payload, headers={"Authorization": f"Bearer {token}"}
                )
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMUnavailable(str(exc)) from exc
