FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app

RUN pip install --no-cache-dir aiogram==3.17.0 httpx==0.28.1 pydantic-settings==2.7.0

COPY bot/ ./bot/

CMD ["python", "-m", "bot.main"]
