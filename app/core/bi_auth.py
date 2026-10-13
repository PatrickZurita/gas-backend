"""Autorización exclusiva de futuras rutas BI.

El módulo no registra endpoints. Una ruta BI debe declarar explícitamente
``Depends(require_bi_permission(...))``; sin configuración, identidad o rol
válidos se rechaza la solicitud. Las rutas móviles existentes no usan esto.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth import exceptions as google_exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

RolBI = Literal["viewer", "analyst", "owner"]
PermisoBI = Literal["ver_agregados", "exportar_agregados"]

_BEARER = HTTPBearer(auto_error=False)
_ROLES_VALIDOS = frozenset({"viewer", "analyst", "owner"})
_PERMISOS: dict[PermisoBI, frozenset[RolBI]] = {
    "ver_agregados": frozenset({"viewer", "analyst", "owner"}),
    "exportar_agregados": frozenset({"analyst", "owner"}),
}


@dataclass(frozen=True)
class PrincipalBI:
    google_sub: str
    rol: RolBI


def _configuracion() -> tuple[str, dict[str, RolBI]]:
    """Lee la lista permitida sin registrar ni devolver sus valores en errores."""
    client_id = os.getenv("BI_GOOGLE_CLIENT_ID", "").strip()
    roles_raw = os.getenv("BI_GOOGLE_SUB_ROLES", "")
    try:
        roles = json.loads(roles_raw)
    except (TypeError, ValueError):
        roles = None

    if (
        not client_id
        or not isinstance(roles, dict)
        or not roles
        or any(
            not isinstance(sub, str)
            or not sub.strip()
            or not isinstance(rol, str)
            or rol not in _ROLES_VALIDOS
            for sub, rol in roles.items()
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Acceso BI no configurado.",
        )
    return client_id, roles


def require_bi_principal(
    credencial: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
) -> PrincipalBI:
    """Verifica un ID token Google para este cliente OAuth y su `sub` permitido."""
    client_id, roles = _configuracion()
    if credencial is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identidad requerida.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = google_id_token.verify_oauth2_token(
            credencial.credentials,
            google_requests.Request(),
            client_id,
        )
    except google_exceptions.TransportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo verificar la identidad.",
        ) from exc
    except (ValueError, google_exceptions.GoogleAuthError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identidad inválida.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identidad inválida.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    rol = roles.get(sub)
    if rol is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso BI no autorizado.",
        )
    return PrincipalBI(google_sub=sub, rol=rol)


def require_bi_permission(permiso: PermisoBI):
    """Dependencia para cada ruta BI futura; nunca admite un rol desde headers."""
    roles_permitidos = _PERMISOS[permiso]

    def comprobar(
        principal: Annotated[PrincipalBI, Depends(require_bi_principal)],
    ) -> PrincipalBI:
        if principal.rol not in roles_permitidos:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acceso BI no autorizado.",
            )
        return principal

    return comprobar
