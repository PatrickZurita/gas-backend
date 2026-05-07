# GAS Backend - Lambda Packaging

Este backend se prepara para AWS Lambda con FastAPI + Mangum. Esta corrida no sube artefactos a AWS, no ejecuta `aws` y no crea recursos reales.

## Entrypoint Lambda

- App FastAPI local: `app.main:app`
- Handler Lambda: `app.lambda_handler.handler`
- Runtime objetivo: Python 3.12
- Arquitectura objetivo: `arm64`

## Empaquetar localmente

Linux/macOS/Git Bash:

```bash
./scripts/package-lambda.sh
```

PowerShell:

```powershell
.\scripts\package-lambda.ps1
```

Ambos scripts:

- instalan dependencias desde `gas-backend/requirements.txt`;
- copian `gas-backend/app`;
- excluyen `.env`, CSV, logs, caches y tests;
- generan un zip local en `build/lambda-gas-api.zip`;
- no ejecutan comandos AWS.

## Nota sobre psycopg y Lambda arm64

`psycopg[binary]` permite empaquetar de forma simple para MVP. Para producción, el zip debe construirse en un entorno compatible con Linux/arm64, idealmente usando la imagen oficial de Lambda Python 3.12 arm64 o un runner equivalente.

## Variables de entorno esperadas

- `APP_ENV`: `dev` o `prd`.
- `APP_VERSION`: versión lógica del despliegue, por ahora `dev`.
- `DATABASE_URL`: requerido para endpoints que usan PostgreSQL.

La IaC también deja un placeholder `DATABASE_URL_PARAM_NAME` para una fase posterior donde la Lambda resuelva la URL desde SSM Parameter Store. No se debe commitear una connection string real.

## Healthcheck

`GET /health` devuelve 200 OK sin consultar base de datos. Sirve para API Gateway y validaciones de despliegue inicial.

## Logs versionados

Se detectaron `server.out.log` y `server.err.log` en `gas-backend/`. No se borraron. La recomendación es quitarlos del tracking con aprobación del dueño del repo y mantenerlos ignorados para evitar nuevos commits de logs.
