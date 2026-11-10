import httpx

from bot.config import settings


class BackendError(Exception):
    pass


async def request(method: str, path: str, payload: dict | None = None, timeout: float = 120) -> dict | list:
    try:
        async with httpx.AsyncClient(base_url=settings.backend_url, timeout=timeout) as client:
            response = await client.request(method, path, json=payload)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise BackendError(str(exc)) from exc


async def chat(tg_id: int, chat_id: int, text: str) -> dict:
    return await request("POST", "/chat", {"tg_id": tg_id, "chat_id": chat_id, "text": text})


async def start(tg_id: int, chat_id: int) -> dict:
    return await request("POST", "/start", {"tg_id": tg_id, "chat_id": chat_id, "text": "/start"})


async def callback(tg_id: int, chat_id: int, data: str) -> dict:
    return await request("POST", "/callback", {"tg_id": tg_id, "chat_id": chat_id, "data": data})


async def command(tg_id: int, chat_id: int, name: str) -> list[dict]:
    return await request("POST", "/command", {"tg_id": tg_id, "chat_id": chat_id, "name": name})


async def reset(tg_id: int) -> None:
    await request("DELETE", f"/users/{tg_id}")
