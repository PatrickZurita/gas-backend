from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base  # idealmente mover Base aquí


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    telefono: Mapped[str] = mapped_column(String(30), index=True)
    nombre: Mapped[str | None] = mapped_column(String(120), nullable=True)

    direcciones: Mapped[list[Direccion]] = relationship(
        back_populates="cliente",
        cascade="all, delete-orphan",
    )
    pedidos: Mapped[list[Pedido]] = relationship(
        back_populates="cliente",
        cascade="all, delete-orphan",
    )


class Direccion(Base):
    __tablename__ = "direcciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(
        ForeignKey("clientes.id", ondelete="CASCADE"),
        index=True,
    )

    texto_original: Mapped[str] = mapped_column(String(300))
    distrito: Mapped[str | None] = mapped_column(String(80), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(120), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)

    cliente: Mapped[Cliente] = relationship(back_populates="direcciones")
    pedidos: Mapped[list[Pedido]] = relationship(
        back_populates="direccion",
        cascade="all, delete-orphan",
    )


class Pedido(Base):
    __tablename__ = "pedidos"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(
        ForeignKey("clientes.id", ondelete="CASCADE"),
        index=True,
    )
    direccion_id: Mapped[int] = mapped_column(
        ForeignKey("direcciones.id", ondelete="CASCADE"),
        index=True,
    )

    fecha_pedido: Mapped[date] = mapped_column(Date, index=True)
    cantidad_balones: Mapped[int] = mapped_column(Integer)

    total_soles: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    pagado: Mapped[bool] = mapped_column(Boolean, default=True)
    saldo_pendiente: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))

    cliente: Mapped[Cliente] = relationship(back_populates="pedidos")
    direccion: Mapped[Direccion] = relationship(back_populates="pedidos")
    