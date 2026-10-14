# Acceso backend BI v1 — Google y lectura separada

**Estado:** código y prueba Google real en localhost, sin push ni despliegue.
El rol `gas_readonly` se sustituyó y el runner BI consultó Neon desde un
proceso local de solo lectura el 2026-10-14. El dueño observó resumen y serie
agregados tras login Google y autorización por `sub`/rol local.
No modifica el inicio de sesión de Android ni sus rutas existentes.

`GET /bi/v1/corte?desde=YYYY-MM-DD&hasta=YYYY-MM-DD&peso_balon_kg=todos|10|45`
entrega el corte agregado `bi-v1.1` completo. `desde` y `hasta` son obligatorios;
el rango máximo es 366 días y termina como máximo hoy en Lima. El router
requiere `Authorization: Bearer <Google ID token>` y permiso `ver_agregados`.
`GET /bi/v1/corte.xlsx` acepta exactamente los mismos filtros y exige el permiso
`exportar_agregados` (`analyst` u `owner`; `viewer` recibe 403). Devuelve el
Excel agregado de cinco hojas desde el mismo cálculo `CorteBI`, en memoria y
sin crear archivos. Responde con tipo MIME XLSX, `Content-Disposition:
attachment` y un nombre basado solo en fechas y peso validados. El encabezado
`X-BI-Generado-En` coincide con `generado_en` de la hoja `Metadatos`. No hay
rutas nominales publicadas: [BI-06 local](BI_V1_NOMINAL_LOCAL.md) añade rutas
deshabilitadas por defecto, solo para `owner` en localhost, con auditoría
SQLite privada obligatoria. Todas las respuestas BI llevan `Cache-Control: no-store`,
incluidos los errores. Una consulta JSON y otra XLSX posteriores pueden tener
distinto `generado_en` o datos si cambió la base entre solicitudes; no comparten
snapshot entre peticiones.

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
solo `analyst` y `owner` pueden descargar el Excel agregado.

La consulta usa una transacción PostgreSQL `REPEATABLE READ READ ONLY`, comprueba
rol y privilegios, y hace `ROLLBACK` al cerrar la solicitud. La política del rol
en Neon debe también revocar escritura/DDL de forma efectiva. La verificación
HTTP con un principal sintético y la conexión limitada real devolvió 200 para
un corte agregado de 30 días, con `Cache-Control: no-store`. Después, la
prueba Google → BFF → backend en localhost mostró 403 antes del alta local y
resumen/serie reales después, según confirmación del dueño. Falta revisión de
TLS, revocación/expiración y despliegue. Reiniciar el proceso backend al rotar
`BI_DATABASE_URL`, pues el pool está cacheado.
