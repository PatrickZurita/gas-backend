# BI v1: proyección JSON y Excel agregado local

**Estado:** implementación local con rutas JSON y XLSX agregado protegidas
(2026-10-14). No hay archivos con ventas reales en Git ni despliegue.

`app.services.bi.construir_corte(...)` genera un `CorteBI` con población, filtros,
resumen, serie diaria, actividad, cobertura y avisos. A partir de **ese mismo
objeto**, `proyectar_corte_agregado(corte)` copia únicamente los campos agregados
del contrato; `serializar_corte_json(corte)` produce UTF-8 y
`exportar_xlsx_agregado(corte)` produce bytes XLSX en memoria. Las funciones de
presentación no acceden a la base de datos ni calculan nuevamente las métricas.

El libro tiene `Resumen`, `Serie diaria`, `Calendario diario`, `Actividad clientes` y `Metadatos`. Desde `bi-v1.1`, el calendario contiene todos los días del filtro con métricas agregadas entre pesos; los ceros significan que no hay pedidos activos **registrados** en ese día. La hoja de actividad conserva la mediana agrupada legacy y añade cadencia basada en una mediana por cliente elegible, con muestra y percentiles 25/75.
Los importes se guardan como enteros en centavos. `Metadatos` registra versión,
fecha de generación, zona horaria, fuente, fecha base, población, filtros,
cobertura y avisos. En la hoja de actividad, un porcentaje de cohorte sin
clientes elegibles queda vacío y los elegibles/censurados se muestran al lado.

Para comparar JSON y XLSX hay que usar **el mismo `CorteBI`**. Dos llamadas
independientes a `construir_corte` pueden diferir por ediciones/cobros; el saldo
pendiente corresponde al momento de consulta. Las rutas JSON y XLSX usan por
petición una transacción de lectura con snapshot `REPEATABLE READ`, pero no
prometen identidad entre dos solicitudes posteriores.
Los campos nominales (alias, teléfono, dirección, coordenadas) no están en la
proyección ni en el libro. Las cifras agregadas siguen siendo información
comercial privada. El BFF web y la configuración privada deben estar listos
antes de cualquier publicación; la descarga agregada exige `analyst` u `owner`
mediante un permiso específico y devuelve el archivo directamente al solicitante.

La dependencia XLSX es `openpyxl==3.1.5` en `requirements.txt`. El exportador
interno se reconcilió en un corte real de solo lectura; el endpoint HTTP XLSX
se ha probado con datos sintéticos, sin descarga productiva ni despliegue.
