# BI v1: proyección JSON y Excel agregado local

**Estado:** implementación interna local (2026-10-13). No se añadieron rutas HTTP,
descargas web, consultas nuevas ni archivos con ventas reales al repositorio.

`app.services.bi.construir_corte(...)` genera un `CorteBI` con población, filtros,
resumen, serie diaria, actividad, cobertura y avisos. A partir de **ese mismo
objeto**, `proyectar_corte_agregado(corte)` copia únicamente los campos agregados
del contrato; `serializar_corte_json(corte)` produce UTF-8 y
`exportar_xlsx_agregado(corte)` produce bytes XLSX en memoria. Las funciones de
presentación no acceden a la base de datos ni calculan nuevamente las métricas.

El libro tiene `Resumen`, `Serie diaria`, `Actividad clientes` y `Metadatos`.
Los importes se guardan como enteros en centavos. `Metadatos` registra versión,
fecha de generación, zona horaria, fuente, fecha base, población, filtros,
cobertura y avisos. En la hoja de actividad, un porcentaje de cohorte sin
clientes elegibles queda vacío y los elegibles/censurados se muestran al lado.

Para comparar JSON y XLSX hay que usar **el mismo `CorteBI`**. Dos llamadas
independientes a `construir_corte` pueden diferir por ediciones/cobros; el saldo
pendiente corresponde al momento de consulta. No se promete snapshot atómico.
Los campos nominales (alias, teléfono, dirección, coordenadas) no están en la
proyección ni en el libro. Las cifras agregadas siguen siendo información
comercial privada. La publicación por red y la descarga real esperan BI-02.

La dependencia XLSX es `openpyxl==3.1.5` en `requirements.txt`. No se ha
contrastado esta salida con datos de producción ni con los reportes Flutter.
