"""Server-side GitHub Actions dispatcher for tenant workflows."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .workflow_config import WorkflowConfig


class WorkflowDispatchError(RuntimeError):
    pass


def dispatch_workflow(
    user_id: str,
    config: WorkflowConfig | dict[str, Any] | None = None,
    *,
    workflow: str = "tenant-scrape.yml",
    repository: str | None = None,
    ref: str = "main",
    client: Any = None,
) -> None:
    """Dispatch a workflow. ``GITHUB_TOKEN`` is intentionally read only server-side."""
    uid = str(user_id or "").strip()
    if not uid or any(char in uid for char in "\r\n"):
        raise WorkflowDispatchError("user_id no válido")
    settings = WorkflowConfig.from_mapping(config)
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        try:
            import streamlit as st
            token = str(st.secrets.get("GITHUB_TOKEN", "") or "").strip()
        except Exception:
            token = ""
    repo = (repository or os.getenv("GITHUB_REPO", "")).strip()
    if not token:
        raise WorkflowDispatchError("GITHUB_TOKEN solo está disponible en el servidor y es obligatorio")
    if not repo or repo.count("/") != 1:
        raise WorkflowDispatchError("repository debe tener el formato owner/repository")
    if workflow not in {"tenant-scrape.yml", "tenant-reanalyze.yml"}:
        raise WorkflowDispatchError("workflow no permitido")

    inputs = {"user_id": uid, "config_json": json.dumps(settings.model_dump(), separators=(",", ":"))}
    own_client = client is None
    client = client or httpx.Client(timeout=30)
    try:
        response = client.post(
            f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches",
            headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}"},
            json={"ref": ref, "inputs": inputs},
        )
        if response.status_code not in (201, 204):
            # GitHub devuelve aquí la causa accionable (permisos, workflow
            # inexistente, rama incorrecta, inputs inválidos, etc.).
            detail = response.text.strip()
            if len(detail) > 500:
                detail = detail[:500] + "..."
            raise WorkflowDispatchError(
                f"GitHub rechazó el workflow ({response.status_code})"
                + (f": {detail}" if detail else "")
            )
    except httpx.HTTPError as exc:
        raise WorkflowDispatchError(f"No se pudo despachar el workflow: {exc}") from exc
    finally:
        if own_client:
            client.close()
