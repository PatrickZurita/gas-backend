# Acceso backend BI v1 — Google y lectura separada

**Estado:** código local, sin credenciales reales, consulta Neon, push ni despliegue.
No modifica el inicio de sesión de Android ni sus rutas existentes.

`GET /bi/v1/corte?desde=YYYY-MM-DD&hasta=YYYY-MM-DD&peso_balon_kg=todos|10|45`
entrega el corte agregado `bi-v1.1` completo. `desde` y `hasta` son obligatorios;
el rango máximo es 366 días y termina como máximo hoy en Lima. El router
requiere `Authorization: Bearer <Google ID token>` y permiso `ver_agregados`.
No hay rutas nominales ni Excel HTTP. Todas las respuestas BI llevan
`Cache-Control: no-store`.

## Configuración privada requerida

- `BI_GOOGLE_CLIENT_ID`: audiencia OAuth del token de ID que presenta el BFF.
- `BI_GOOGLE_SUB_ROLES`: JSON `sub` → `viewer|analyst|owner`; el identificador
  estable es `sub`, no correo ni dominio. La lista real no va en Git.
- `BI_DATABASE_URL`: DSN PostgreSQL con TLS del usuario **gas_readonly** en Neon.
  Es independiente de `DATABASE_URL` usado por las rutas móviles. La ruta
  devuelve 503 si falta o si el rol efectivo tiene permisos de escritura,
  DDL, superusuario, creación de roles o bypass RLS.

El servidor verifica firma, emisor, audiencia, expiración y `sub` por medio de
`google-auth` y controles explícitos. Una identidad válida sin rol permitido
recibe 403; token ausente o inválido 401; configuración o fuente BI ausente 503.
La dependencia no admite `APP_SHARED_TOKEN`, headers de rol ni una ruta de
desarrollo sin identidad. `viewer`, `analyst` y `owner` pueden ver el agregado;
exportar Excel exigirá un permiso distinto cuando se implemente.

La consulta usa una transacción PostgreSQL `REPEATABLE READ READ ONLY`, comprueba
rol y privilegios, y hace `ROLLBACK` al cerrar la solicitud. La política del rol
en Neon debe también revocar escritura/DDL de forma efectiva. La verificación
HTTP con un token real y la conexión operativa quedan pendientes de la
configuración privada y de una revisión de despliegue. Reiniciar el proceso
backend al rotar `BI_DATABASE_URL`, pues el pool está cacheado.
