# BI-06 — rutas nominales solo en localhost

**Estado:** código y pruebas sintéticas locales; sin consulta nominal a Neon,
push ni despliegue. Estas rutas no cambian `/clientes`, `/pedidos` ni Flutter.

## Contrato HTTP

Todas las rutas exigen token Google válido con rol BI `owner`, la puerta local y
la auditoría disponible. `viewer` y `analyst` reciben 403. `GET` responde JSON;
`POST` responde XLSX en memoria. Las respuestas BI usan `Cache-Control: no-store`.

| Ruta | Filtros | Respuesta |
|---|---|---|
| `GET /bi/v1/clientes` | `offset=0..1000000`, `limit=1..200` (100 por defecto) | Catálogo de clientes registrados: `metadatos`, `offset`, `limite`, `filas`. |
| `GET /bi/v1/pedidos` | `desde`, `hasta`, `peso_balon_kg=todos|10|45`, `offset`, `limit` | Pedidos activos por fecha de entrega registrada, más `cobertura_pagina`. |
| `POST /bi/v1/clientes/export` | Sin cuerpo ni filtros | Excel de clientes registrados, máximo 5.000. |
| `POST /bi/v1/pedidos/export` | `desde`, `hasta`, `peso_balon_kg` **en query**, sin cuerpo | Excel de pedidos activos y compradores, máximo 5.000 pedidos. |

Los libros incluyen `Metadatos`, versión, filtros, generación, cobertura y
`snapshot_garantizado=true` con `snapshot_alcance=solicitud`. Conteo y filas
comparten la transacción `REPEATABLE READ READ ONLY` de `get_bi_db`. En el
export de pedidos se comparan conteo, compradores, filas monetarias válidas,
montos y cobertura con `CorteBI` **dentro de esa misma solicitud**; una
discrepancia devuelve 503 y no entrega el libro. Consultas sucesivas no
comparten snapshot. Los montos son centavos enteros; los desconocidos y
anómalos no se convierten a cero. Textos que podrían ser fórmulas se escapan.

## Puerta local y auditoría

- `BI_NOMINAL_LOCAL_ENABLED=1` debe configurarse explícitamente. Se exige
  `APP_ENV=dev`, cliente TCP loopback y host HTTP loopback; se rechazan
  encabezados de reenvío. El proceso backend debe escucharse solo en
  `127.0.0.1` o `::1`. La puerta está apagada por defecto; **no configurar
  estas variables en Fly ni publicar el puerto**.
- `BI_NOMINAL_AUDIT_DB_PATH` debe ser una ruta absoluta a un archivo
  `.sqlite3`, fuera de Git, en un directorio privado del usuario con modo
  `0700`. El archivo se crea con modo `0600`; otros permisos, enlaces o fallo
  de escritura bloquean la solicitud con 503 antes de leer datos nominales.
- Cada solicitud habilitada registra acción, instante, resultado, filtros
  acotados, número de filas y bytes preparados. Para un usuario autorizado se
  guarda una referencia SHA-256 de `sub`, nunca `sub` en claro, token, cookie,
  alias, teléfono, domicilio ni contenido XLSX. La retención **provisional**
  es de 90 días; la limpieza ocurre al iniciar la siguiente solicitud. El
  dueño debe confirmar la política antes de operar BI-06 con datos reales.
  Sin nuevas solicitudes no hay limpieza automática: el operador debe
  ejecutar su rutina local de retención o borrar la base al cerrar el piloto.
- El resultado `prepared` significa que el backend preparó la respuesta XLSX
  y registró sus bytes. **No demuestra que el navegador guardó el archivo**.
  Sin auditoría persistida, no se entrega información nominal.

Errores de filtro/límite devuelven 422 genérico; identidad ausente 401, rol
insuficiente 403, fuente/auditoría/paridad no disponible 503. No incluir rutas
privadas, SQL, credenciales ni datos de clientes en respuestas de error.
