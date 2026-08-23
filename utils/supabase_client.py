"""Supabase client factories with explicit browser/server separation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


class SupabaseConfigurationError(RuntimeError):
    """Raised when a required Supabase setting is missing or invalid."""


@dataclass(frozen=True)
class SupabaseConfig:
    url: str
    anon_key: str
    service_role_key: str | None = None


def _secret(name: str, default: Any = None) -> Any:
    value = os.getenv(name)
    if value not in (None, ""):
        return value
    try:
        import streamlit as st

        return st.secrets.get(name, default)
    except Exception:
        return default


def get_supabase_config(*, require_service_role: bool = False) -> SupabaseConfig:
    url = str(_secret("SUPABASE_URL", "") or "").strip().rstrip("/")
    anon_key = str(
        _secret("SUPABASE_ANON_KEY", _secret("SUPABASE_PUBLISHABLE_KEY", "")) or ""
    ).strip()
    service_role_key = str(
        _secret("SUPABASE_SERVICE_ROLE_KEY", _secret("SUPABASE_SECRET_KEY", "")) or ""
    ).strip() or None

    missing = []
    if not url:
        missing.append("SUPABASE_URL")
    if not anon_key and not service_role_key:
        missing.append("SUPABASE_ANON_KEY")
    if require_service_role and not service_role_key:
        missing.append("SUPABASE_SERVICE_ROLE_KEY")
    if missing:
        raise SupabaseConfigurationError(
            "Supabase no está configurado. Falta(n): " + ", ".join(dict.fromkeys(missing)) + ". "
            "Configúralas en el entorno o en secrets de Streamlit."
        )
    if not url.startswith(("https://", "http://")):
        raise SupabaseConfigurationError("SUPABASE_URL debe ser una URL HTTP(S) válida.")
    return SupabaseConfig(url=url, anon_key=anon_key, service_role_key=service_role_key)


def is_supabase_configured(*, require_service_role: bool = False) -> bool:
    try:
        get_supabase_config(require_service_role=require_service_role)
        return True
    except SupabaseConfigurationError:
        return False


def _create_client(url: str, key: str):
    try:
        from supabase import create_client
    except ImportError as exc:
        raise SupabaseConfigurationError(
            "Falta la dependencia supabase. Instala requirements.txt."
        ) from exc
    try:
        return create_client(url, key)
    except Exception as exc:
        raise SupabaseConfigurationError(f"No se pudo crear el cliente Supabase: {exc}") from exc


def create_browser_client():
    """Create the anon-key client intended for a user session/browser flow."""
    config = get_supabase_config()
    if not config.anon_key:
        raise SupabaseConfigurationError(
            "El cliente browser requiere SUPABASE_ANON_KEY (o SUPABASE_PUBLISHABLE_KEY); "
            "no se usará la service-role key en el browser."
        )
    return _create_client(config.url, config.anon_key)


def create_server_client():
    """Create the server client; it requires the service-role key explicitly."""
    config = get_supabase_config(require_service_role=True)
    return _create_client(config.url, config.service_role_key or "")


# Friendly aliases for callers that prefer get_* naming.
get_browser_client = create_browser_client
get_server_client = create_server_client
get_supabase_browser_client = create_browser_client
get_supabase_server_client = create_server_client
