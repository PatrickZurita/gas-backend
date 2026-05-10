from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Cliente, Direccion, Pedido

def crear_cliente(db: Session, alias: str, telefono: str) -> Cliente:
    cliente = Cliente(alias=alias, telefono=telefono, nombre=None)
    db.add(cliente)
    db.flush()
    
    dir1 = Direccion(
        cliente_id=cliente.id,
        texto_original=alias,
        distrito=None,
        referencia=None,
        activa=True,
    )
    db.add(dir1)

    db.commit()
    db.refresh(cliente)
    return cliente

def buscar_clientes(db: Session, q: str, limit: int = 10) -> list[Cliente]:
    q = q.strip()
    stmt = (
        select(Cliente)
        .where((Cliente.alias.ilike(f"%{q}%")) | (Cliente.telefono.ilike(f"%{q}%")))
        .order_by(Cliente.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())

def obtener_cliente(db: Session, cliente_id: int) -> Cliente | None:
    return db.get(Cliente, cliente_id)

def obtener_cliente_por_id(db: Session, cliente_id: int) -> Cliente | None:
    return db.get(Cliente, cliente_id)

def listar_clientes_recientes(db: Session, limit: int = 10) -> list[tuple[Cliente, Pedido]]:
    stmt = (
        select(Cliente, Pedido)
        .join(Pedido, Pedido.cliente_id == Cliente.id)
        .order_by(Pedido.created_at.desc(), Pedido.id.desc())
    )
    rows = db.execute(stmt).all()

    recientes: list[tuple[Cliente, Pedido]] = []
    seen: set[int] = set()
    for cliente, pedido in rows:
        if cliente.id in seen:
            continue
        recientes.append((cliente, pedido))
        seen.add(cliente.id)
        if len(recientes) >= limit:
            break

    return recientes
