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
| `GET /bi/v1/clientes/historicos` | `fecha_corte`, `peso_balon_kg=todos|10|45`, `segmento=todos|compra_unica_antigua|recurrente_pausa_larga|recurrente_pausa_relativa|sin_senal_prioritaria`, `offset`, `limit` | Todos los compradores activos observados desde 21-may-2026 hasta el corte, incluidos quienes no compraron en un rango reciente. Solo revisión humana `owner`. |
| `GET /bi/v1/geo/direcciones-pendientes` | `desde`, `hasta`, `peso_balon_kg=todos|10|45`, `estado=todos|NO_GEOCODIFICADO|SIN_RESULTADO|RECHAZADO_PRECISION|RECHAZADO_BOUNDS|PENDIENTE_DUENO|SIN_H3`, `offset`, `limit` | Direcciones con pedidos activos sin H3, agrupadas y priorizadas por pedidos afectados. Revisión humana `owner`; no escribe ni geocodifica. |
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

`clientes/historicos` también es JSON paginado y usa un único snapshot de
lectura por solicitud. `metadatos.denominadores.compradores_observados` cuenta
todos los compradores con pedido activo entre 21-may-2026 y `fecha_corte`, con
el peso indicado; `por_segmento` es una partición exhaustiva de ese total y
`por_banda_dias` agrupa la pausa en `0_29`, `30_59`, `60_89`, `90_119`,
`120_mas`. `total_registros` cuenta el segmento solicitado antes de paginar.
`con_telefono` y `sin_telefono` describen cobertura nominal de ese universo,
no permiso de contacto. Las filas se ordenan por días sin compra descendentes
y `cliente_id` ascendente. Devuelven alias y teléfono bajo el mismo permiso
`owner`, fecha primera y última observada, días de compra distintos, banda,
segmento y cadencia individual solo con >=3 días y >=2 intervalos.

La regla de revisión es: compra única antigua = un día y pausa >=120 días;
recurrente con pausa larga = >=2 días y pausa >=120; recurrente con pausa
relativa = >=3 días y pausa >=máximo(30, dos veces su mediana individual),
siempre que no sea ya pausa larga. El resto es `sin_senal_prioritaria`.
Estas categorías son excluyentes. El historial anterior al 21-may no es
observable; tampoco hay marca fiable de carga tardía por fila. El día actual
se rotula abierto. Ninguna categoría demuestra abandono ni dispara contacto.

`geo/direcciones-pendientes` usa los mismos pedidos activos y la misma fuente
GEO efectiva que `corte-territorio`: cache local Google temporal si está
disponible; si no, la tabla de resultados temporales con permiso SELECT. Ambas
consultas son solicitudes independientes, por lo que su snapshot puede diferir
si cambian pedidos o vence el cache entre ellas. Dentro de cada solicitud, la
lista, los denominadores y la página se calculan en un solo snapshot
`REPEATABLE READ READ ONLY`. Si falta la fuente GEO, falla cerrado con 503.
No llama a Google ni guarda puntos o resultados nuevos.

`metadatos.denominadores` incluye pedidos activos, con H3, sin H3, direcciones
pendientes y compradores afectados, más particiones por estado de direcciones
y pedidos. `total_registros` cuenta direcciones después del filtro `estado`,
antes de paginar. Cada fila agrupa un `direccion_id` y expone, solo al dueño,
`cliente_id`, `alias_cliente`, `texto_original`, `distrito`, `referencia`,
`estado_geo`, `motivo_tecnico`, compradores distintos, pedidos y balones
afectados y la primera/última
entrega registrada del rango. Se ordena por pedidos, balones e ID de dirección.
Si varios compradores usaron el mismo `direccion_id`, `cliente_id` y
`alias_cliente` son `null` para no atribuirla a uno de ellos.
`SIN_H3` cubre geocoding OK sin H3, por ejemplo precisión LOW. Un resultado
ausente, vencido o con texto modificado se presenta como `NO_GEOCODIFICADO`
con `motivo_tecnico` distinto. Un alias o apodo **no se diagnostica** por
heurística; requiere revisión humana posterior. Los pedidos con H3 en celdas
suprimidas por privacidad no entran en esta cola. La corrección de direcciones
en producción queda fuera de este endpoint y se pospone para el tramo final.

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
