"""Google ID-token identity and per-route BI permissions.

Only the separate BI router uses these dependencies. Mobile routes keep their
existing contract until their own coordinated authentication migration.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth import exceptions as google_exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

RolBI = Literal["viewer", "analyst", "owner"]
PermisoBI = Literal[
    "ver_agregados", "exportar_agregados", "ver_nominales", "exportar_nominales",
]

_BEARER = HTTPBearer(auto_error=False)
_ROLES_VALIDOS = frozenset({"viewer", "analyst", "owner"})
_PERMISOS: dict[PermisoBI, frozenset[RolBI]] = {
    "ver_agregados": frozenset({"viewer", "analyst", "owner"}),
    "exportar_agregados": frozenset({"analyst", "owner"}),
    "ver_nominales": frozenset({"owner"}),
    "exportar_nominales": frozenset({"owner"}),
}
_EMISORES_GOOGLE = frozenset({"accounts.google.com", "https://accounts.google.com"})


@dataclass(frozen=True)
class PrincipalBI:
    google_sub: str
    rol: RolBI


def _error_configuracion() -> HTTPException:
    return HTTPException(status_code=503, detail="Acceso BI no configurado.")


def _configuracion() -> tuple[str, dict[str, RolBI]]:
    """Read allowlist at request time so revocation needs no code change."""
    client_id = os.getenv("BI_GOOGLE_CLIENT_ID", "").strip()
    roles_raw = os.getenv("BI_GOOGLE_SUB_ROLES", "")
    try:
        roles = json.loads(roles_raw)
    except (TypeError, ValueError):
        roles = None
    if (
        not client_id or not isinstance(roles, dict) or not roles
        or any(
            not isinstance(sub, str) or not sub.strip()
            or not isinstance(rol, str) or rol not in _ROLES_VALIDOS
            for sub, rol in roles.items()
        )
    ):
        raise _error_configuracion()
    return client_id, roles


def _error_identidad() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Identidad inválida.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_bi_principal(
    credencial: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
) -> PrincipalBI:
    """Verify signed Google ID token and match stable `sub` to the allowlist."""
    client_id, roles = _configuracion()
    if credencial is None:
        raise HTTPException(
            status_code=401, detail="Identidad requerida.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = google_id_token.verify_oauth2_token(
            credencial.credentials, google_requests.Request(), client_id,
        )
    except google_exceptions.TransportError as exc:
        raise HTTPException(status_code=503, detail="No se pudo verificar la identidad.") from exc
    except (ValueError, google_exceptions.GoogleAuthError) as exc:
        raise _error_identidad() from exc

    # google-auth validates signature, issuer, audience and expiry. Keep these
    # explicit checks as defense in depth and as a visible route invariant.
    sub = claims.get("sub")
    exp = claims.get("exp")
    if (
        claims.get("iss") not in _EMISORES_GOOGLE
        or claims.get("aud") != client_id
        or not isinstance(exp, (int, float)) or isinstance(exp, bool)
        or exp <= time.time()
        or not isinstance(sub, str) or not sub.strip()
    ):
        raise _error_identidad()
    rol = roles.get(sub)
    if rol is None:
        raise HTTPException(status_code=403, detail="Acceso BI no autorizado.")
    return PrincipalBI(google_sub=sub, rol=rol)


def require_bi_permission(permiso: PermisoBI):
    """A BI endpoint must name its permission; browser role headers are ignored."""
    roles_permitidos = _PERMISOS[permiso]

    def comprobar(
        principal: Annotated[PrincipalBI, Depends(require_bi_principal)],
    ) -> PrincipalBI:
        if principal.rol not in roles_permitidos:
            raise HTTPException(status_code=403, detail="Acceso BI no autorizado.")
        return principal

    return comprobar
