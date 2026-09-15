"""Redis-backed enqueue boundary kept separate from HTTP and worker code."""

from os import getenv
from typing import Protocol

from arq.connections import RedisSettings, create_pool


class ReviewQueue(Protocol):
    async def enqueue(self, review_id: str) -> None: ...


class ArqReviewQueue:
    async def enqueue(self, review_id: str) -> None:
        settings = RedisSettings.from_dsn(getenv("REDIS_URL", "redis://localhost:6379/0"))
        redis = await create_pool(settings)
        try:
            await redis.enqueue_job("run_review", review_id)
        finally:
            await redis.aclose()
