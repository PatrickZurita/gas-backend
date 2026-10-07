# CLAUDE.md — Guía para Claude en `gas-backend`

> Complementa [AGENTS.md](AGENTS.md) (gobernanza local) y [../AGENTS.md](../AGENTS.md) (raíz). Si hay conflicto, gana `AGENTS.md`.

Lee ambos `AGENTS.md` explícitamente y sigue su protocolo Git + `brain_search`. El cierre
multi-repo vive en `../_brain/`, no en un `_brain/` del backend.

## Contexto en una línea
Backend FastAPI + PostgreSQL + SQLAlchemy + Alembic del MVP GAS (registro de pedidos de gas). PostgreSQL es la base activa; AWS/DynamoDB en standby.

## Misión actual
El plan V2 de [../docs/roadmap/IMPLEMENTATION_ORDER.md](../docs/roadmap/IMPLEMENTATION_ORDER.md)
es histórico. Antes de escoger trabajo, revisar commits, el último cierre y el brain; el backend
PostgreSQL está desplegado en Fly según el corte 2026-09-24, con AWS en standby.

## Lo más importante que Claude debe respetar
- Backend es **source of truth** de stock/resumen; el frontend no recalcula stock crítico.
- Pedido anulado **no cuenta** en ventas/deuda/salidas. No repetir el bug "vendidos 17 vs 16".
- Dinero en **centavos enteros**, nunca `double`.
- Pedidos legacy sin peso = `10 kg`; 10 kg y 45 kg no se mezclan.
- No ejecutar `alembic upgrade head` ni migraciones contra datos reales.
- No tocar `app/**` sin autorización; proponer diff revisable.

## Skills relevantes
- [gas-backend-stock-consistency](../docs/codex-skills/gas-backend-stock-consistency/SKILL.md) — reglas V2.0/V2.1.
- [gas-qa-regression-stock-reports](../docs/codex-skills/gas-qa-regression-stock-reports/SKILL.md) — matriz de regresión.
- [gas-fastapi-reports](../docs/codex-skills/gas-fastapi-reports/SKILL.md), [gas-postgres-minimal](../docs/codex-skills/gas-postgres-minimal/SKILL.md), [gas-api-contracts](../docs/codex-skills/gas-api-contracts/SKILL.md).

## Cómo responder
Formato corto: `Done / Files / Checks / Risks / Next`. Decisiones de arquitectura o datos: respuesta extendida con tradeoffs.

## Checks
```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```
Más comandos: [DEV_COMMANDS.md](DEV_COMMANDS.md).
