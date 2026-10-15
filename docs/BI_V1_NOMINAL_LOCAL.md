# BI-06 — rutas nominales solo en localhost

**Estado:** código y pruebas sintéticas locales; el 2026-10-14 se consultaron
listas reales y se prepararon ambos Excel con Neon `gas_readonly` en localhost.
Después, el dueño confirmó que Chrome descargó `gas-bi-clientes.xlsx` y
`gas-bi-pedidos.xlsx`. Sin push ni despliegue.
Estas rutas no cambian `/clientes`, `/pedidos` ni Flutter. Evidencia sin datos
personales en la
[validación nominal del workspace](../../docs/analytics/VALIDACION-NEON-NOMINAL-BI-06-2026-10-14.md).

## Contrato HTTP

Todas las rutas exigen token Google válido con rol BI `owner`, la puerta local y
la auditoría disponible. `viewer` y `analyst` reciben 403. `GET` responde JSON;
`POST` responde XLSX en memoria. Las respuestas BI usan `Cache-Control: no-store`.

| Ruta | Filtros | Respuesta |
|---|---|---|
| `GET /bi/v1/clientes` | `offset=0..1000000`, `limit=1..200` (100 por defecto) | Catálogo de clientes registrados: `metadatos`, `offset`, `limite`, `filas`. |
| `GET /bi/v1/pedidos` | `desde`, `hasta`, `peso_balon_kg=todos|10|45`, `offset`, `limit` | Pedidos activos por fecha de entrega registrada, más `cobertura_pagina`. |
| `GET /bi/v1/clientes/pausas` | `desde`, `hasta`, `peso_balon_kg=todos|10|45`, `offset`, `limit` | Compradores del rango, ordenados por última compra registrada más antigua, con historia observable hasta el corte. |
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

`clientes/pausas` es JSON paginado, no exportación. `metadatos.poblacion` vale
`compradores_del_periodo_con_pausa_observada`; `total_registros` cuenta
compradores distintos con al menos un pedido activo entre `desde` y `hasta`.
La historia de esos compradores abarca todos los pedidos activos observados
hasta `hasta` con el mismo filtro de peso. Cada fila incluye `cliente_id`,
`alias`, `telefono`, `primera_compra_observada`, `ultima_compra_registrada`,
`dias_sin_compra_registrada`, `dias_compra_observados` (fechas ISO distintas) y
`cadencia_individual`. Esta última es `null` hasta tener tres días distintos;
luego informa dos o más intervalos observados, su mediana, mínimo y máximo.
El orden es `ultima_compra_registrada` ascendente y `cliente_id` ascendente;
`offset`/`limite` controlan la página. Metadatos informan fecha de corte,
`dia_abierto` si incluye hoy, calidad de fecha operativa y avisos. El cálculo
no etiqueta abandono, no predice próxima compra y no distingue pedidos
cargados tarde sin evidencia por fila. Por contener datos personales, conserva
la puerta local, `owner`, auditoría y `Cache-Control: no-store` de BI-06.

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
  dueño confirmó 90 días para la validación local real de BI-06.
  Sin nuevas solicitudes no hay limpieza automática: el operador debe
  ejecutar su rutina local de retención o borrar la base al cerrar el piloto.
- El resultado `prepared` significa que el backend preparó la respuesta XLSX
  y registró sus bytes; por sí solo no demuestra que el navegador guardó el
  archivo. Para esta corrida concreta, el dueño confirmó ambas descargas. Sin
  auditoría persistida, no se entrega información nominal.

Errores de filtro/límite devuelven 422 genérico; identidad ausente 401, rol
insuficiente 403, fuente/auditoría/paridad no disponible 503. No incluir rutas
privadas, SQL, credenciales ni datos de clientes en respuestas de error.
