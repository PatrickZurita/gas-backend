# Núcleo BI v1 (PostgreSQL)

Estado: cálculo interno implementado; **sin ruta HTTP ni exportador**. Contrato de negocio: `../../docs/analytics/CONTRATO-BI-V1.md` en el workspace GAS.

`app.services.bi.construir_corte(db, desde, hasta, peso_balon_kg=None)` devuelve un `CorteBI` tipado con `resumen`, `serie_diaria`, `actividad_clientes`, `cobertura` y `avisos`. Acepta fechas inclusivas, peso `10`, `45` o todos, y hasta 366 días. Reutilizar este único corte para futuras representaciones JSON/Excel, preservando filtros y versión. Solo consulta pedidos activos en PostgreSQL; en DynamoDB falla de forma explícita. No abre conexión por sí mismo.

`hasta` no puede superar el día actual en Lima. Si incluye hoy, ese día puede estar incompleto: la elegibilidad de cohortes se calcula hasta ayer y se expone en `actividad_clientes.corte_cohortes_hasta`.

El repositorio lee identificadores de cliente para deduplicar y construir historia, pero la salida agregada no los expone. El historial de compradores llega hasta `hasta`; los intervalos contados terminan dentro de `desde`–`hasta` y pueden empezar antes. La mediana describe esos intervalos observados, no predice recompra. Los meses muestran clientes con compra registrada y las cohortes 30/60/90 días incluyen solo ventanas completas. Varios pedidos del mismo cliente y día cuentan como un evento para recompra.

Montos total y pendiente usan centavos o fallback decimal legacy. Filas sin ambos importes válidos o con `pendiente > total` siguen contando como pedidos, compradores y balones, pero quedan excluidas de las sumas monetarias; `cobertura` cuenta faltantes, fallback y anomalías. El saldo es actual al consultar. El peso histórico de 10 kg puede ser un default de migración; el modelo no conserva su procedencia individual. `fecha_entrega` es día operativo registrado, no hora de demanda. Consultas sucesivas sin snapshot pueden variar si cambian pedidos.

**Control de acceso pendiente de integración:** `app.core.security.require_app_token` permite acceso cuando `APP_SHARED_TOKEN` no está configurado y no se usa para BI. El verificador Google y el router reservado se describen en [BI_V1_ACCESS.md](BI_V1_ACCESS.md); aún faltan sesión web, aplicación de permisos a cada endpoint y revisión antes de montar rutas. Las respuestas nominales requieren además roles, paginación y auditoría. Este módulo no consulta producción ni contiene datos de clientes.
