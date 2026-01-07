# 🚚 Gas Backend & Mobile App (MVP)

## 1. Descripción general del proyecto

Este proyecto consiste en una **app móvil con backend propio** para un negocio real de
**distribución de balones de gas** que opera en el distrito de **La Molina (Perú)**.

El objetivo principal es **reemplazar el registro manual en cuadernos físicos**
por un sistema digital **rápido, simple y confiable**, pensado para un **usuario mayor
de 50 años** que registra los pedidos **en el momento de la entrega**, directamente
desde su celular.

La aplicación no está pensada como un sistema administrativo complejo,
sino como una **herramienta operativa diaria**, enfocada en **reducir errores humanos**
y **mejorar el control del negocio**.

---

## 2. Problema real que se quiere resolver

Actualmente, el negocio registra los pedidos en hojas sueltas o cuadernos, donde se anota:

- Dirección del cliente
- Fecha del pedido
- Monto pagado
- Si el cliente debe o no

Este método genera problemas reales como:

- ❌ Pedidos que se olvidan de anotar  
- ❌ Letras ilegibles o confusión al revisar días pasados  
- ❌ Descuadres de stock  
  (ej. el cuaderno dice que se vendieron 10 balones, pero físicamente hay 9)
- ❌ Dificultad para saber cuándo un cliente suele volver a pedir
- ❌ Imposibilidad de analizar zonas con mayor o menor demanda

El sistema busca atacar estos problemas **desde la raíz**, facilitando el
**registro inmediato y confiable**.

---

## 3. Objetivo del MVP (fase actual)

En esta primera fase, el objetivo es **operativo**, no analítico:

- ✅ Registrar pedidos de forma rápida y simple
- ✅ Reducir la posibilidad de pedidos no registrados
- ✅ Permitir búsqueda de clientes tipo *contactos del celular*
- ✅ Registrar pagos y deudas reales (entregado pero no pagado)
- ✅ Consultar historial de pedidos por cliente

El éxito del MVP se mide con una sola pregunta:

> **¿El negocio dejó de depender del cuaderno?**

---

## 4. Enfoque de usuario (UX real)

El usuario final:

- Tiene más de 50 años
- Usa principalmente el celular
- Registra pedidos mientras trabaja en la calle
- Guarda clientes como contactos con la dirección como nombre

Por eso, la app debe:

- Tener pocos campos
- Evitar escritura innecesaria
- Usar autocompletado por dirección o teléfono
- Registrar pedidos en pocos toques
- Asignar valores por defecto (fecha = hoy)

---

## 5. Modelo de negocio reflejado en el sistema

### Cliente
- El cliente se identifica por un **alias**, normalmente la dirección  
  (ej. *“Las Higueras 371”*)
- Puede tener teléfono
- No se fuerza normalización estricta en el MVP

### Pedido
Cada pedido registra:

- Cliente
- Fecha del pedido (automática por defecto)
- Cantidad de balones
- Total en soles
- Si fue pagado o no
- Saldo pendiente (cuando hay deuda)

Esto refleja exactamente cómo funciona el negocio en la vida real:
El gas se entrega aunque el cliente no pague en el momento.

---

## 6. Problema adicional identificado: control de stock

El registro en papel provoca **descuadres entre el stock físico y los pedidos anotados**.

Aunque el MVP no implementa inventarios formales, el registro inmediato:

- Reduce errores
- Permite detectar inconsistencias
- Prepara el terreno para control de stock futuro

---

## 7. Arquitectura técnica (backend)

### Stack
- **Backend:** Python + FastAPI
- **Base de datos:** PostgreSQL
- **ORM:** SQLAlchemy
- **Migraciones:** Alembic

### Enfoque
- Backend minimalista orientado al flujo real
- Arquitectura *clean-ish / layered lite*
- Docker opcional (agnóstico al entorno)
- Preparado para análisis futuro

---

## 8. Endpoints principales del MVP

### Clientes
- `POST /clientes`
- `GET /clientes/search?q=...`
- `GET /clientes/{id}`

### Pedidos
- `POST /pedidos`
- `GET /pedidos?cliente_id=...`

Estos endpoints permiten construir el **frontend móvil completo del MVP**.

---

## 9. Uso de datos históricos

El negocio cuenta con pedidos antiguos registrados en papel.

Estos datos:

- Sí son valiosos
- Se migrarán a Excel
- Luego se cargarán de forma masiva al sistema

No se busca perfección, sino **histórico suficiente** para análisis.

---

## 10. Objetivos a futuro

Una vez consolidado el MVP:

- Análisis de recurrencia de pedidos
- Predicción de próximas compras
- Análisis geográfico por zonas
- Mapas de calor para marketing físico
- Control básico de stock
- Recordatorios automáticos

---

## 11. Principio rector del proyecto

> **Primero resolver el problema operativo real.  
> Luego usar los datos para inteligencia del negocio.**