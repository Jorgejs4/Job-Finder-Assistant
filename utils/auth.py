"""Small adapter around Streamlit's native Google OIDC authentication."""

from __future__ import annotations

import os
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any


class AuthConfigurationError(RuntimeError):
    """Raised when a login operation is attempted without OIDC settings."""


@dataclass(frozen=True)
class AuthUser:
    user_id: str
    email: str = ""
    name: str = ""
    picture: str = ""
    claims: dict[str, Any] | None = None


_AUTH_KEYS = ("redirect_uri", "cookie_secret", "client_id", "client_secret", "server_metadata_url")


def _streamlit():
    try:
        import streamlit as st
        return st
    except ImportError as exc:
        raise AuthConfigurationError("Streamlit no está instalado; no se puede iniciar OIDC.") from exc


def _auth_settings() -> dict[str, str]:
    settings: dict[str, str] = {}
    try:
        import streamlit as st

        configured = st.secrets.get("auth", {})
        if isinstance(configured, Mapping):
            settings.update({str(k): str(v) for k, v in configured.items() if v not in (None, "")})
    except Exception:
        pass
    for key in _AUTH_KEYS:
        env_value = os.getenv(f"STREAMLIT_AUTH_{key.upper()}")
        if env_value:
            settings[key] = env_value
    return settings


def is_auth_configured() -> bool:
    return all(_auth_settings().get(key) for key in _AUTH_KEYS)


def auth_configuration_message() -> str:
    missing = [key for key in _AUTH_KEYS if not _auth_settings().get(key)]
    if not missing:
        return "Google OIDC configurado."
    return (
        "Google OIDC no está configurado. Faltan: " + ", ".join(missing) + ". "
        "Añade la sección [auth] a secrets de Streamlit; consulta docs/supabase_multitenant.md."
    )


def _claims(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        return dict(vars(value))
    except (TypeError, ValueError):
        return {}


def current_user() -> AuthUser | None:
    """Return the current Streamlit OIDC principal, or None when logged out."""
    st = _streamlit()
    raw = getattr(st, "user", None)
    claims = _claims(raw)
    if not claims:
        return None
    logged_in = claims.get("is_logged_in", claims.get("is_authenticated", True))
    if logged_in is False:
        return None
    subject = str(claims.get("sub") or claims.get("user_id") or claims.get("id") or "").strip()
    if not subject:
        return None
    return AuthUser(
        user_id=subject,
        email=str(claims.get("email") or ""),
        name=str(claims.get("name") or claims.get("preferred_username") or ""),
        picture=str(claims.get("picture") or claims.get("avatar_url") or ""),
        claims=claims,
    )


def login() -> None:
    if not is_auth_configured():
        raise AuthConfigurationError(auth_configuration_message())
    _streamlit().login("google")


def logout() -> None:
    _streamlit().logout()


def render_login() -> bool:
    """Render a login/fallback message and return whether a user is present."""
    user = current_user()
    if user:
        return True
    st = _streamlit()
    if not is_auth_configured():
        st.info(auth_configuration_message())
        return False
    if st.button("Iniciar sesión con Google", key="google_oidc_login"):
        login()
    return False


get_current_user = current_user


def is_authenticated() -> bool:
    return current_user() is not None


def resolve_supabase_user_id(user: AuthUser, client: Any) -> str:
    """Map a Google OIDC subject to a Supabase auth.users UUID server-side."""
    if not user or not user.user_id or not user.email:
        raise AuthConfigurationError("Google no devolvió un subject y email válidos.")
    rows = getattr(
        client.table("user_profiles").select("id").eq("google_subject", user.user_id).limit(1).execute(),
        "data",
        None,
    )
    if rows:
        return str(rows[0]["id"])

    try:
        created = client.auth.admin.create_user(
            {
                "email": user.email,
                "email_confirm": True,
                "user_metadata": {
                    "google_subject": user.user_id,
                    "full_name": user.name,
                },
            }
        )
        auth_user = getattr(created, "user", None) or (created.get("user") if isinstance(created, dict) else None)
        supabase_id = getattr(auth_user, "id", None) or (auth_user.get("id") if isinstance(auth_user, dict) else None)
    except Exception as exc:
        raise AuthConfigurationError(f"No se pudo crear la identidad Supabase: {exc}") from exc
    if not supabase_id:
        raise AuthConfigurationError("Supabase no devolvió el UUID del usuario.")
    return str(supabase_id)
