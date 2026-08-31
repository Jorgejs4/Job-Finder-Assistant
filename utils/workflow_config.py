"""Validated, serializable configuration for one tenant workflow."""

from __future__ import annotations

import hashlib
import json
from datetime import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkflowConfig(BaseModel):
    """Only user-controlled workflow knobs; secrets are never part of this model."""

    model_config = ConfigDict(extra="forbid")

    locations: list[str] = Field(default_factory=lambda: ["Sevilla", "Remoto"], min_length=1, max_length=20)
    years_of_experience: int = Field(default=0, ge=0, le=60)
    min_salary: int | None = Field(default=20000, ge=0, le=2_000_000)
    max_jobs_per_scraper: int = Field(default=250, ge=1, le=2_000)
    use_jobspy: bool = True
    jobspy_sites: list[str] = Field(default_factory=lambda: ["indeed", "glassdoor", "google"], max_length=10)
    headless: bool = False
    max_gemini_jobs: int = Field(default=0, ge=0, le=2_000)
    workers: int = Field(default=3, ge=1, le=20)
    rate_limit_seconds: float = Field(default=6.0, ge=0, le=600)
    schedule_time: str = "07:00"
    frequency_hours: int = Field(default=12, ge=1, le=168)
    reanalyze: bool = False
    reanalysis_limit: int = Field(default=0, ge=0, le=2_000)
    reanalysis_workers: int = Field(default=1, ge=1, le=20)
    force_missing_documents: bool = False

    @field_validator("locations", "jobspy_sites")
    @classmethod
    def clean_strings(cls, values: list[str]) -> list[str]:
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        if not cleaned:
            raise ValueError("la lista no puede estar vacía")
        return list(dict.fromkeys(cleaned))

    @field_validator("schedule_time")
    @classmethod
    def valid_time(cls, value: str) -> str:
        try:
            time.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("schedule_time debe usar HH:MM") from exc
        return value[:5]

    @classmethod
    def from_mapping(cls, value: "WorkflowConfig | dict[str, Any] | None") -> "WorkflowConfig":
        return value if isinstance(value, cls) else cls.model_validate(value or {})

    def analysis_hash(self) -> str:
        payload = self.model_dump(include={"years_of_experience", "min_salary", "max_gemini_jobs", "reanalysis_limit"})
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
