import hashlib
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def hash_tg_id(tg_id: int, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{tg_id}".encode()).hexdigest()


def with_utm(url: str | None, content: str, material_id: str | None, user_hash: str) -> str | None:
    if not url:
        return None
    parts = urlparse(url)
    query = dict(parse_qsl(parts.query))
    query.update(
        {
            "utm_source": "tg_bot",
            "utm_medium": "bot",
            "utm_content": content,
            "utm_campaign": material_id or "none",
            "utm_term": user_hash[:12],
        }
    )
    return urlunparse(parts._replace(query=urlencode(query)))
