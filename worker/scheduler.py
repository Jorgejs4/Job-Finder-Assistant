"""Race-free scheduler backed by a Supabase RPC claim operation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable


class Scheduler:
    def __init__(self, client: Any, dispatch: Callable[..., Any]):
        self.client = client
        self.dispatch = dispatch

    def claim_due(self, *, limit: int = 20, lease_seconds: int = 900) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100 or not 60 <= lease_seconds <= 86400:
            raise ValueError("limit o lease_seconds fuera de rango")
        response = self.client.rpc(
            "claim_due_workflows",
            {"p_limit": limit, "p_lease_seconds": lease_seconds},
        ).execute()
        return list(getattr(response, "data", response) or [])

    def dispatch_due(self, **kwargs: Any) -> int:
        count = 0
        for row in self.claim_due(**kwargs):
            self.dispatch(row["user_id"], row.get("config") or {})
            schedule = row.get("config") or {}
            frequency = max(1, min(int(schedule.get("frequency_hours", 12)), 168))
            next_run = self._next_run(schedule, frequency)
            self.client.table("workflow_schedules").update({
                "next_run_at": next_run.isoformat(),
                "claimed_until": None,
            }).eq("user_id", row["user_id"]).execute()
            count += 1
        return count

    @staticmethod
    def _next_run(schedule: dict[str, Any], frequency: int) -> datetime:
        now = datetime.now(timezone.utc)
        try:
            hour, minute = (int(part) for part in str(schedule.get("schedule_time", "07:00")).split(":", 1))
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except (TypeError, ValueError):
            candidate = now
        while candidate <= now:
            candidate += timedelta(hours=frequency)
        return candidate
