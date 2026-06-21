# AGENTS.md — `gas-backend` (FastAPI + PostgreSQL)

> Gobernanza local del backend. Hereda la gobernanza raíz del workspace: [../AGENTS.md](../AGENTS.md). Si hay conflicto, gana la raíz. Guía Claude: [CLAUDE.md](CLAUDE.md).

## Propósito del producto
Backend del MVP GAS: registro de pedidos de balones de gas (La Molina) para reemplazar el cuaderno físico. Usuario adulto registra desde Android en la calle. Detalle: [README.md](README.md), [../docs/product/GAS-MVP-CONTEXT.md](../docs/product/GAS-MVP-CONTEXT.md).

## Estado actual (vigente 2026-05-22)
- **PostgreSQL es la base de datos activa** del MVP en uso real (deploy Fly+Neon: https://gas-backend-mvp.fly.dev).
- **AWS/IaC y DynamoDB en standby**: no se activan en V2. Decisión: [../docs/roadmap/AWS_STANDBY_DECISION.md](../docs/roadmap/AWS_STANDBY_DECISION.md).
- Fase actual: implementar **V2** sobre PostgreSQL. Orden: [../docs/roadmap/IMPLEMENTATION_ORDER.md](../docs/roadmap/IMPLEMENTATION_ORDER.md).

## Stack
- Python + FastAPI · PostgreSQL · SQLAlchemy · Alembic.
- Dinero siempre en **centavos enteros** (`int`), nunca `double`.
- Comandos de desarrollo: [DEV_COMMANDS.md](DEV_COMMANDS.md). Packaging: [PACKAGING.md](PACKAGING.md).

## Misión backend V2 (orden bloqueante)
1. **V2.0 Stock consistency**: backend como source of truth de stock/resumen; pedidos anulados no cuentan; stock inicial, compras, ventas y ajustes no se mezclan. **Bloqueante**: no construir nada encima de un resumen inconsistente.
2. **V2.1 Anulación/edición**: `POST /pedidos/{pedido_id}/anular`, `PATCH /pedidos/{pedido_id}`; soft-delete con compensación de stock.
3. **V2.2 `peso_balon_kg`** entero 10/45, default 10, compat legacy.
4. **V2.3 Stock por peso**: 10 kg y 45 kg separados, solo tras baseline consistente.
5. **V2.4 Compras a proveedores**: entradas reales del dia separadas de stock inicial/arrastrado y reportables por peso.
6. **V2.5 Clientes**: `GET /clientes` (catálogo simple).
7. **V4 (futuro)**: `GET /reportes/semana`, `GET /reportes/mes` derivados de pedidos activos reales.

Modelo de datos e impacto: [../docs/roadmap/DATA_MODEL_IMPACT_PLAN.md](../docs/roadmap/DATA_MODEL_IMPACT_PLAN.md). Contratos: [../docs/roadmap/API_CONTRACT_PLAN.md](../docs/roadmap/API_CONTRACT_PLAN.md). Guardrails: [../docs/roadmap/STOCK_CONSISTENCY_GUARDRAILS.md](../docs/roadmap/STOCK_CONSISTENCY_GUARDRAILS.md).

## Reglas de dominio obligatorias
- Pedido `ANULADO` no cuenta en `pedidos_count`, `balones_vendidos`, `salidas`, deuda ni montos.
- `stock_actual` = inicial + entradas + ajustes + compensaciones − salidas de pedidos activos.
- `salidas` no incluye anulados; `ajustes` se muestra separado y no oculta una reversa.
- Stock inicial o stock arrastrado del dia anterior no cuenta como compra/entrada real del dia.
- Compras a proveedor aumentan stock y se reportan separadas por peso 10/45.
- Anular dos veces no duplica reversa; editar revierte impacto previo y aplica el nuevo.
- Pedidos legacy sin peso = `10 kg`. Pedido 10 kg no toca stock 45 kg y viceversa.
- PostgreSQL y DynamoDB (router) aplican las mismas reglas.

## Equipo de agentes backend
| Rol | Mandato | Skill |
|---|---|---|
| Backend FastAPI / Stock Consistency Agent | Source of truth, anulación, PATCH, peso. | [gas-backend-stock-consistency](../docs/codex-skills/gas-backend-stock-consistency/SKILL.md) |
| PostgreSQL / Data Model Architect | Campos mínimos, migraciones, índices. | [gas-postgres-minimal](../docs/codex-skills/gas-postgres-minimal/SKILL.md), [gas-sqlalchemy-reports](../docs/codex-skills/gas-sqlalchemy-reports/SKILL.md) |
| API Contracts Agent | Campos y responses para inicio, compras, ventas, ajustes, disponible por peso. | [gas-api-contracts](../docs/codex-skills/gas-api-contracts/SKILL.md) |
| QA / Regression Agent | Matriz bug 17-vs-16, anulados, peso. | [gas-qa-regression-stock-reports](../docs/codex-skills/gas-qa-regression-stock-reports/SKILL.md), [gas-backend-qa](../docs/codex-skills/gas-backend-qa/SKILL.md) |
| Reports Endpoints Agent | `/reportes/*` operativos, dinero en centavos. | [gas-fastapi-reports](../docs/codex-skills/gas-fastapi-reports/SKILL.md), [gas-api-contracts](../docs/codex-skills/gas-api-contracts/SKILL.md) |

## Caso activo: `GAS_stock_compras_proveedores_bug_plan.md`

Para analizar el bug `Entradas: 2` al continuar stock anterior y la necesidad de compras a proveedores:

- Cargar `gas-backend-stock-consistency` primero.
- Cargar `gas-postgres-minimal` si hay modelos, migraciones o Alembic.
- Cargar `gas-api-contracts` antes de proponer respuestas consumidas por Flutter.
- Cargar `gas-fastapi-reports` y `gas-sqlalchemy-reports` para compras diarias/semanales.
- Cargar `gas-qa-regression-stock-reports` para convertir los casos de aceptacion en pruebas.

El diagnostico backend debe responder como minimo:

- Donde se guarda o deriva el stock inicial del dia.
- Donde se guarda o deriva el stock arrastrado del dia anterior.
- Si una entrada de 45 kg se esta usando para representar stock inicial.
- Si compras reales a proveedor existen como movimiento separado.
- Si resumen y reportes devuelven inicio/compras/ventas/ajustes/disponible por `peso_balon_kg`.
- Que endpoints, schemas, services, repositorios, modelos, migraciones y tests quedan afectados.

Reparto modelos: Codex GPT-5.5 implementa; Opus 4.7 audita decisiones delicadas. [../docs/roadmap/MODEL_USAGE_STRATEGY.md](../docs/roadmap/MODEL_USAGE_STRATEGY.md).

## Reglas duras (heredadas)
- NO leer `.env`, `*.env*`, `*.csv`, `~/.aws`, `credentials`; NO imprimir env vars.
- NO ejecutar `aws *`, `terraform *`, `terragrunt *` reales; NO crear recursos AWS.
- NO ejecutar `alembic upgrade head` ni migraciones contra datos reales sin autorización humana.
- NO modificar `app/**` (lógica funcional) sin autorización explícita; proponer diff revisable.
- NO `git push` ni `commit` sin que el usuario lo pida.

## Comandos permitidos
- `git status --short`, `git log`, `git diff`.
- `.\.venv\Scripts\python.exe -m pytest tests -q` (sin red, sin datos reales).
- `python -m py_compile`, `python -c "import x"`.
- Lectura de Markdown, Python no sensible, `pyproject.toml`, `requirements*.txt`.

## Checks antes de cerrar una fase
```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_stock.py tests\test_reportes.py -q
.\.venv\Scripts\python.exe -m pytest tests -q
```
Done V2: tests pasan, reportes/stock excluyen anulados, crear/editar/anular recalcula, legacy = 10 kg, 10/45 no se mezclan, no se ejecutó `alembic upgrade head` contra base real.

## Formato de salida obligatorio
```
- Done:
- Files:
- Checks:
- Risks:
- Next:
```
