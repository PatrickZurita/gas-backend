# Reconciliación BI local con rol de solo lectura

**Estado:** comando opt-in, no ejecutado contra Neon al incorporarlo.

`scripts/reconciliar_bi_readonly.py` compara JSON y XLSX agregados producidos
desde un único `CorteBI` y los contrasta con la ruta de cálculo de los reportes
operativos V4. No agrega rutas HTTP, no guarda Excel ni exporta filas de
clientes o pedidos. La salida estándar contiene solo filtros, periodo,
conteos, importes agregados, cobertura y estado de las comprobaciones.

Uso desde el checkout de `gas-backend`:

```sh
python scripts/reconciliar_bi_readonly.py --desde 2026-10-01 --hasta 2026-10-02
```

`--peso` acepta `10` o `45`; sin él se incluyen ambos pesos. El comando solicita
el DSN de `gas_readonly` con entrada oculta. Nunca pasarlo por argumentos,
archivos, variables de entorno ni redirección a logs. Un rango máximo de 366
días y `hasta` no posterior a hoy en Lima se comprueban antes de conectar.

`--calidad-fuentes` añade agregados BI-08A de canal entre compradores, eventos
de demanda no atendida, jornadas de stock y movimientos por tipo/peso. Cada
tabla opcional se comprueba por separado antes de leerla. Si el rol no tiene
`SELECT` puro, esa fuente aparece como `no_disponible` y la reconciliación
principal de pedidos puede continuar. `Cliente` no tiene fecha de alta, por
lo que altas por canal dentro del rango aparecen como no medibles. Eventos
de demanda no atendida son otra población: nunca se suman a ventas. La
cobertura de captura de llamadas requiere confirmación del dueño.

Barreras antes de la consulta de pedidos:

1. Solo se admite PostgreSQL en host `*.neon.tech`, con TLS y usuario
   `gas_readonly`; se rechazan opciones arbitrarias del DSN.
2. La conexión establece `default_transaction_read_only=on`, tiempo límite de
   conexión y consultas, `search_path=public` y transacción `REPEATABLE READ
   READ ONLY`. La comprobación de rol/privilegios ocurre antes de construir el
   corte y exige ausencia de `INSERT`, `UPDATE`, `DELETE` y `TRUNCATE` sobre
   `public.pedidos`, de `CREATE` en esquema/base y de atributos elevados del
   rol (`BYPASSRLS` incluido). La comparación operativa también lee únicamente
   `public.pedidos`.
3. El proceso hace rollback y cierra la conexión incluso ante errores. Los
   errores no imprimen el DSN ni resultados parciales. Al iniciarse como CLI,
   cambia a un directorio temporal vacío antes de importar la configuración del
   backend, evitando la lectura del `.env` relativo al checkout.

Las comprobaciones comparan resumen, serie, actividad, cohortes, filtros,
cobertura y metadatos entre JSON y XLSX; también revisan población, unidades,
importes y denominadores. En la **misma transacción y snapshot**, el runner
vuelve a leer los pedidos mediante `listar_pedidos_por_rango` del reporte V4,
aplica el mismo rango `fecha_entrega`, `ACTIVO` y peso, y usa su agregador diario
para los importes comparables. No llama al endpoint ni calcula stock; por tanto
no certifica la pantalla Flutter ni el módulo de stock.

La salida `comparacion_operativa` informa conteos, unidades, dinero comparable,
legacy, nulos y anomalías. Informa también la diferencia entre el importe bruto
operativo y el importe válido BI; **no declara igualdad monetaria bruta si hay
exclusiones**. Estados: `ok`; `ok_con_legacy` si solo se usó la conversión desde
soles; `requiere_revision` si hay importes faltantes/anómalos o peso nulo
heredado; `difiere` si queda una diferencia no explicada. Los dos últimos
estados salen con código 2 aunque se emita el diagnóstico agregado. Una fila
sin importe completo tampoco podría representarse en el reporte V4 actual.
Las pruebas locales solo usan datos sintéticos: no constituyen una lectura
actual de Neon ni garantía de que el rol siga intacto hasta ejecutarlo. Si
alguna barrera falla, el comando termina sin resultados. No usar un DSN de
propietario o del backend operativo. Mantener la salida privada y fuera de Git.
Los listados nominales futuros deberán aplicar también snapshot `REPEATABLE
READ READ ONLY` y control de permisos antes de paginar/exportar; este runner
no habilita esas descargas.
