# Reconciliación BI local con rol de solo lectura

**Estado:** comando opt-in, no ejecutado contra Neon al incorporarlo.

`scripts/reconciliar_bi_readonly.py` compara JSON y XLSX agregados producidos
desde un único `CorteBI`. No agrega rutas HTTP, no guarda Excel ni exporta filas
de clientes o pedidos. La salida estándar contiene solo filtros, periodo,
conteos, importes agregados, cobertura y estado de las comprobaciones.

Uso desde el checkout de `gas-backend`:

```sh
python scripts/reconciliar_bi_readonly.py --desde 2026-10-01 --hasta 2026-10-02
```

`--peso` acepta `10` o `45`; sin él se incluyen ambos pesos. El comando solicita
el DSN de `gas_readonly` con entrada oculta. Nunca pasarlo por argumentos,
archivos, variables de entorno ni redirección a logs. Un rango máximo de 366
días y `hasta` no posterior a hoy en Lima se comprueban antes de conectar.

Barreras antes de la consulta de pedidos:

1. Solo se admite PostgreSQL en host `*.neon.tech`, con TLS y usuario
   `gas_readonly`; se rechazan opciones arbitrarias del DSN.
2. La conexión establece `default_transaction_read_only=on`, tiempo límite de
   conexión y consultas, `search_path=public` y transacción `REPEATABLE READ
   READ ONLY`. La comprobación de rol/privilegios ocurre antes de construir el
   corte y exige ausencia de `INSERT`, `UPDATE`, `DELETE` y `TRUNCATE` sobre
   `public.pedidos`, además de ausencia de atributos elevados del rol.
3. El proceso hace rollback y cierra la conexión incluso ante errores. Los
   errores no imprimen el DSN ni resultados parciales. Al iniciarse como CLI,
   cambia a un directorio temporal vacío antes de importar la configuración del
   backend, evitando la lectura del `.env` relativo al checkout.

Las comprobaciones comparan resumen, serie, actividad, cohortes, filtros,
cobertura y metadatos entre JSON y XLSX; también revisan población, unidades,
importes y denominadores. Son comprobaciones internas de consistencia del
corte, **no** contraste independiente con los reportes Flutter ni garantía de
que el rol siga intacto hasta ejecutarlo. Si cualquiera de las barreras falla,
el comando termina sin resultados. No usar un DSN de propietario o del backend
operativo. Mantener la salida privada y fuera de Git.
