"""Task Queue Abstraction with Redis and In-Memory Fallback."""
import asyncio
import json
from typing import Any, Dict, Optional
import redis.asyncio as aioredis
from src.agentops.logging import app_logger
from src.agentops.metrics import QUEUE_DEPTH_CURRENT
from src.config import settings

class TaskQueue:
    """Manages asynchronous incident job queue with Redis and local fallback."""
    def __init__(self):
        self.redis_client: Optional[aioredis.Redis] = None
        self._in_memory_queue: asyncio.Queue = asyncio.Queue()
        self._use_redis = False

    async def initialize(self):
        try:
            client = aioredis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                password=settings.redis_password,
                db=settings.redis_db,
                socket_timeout=2.0
            )
            await client.ping()
            self.redis_client = client
            self._use_redis = True
            app_logger.info(f"Connected to Redis queue on {settings.redis_host}:{settings.redis_port}")
        except Exception as e:
            self._use_redis = False
            app_logger.warning(f"Redis unavailable ({e}). Using in-memory asynchronous queue fallback.")

    async def enqueue(self, task: Dict[str, Any]) -> str:
        payload = json.dumps(task)
        if self._use_redis and self.redis_client:
            try:
                await self.redis_client.rpush(settings.queue_name, payload)
                depth = await self.redis_client.llen(settings.queue_name)
                QUEUE_DEPTH_CURRENT.set(depth)
                return task.get("run_id", "unknown")
            except Exception as e:
                app_logger.warning(f"Redis enqueue failed ({e}), falling back to in-memory queue.")
        
        await self._in_memory_queue.put(task)
        QUEUE_DEPTH_CURRENT.set(self._in_memory_queue.qsize())
        return task.get("run_id", "unknown")

    async def dequeue(self, timeout_seconds: float = 1.0) -> Optional[Dict[str, Any]]:
        if self._use_redis and self.redis_client:
            try:
                res = await self.redis_client.blpop(settings.queue_name, timeout=int(timeout_seconds))
                if res:
                    _, payload = res
                    depth = await self.redis_client.llen(settings.queue_name)
                    QUEUE_DEPTH_CURRENT.set(depth)
                    return json.loads(payload)
            except Exception:
                pass

        try:
            task = await asyncio.wait_for(self._in_memory_queue.get(), timeout=timeout_seconds)
            self._in_memory_queue.task_done()
            QUEUE_DEPTH_CURRENT.set(self._in_memory_queue.qsize())
            return task
        except asyncio.TimeoutError:
            return None

    async def get_depth(self) -> int:
        if self._use_redis and self.redis_client:
            try:
                return await self.redis_client.llen(settings.queue_name)
            except Exception:
                pass
        return self._in_memory_queue.qsize()

task_queue = TaskQueue()
