"""Persistent and Stateful Run Tracking and Result Storage Module."""
import asyncio
from datetime import datetime, timezone
import json
import socket
import time
from typing import Any, Dict, Optional, Union
import redis.asyncio as aioredis

from src.agentops.logging import app_logger
from src.config import settings
from src.backend.schemas import (
    IncidentStatus,
    IncidentStatusResponse,
    IncidentResultResponse
)

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

class RunStorage:
    """Manages lifecycle statuses, agent output persistence, and idempotency mapping."""

    def __init__(self):
        self.redis_client: Optional[aioredis.Redis] = None
        self._use_redis = False
        # In-memory fallbacks
        self._statuses: Dict[str, Dict[str, Any]] = {}
        self._results: Dict[str, Dict[str, Any]] = {}
        self._idempotency_map: Dict[str, str] = {}
        self._timestamps: Dict[str, float] = {}

    async def initialize(self):
        """Attempts to connect to Redis for distributed state storage."""
        if not _is_redis_port_open(settings.redis_host, settings.redis_port):
            self._use_redis = False
            app_logger.info(f"Redis not detected on {settings.redis_host}:{settings.redis_port}. Using in-memory state store.")
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
            app_logger.info(f"Connected to Redis state store on {settings.redis_host}:{settings.redis_port}")
        except Exception as e:
            self._use_redis = False
            if self.redis_client:
                try:
                    await self.redis_client.aclose()
                except Exception:
                    pass
                self.redis_client = None
            app_logger.warning(f"Redis state store unavailable ({e}). Falling back to local state store.")

    async def create_run(
        self,
        run_id: str,
        alert_id: str,
        correlation_id: str,
        idempotency_key: Optional[str] = None
    ) -> IncidentStatusResponse:
        now_iso = datetime.now(timezone.utc).isoformat()
        now_ts = time.time()
        self._timestamps[run_id] = now_ts

        status_data = {
            "run_id": run_id,
            "alert_id": alert_id,
            "correlation_id": correlation_id,
            "status": IncidentStatus.QUEUED.value,
            "created_at": now_iso,
            "updated_at": now_iso,
            "completed_at": None,
            "queue_duration_seconds": None,
            "execution_duration_seconds": None,
            "retry_count": 0,
            "error": None
        }

        if self._use_redis and self.redis_client:
            try:
                key = f"incident:status:{run_id}"
                await self.redis_client.set(key, json.dumps(status_data), ex=86400)
                if idempotency_key:
                    await self.redis_client.set(f"incident:idempotency:{idempotency_key}", run_id, ex=86400)
            except Exception as e:
                app_logger.warning(f"Failed to write run status to Redis ({e}), using in-memory store.")

        self._statuses[run_id] = status_data
        if idempotency_key:
            self._idempotency_map[idempotency_key] = run_id

        return IncidentStatusResponse(**status_data)

    async def get_status(self, run_id: str) -> Optional[IncidentStatusResponse]:
        if self._use_redis and self.redis_client:
            try:
                data = await self.redis_client.get(f"incident:status:{run_id}")
                if data:
                    parsed = json.loads(data)
                    return IncidentStatusResponse(**parsed)
            except Exception:
                pass

        if run_id in self._statuses:
            return IncidentStatusResponse(**self._statuses[run_id])
        return None

    async def update_status(
        self,
        run_id: str,
        status: str,
        error: Optional[str] = None,
        retry_count: Optional[int] = None
    ) -> Optional[IncidentStatusResponse]:
        existing = await self.get_status(run_id)
        if not existing:
            return None

        now_iso = datetime.now(timezone.utc).isoformat()
        now_ts = time.time()
        created_ts = self._timestamps.get(run_id, now_ts)

        updated_dict = existing.model_dump()
        updated_dict["status"] = status
        updated_dict["updated_at"] = now_iso

        if status == IncidentStatus.PROCESSING.value:
            updated_dict["queue_duration_seconds"] = round(now_ts - created_ts, 4)

        if status in (IncidentStatus.COMPLETED.value, IncidentStatus.FAILED.value, IncidentStatus.ESCALATED.value):
            updated_dict["completed_at"] = now_iso
            queue_dur = updated_dict.get("queue_duration_seconds") or 0.0
            updated_dict["execution_duration_seconds"] = round(max(0.0, now_ts - created_ts - queue_dur), 4)

        if error is not None:
            updated_dict["error"] = error
        if retry_count is not None:
            updated_dict["retry_count"] = retry_count

        if self._use_redis and self.redis_client:
            try:
                key = f"incident:status:{run_id}"
                await self.redis_client.set(key, json.dumps(updated_dict), ex=86400)
            except Exception:
                pass

        self._statuses[run_id] = updated_dict
        return IncidentStatusResponse(**updated_dict)

    async def save_result(
        self,
        run_id: str,
        result: Union[IncidentResultResponse, Dict[str, Any]]
    ) -> None:
        result_dict = result.model_dump() if isinstance(result, IncidentResultResponse) else dict(result)

        if self._use_redis and self.redis_client:
            try:
                key = f"incident:result:{run_id}"
                await self.redis_client.set(key, json.dumps(result_dict), ex=86400)
            except Exception as e:
                app_logger.warning(f"Failed to save result to Redis ({e}), using in-memory store.")

        self._results[run_id] = result_dict

    async def get_result(self, run_id: str) -> Optional[Dict[str, Any]]:
        if self._use_redis and self.redis_client:
            try:
                raw = await self.redis_client.get(f"incident:result:{run_id}")
                if raw:
                    return json.loads(raw)
            except Exception:
                pass

        return self._results.get(run_id)

    async def get_run_by_idempotency_key(self, idempotency_key: str) -> Optional[str]:
        if not idempotency_key:
            return None
        if self._use_redis and self.redis_client:
            try:
                val = await self.redis_client.get(f"incident:idempotency:{idempotency_key}")
                if val:
                    return val.decode("utf-8") if isinstance(val, bytes) else str(val)
            except Exception:
                pass
        return self._idempotency_map.get(idempotency_key)

    def clear(self):
        """Clears local in-memory records (for test isolation)."""
        self._statuses.clear()
        self._results.clear()
        self._idempotency_map.clear()
        self._timestamps.clear()

run_storage = RunStorage()
