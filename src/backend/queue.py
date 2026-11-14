"""Task Queue Abstraction with Redis and In-Memory Fallback."""
import asyncio
import json
import socket
from typing import Any, Dict, Optional
import redis.asyncio as aioredis

from src.agentops.logging import app_logger
from src.agentops.metrics import QUEUE_DEPTH_CURRENT
from src.agentops.tracing import inject_trace_context
from src.config import settings

def _is_redis_port_open(host: str, port: int, timeout_sec: float = 0.05) -> bool:
    """Fast synchronous pre-check to prevent connection hangs when Redis is absent."""
    try:
        target_host = "127.0.0.1" if host in ("localhost", "127.0.0.1") else host
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout_sec)
            s.connect((target_host, port))
            return True
    except Exception:
        return False

class TaskQueue:
    """Manages asynchronous incident job queue with Redis and local fallback."""

    def __init__(self):
        self.redis_client: Optional[aioredis.Redis] = None
        self._in_memory_queue: asyncio.Queue = asyncio.Queue()
        self._use_redis = False

    async def initialize(self):
        """Attempts to connect to the Redis queue server."""
        if not _is_redis_port_open(settings.redis_host, settings.redis_port):
            self._use_redis = False
            app_logger.info(f"Redis not detected on {settings.redis_host}:{settings.redis_port}. Using in-memory queue.")
            return

        try:
            client = aioredis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                password=settings.redis_password,
                db=settings.redis_db,
                socket_timeout=1.0,
                socket_connect_timeout=1.0
            )
            await asyncio.wait_for(client.ping(), timeout=1.0)
            self.redis_client = client
            self._use_redis = True
            app_logger.info(f"Connected to Redis queue on {settings.redis_host}:{settings.redis_port}")
        except Exception as e:
            self._use_redis = False
            if self.redis_client:
                try:
                    await self.redis_client.aclose()
                except Exception:
                    pass
                self.redis_client = None
            app_logger.warning(f"Redis unavailable ({e}). Using in-memory asynchronous queue fallback.")

    async def enqueue(self, task: Dict[str, Any]) -> str:
        """
        Enqueues an incident triage task with injected W3C OpenTelemetry trace context.
        """
        # Inject distributed trace context into task dictionary
        carrier = task.setdefault("_trace_carrier", {})
        inject_trace_context(carrier)

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
        """
        Dequeues an incident triage task, blocking up to timeout_seconds.
        """
        if self._use_redis and self.redis_client:
            try:
                res = await self.redis_client.blpop(settings.queue_name, timeout=int(timeout_seconds))
                if res:
                    _, payload = res
                    depth = await self.redis_client.llen(settings.queue_name)
                    QUEUE_DEPTH_CURRENT.set(depth)
                    data = json.loads(payload)
                    return data
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
        """Returns the current number of pending items in the queue."""
        if self._use_redis and self.redis_client:
            try:
                return await self.redis_client.llen(settings.queue_name)
            except Exception:
                pass
        return self._in_memory_queue.qsize()

    def is_connected(self) -> bool:
        """Returns True if connected to Redis message queue."""
        return self._use_redis and self.redis_client is not None

task_queue = TaskQueue()
