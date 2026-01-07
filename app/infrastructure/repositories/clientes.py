from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Cliente, Direccion

def crear_cliente(db: Session, alias: str, telefono: str, direccion: str) -> Cliente:
    cliente = Cliente(alias=alias, telefono=telefono, nombre=None)
    db.add(cliente)
    db.flush()  # obtiene cliente.id sin commit

    dir1 = Direccion(
        cliente_id=cliente.id,
        texto_original=direccion,
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