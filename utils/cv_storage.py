"""Private CV storage backed by Supabase Storage, never by GitHub."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import BinaryIO, Any
from uuid import uuid4


class CVStorageError(RuntimeError):
    """Raised for invalid CV paths or storage failures."""


_ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt"}


class CVStorage:
    def __init__(self, client: Any, *, bucket: str = "cv-files"):
        self.client = client
        self.bucket = bucket

    @staticmethod
    def _user_segment(user_id: str) -> str:
        value = str(user_id or "").strip()
        if not value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise CVStorageError("user_id no válido para una ruta privada de CV.")
        return value

    @classmethod
    def _safe_path(cls, user_id: str, path: str) -> str:
        owner = cls._user_segment(user_id)
        candidate = str(path or "").replace("\\", "/")
        parsed = PurePosixPath(candidate)
        if parsed.is_absolute() or ".." in parsed.parts or not candidate.startswith(owner + "/"):
            raise CVStorageError("La ruta del CV no pertenece al usuario actual.")
        return candidate

    @staticmethod
    def _bytes(file: bytes | bytearray | BinaryIO) -> bytes:
        if isinstance(file, (bytes, bytearray)):
            return bytes(file)
        try:
            value = file.read()
        except Exception as exc:
            raise CVStorageError("El archivo de CV no se puede leer.") from exc
        if not isinstance(value, (bytes, bytearray)):
            raise CVStorageError("El archivo de CV debe producir bytes.")
        return bytes(value)

    def upload_cv(
        self,
        user_id: str,
        file: bytes | bytearray | BinaryIO,
        filename: str,
        *,
        content_type: str | None = None,
    ) -> str:
        owner = self._user_segment(user_id)
        suffix = PurePosixPath(filename or "").suffix.lower()
        if suffix not in _ALLOWED_EXTENSIONS:
            raise CVStorageError("Formato de CV no permitido. Usa PDF, DOC, DOCX o TXT.")
        path = f"{owner}/{uuid4().hex}{suffix}"
        options = {"content-type": content_type or "application/octet-stream", "upsert": False}
        try:
            self.client.storage.from_(self.bucket).upload(path, self._bytes(file), options)
        except Exception as exc:
            raise CVStorageError(f"No se pudo subir el CV a Supabase Storage: {exc}") from exc
        return path

    def signed_url(self, user_id: str, path: str, *, expires_in: int = 3600) -> str:
        safe_path = self._safe_path(user_id, path)
        if not 1 <= int(expires_in) <= 86400:
            raise CVStorageError("expires_in debe estar entre 1 y 86400 segundos.")
        try:
            response = self.client.storage.from_(self.bucket).create_signed_url(safe_path, int(expires_in))
        except Exception as exc:
            raise CVStorageError(f"No se pudo generar la URL firmada del CV: {exc}") from exc
        if isinstance(response, dict):
            url = response.get("signedURL") or response.get("signedUrl") or response.get("signed_url")
        else:
            url = getattr(response, "signedURL", None) or getattr(response, "signed_url", None)
        if not url:
            raise CVStorageError("Supabase no devolvió una URL firmada válida.")
        return str(url)

    def download_cv(self, user_id: str, path: str) -> bytes:
        """Download a tenant-owned CV for a server-side worker."""
        safe_path = self._safe_path(user_id, path)
        try:
            value = self.client.storage.from_(self.bucket).download(safe_path)
        except Exception as exc:
            raise CVStorageError(f"No se pudo descargar el CV desde Supabase Storage: {exc}") from exc
        if not isinstance(value, (bytes, bytearray)):
            raise CVStorageError("Supabase no devolvió bytes para el CV.")
        return bytes(value)

    def upload_and_sign(self, user_id: str, file: bytes | bytearray | BinaryIO, filename: str, *, expires_in: int = 3600, content_type: str | None = None) -> tuple[str, str]:
        path = self.upload_cv(user_id, file, filename, content_type=content_type)
        return path, self.signed_url(user_id, path, expires_in=expires_in)
