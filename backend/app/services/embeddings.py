import asyncio
from functools import lru_cache

from app.config import get_settings


@lru_cache
def _model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(get_settings().embedding_model)


def _encode(texts: list[str]) -> list[list[float]]:
    vectors = _model().encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
    return [v.tolist() for v in vectors]


def encode_passages_sync(texts: list[str]) -> list[list[float]]:
    return _encode([f"passage: {t}" for t in texts])


async def encode_query(text: str) -> list[float]:
    vectors = await asyncio.to_thread(_encode, [f"query: {text}"])
    return vectors[0]
