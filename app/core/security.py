"""Validacion opcional del header `x-app-token`.

Estrategia para Lambda Function URL con `authorization_type = "NONE"`:
los endpoints funcionales pueden exigir un header compartido
`x-app-token` cuyo valor real se compara contra la env var
`APP_SHARED_TOKEN`.

Reglas:
- Si `APP_SHARED_TOKEN` no esta configurado, la validacion queda
  desactivada (los tests locales y `/health` siguen pasando).
- Si esta configurado, los endpoints que dependan de
  `require_app_token` rechazan con 401 si falta o no coincide.
- `/health` no usa esta dependencia y queda publico para smoke.
- No se loggea el valor del header ni del token.
"""

import os
from typing import Annotated

from fastapi import Header, HTTPException, status

APP_SHARED_TOKEN_ENV = "APP_SHARED_TOKEN"


def _expected_token() -> str | None:
    value = os.getenv(APP_SHARED_TOKEN_ENV)
    if value is None:
        return None
    value = value.strip()
    return value or None


def require_app_token(
    x_app_token: Annotated[str | None, Header(alias="x-app-token")] = None,
) -> None:
    """Dependency FastAPI: exige `x-app-token` si `APP_SHARED_TOKEN` esta seteado.

    Cuando la env var no existe la dependencia es no-op, lo que permite
    pruebas locales y desarrollo sin token. En Lambda con `APP_SHARED_TOKEN`
    configurado, se exige el header en cada request funcional.
    """
    expected = _expected_token()
    if expected is None:
        return
    if x_app_token is None or x_app_token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token requerido.",
        )


def app_token_configured() -> bool:
    """True si `APP_SHARED_TOKEN` esta seteado y la validacion esta activa."""
    return _expected_token() is not None
