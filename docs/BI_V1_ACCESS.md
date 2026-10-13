# Verificador BI v1 — preparado, sin ruta

`app/core/bi_auth.py` prepara identidad individual para una sola distribuidora usando tokens de ID de Google. `app/api/bi.py` reserva un router con dependencia de identidad para todas sus futuras rutas. **No hay endpoints BI montados** ni sesión web implementada. Este código no protege los routers móviles existentes. El contrato de diseño vive en `../../docs/analytics/ACCESO-PRIVADO-BI-V1.md` dentro del workspace.

## Configuración requerida antes de usarlo

- `BI_GOOGLE_CLIENT_ID`: ID OAuth del cliente web que emitirá los tokens de ID. El backend valida la audiencia contra este valor.
- `BI_GOOGLE_SUB_ROLES`: objeto JSON con identificadores estables `sub` de Google como claves y `viewer`, `analyst` u `owner` como valores. No se usan emails como identificador ni se guarda la lista real en Git.

Si falta o es inválida cualquiera de las dos configuraciones, la dependencia responde 503. Si falta el bearer o el token no pasa firma/emisor/audiencia/vigencia responde 401; un `sub` no permitido o un rol sin el permiso pedido recibe 403. La librería `google-auth` realiza la validación criptográfica usando certificados públicos de Google. Se configurará un método de alta/revocación de los `sub` antes de exponer rutas; una revocación en la lista permitida debe llegar al proceso backend para surtir efecto.

Uso previsto al crear rutas BI: añadir cada operación al router reservado de `app/api/bi.py` y declarar `Depends(require_bi_permission("ver_agregados"))` para JSON agregado o `Depends(require_bi_permission("exportar_agregados"))` para XLSX agregado. Revisar que ninguna ruta nueva omita el permiso específico. No hay permiso nominal hasta diseñar BI-06. El BFF de `gas-web` deberá mantener el token fuera del navegador y entregarlo al backend por HTTPS; resolver expiración/reinicio de sesión, caché de certificados y auditoría antes de conectar datos.

No se debe confundir esta preparación con BI-02 completo: falta BFF/sesión, verificación solicitada, revisión de seguridad y aplicación a cada ruta futura. No se consultó producción.

Referencia del verificador: [Google — validación del token de ID en servidor](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token), [google-auth `verify_oauth2_token`](https://google-auth.readthedocs.io/en/latest/reference/google.oauth2.id_token.html).
