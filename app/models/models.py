from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
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
    __table_args__ = (
        CheckConstraint(
            "tipo_balon IN ('NORMAL', 'PREMIUM')",
            name="ck_pedidos_tipo_balon_valido",
        ),
        CheckConstraint(
            "marca_balon IN ('SOLGAS', 'PETROPERU')",
            name="ck_pedidos_marca_balon_valida",
        ),
        CheckConstraint(
            "precio_unitario_centavos IS NULL OR precio_unitario_centavos >= 0",
            name="ck_pedidos_precio_unitario_centavos_ge_0",
        ),
        CheckConstraint(
            "monto_total_centavos IS NULL OR monto_total_centavos >= 0",
            name="ck_pedidos_monto_total_centavos_ge_0",
        ),
        CheckConstraint(
            "monto_pendiente_centavos IS NULL OR monto_pendiente_centavos >= 0",
            name="ck_pedidos_monto_pendiente_centavos_ge_0",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(
        ForeignKey("clientes.id", ondelete="CASCADE"),
        index=True,
    )
    direccion_id: Mapped[int] = mapped_column(
        ForeignKey("direcciones.id", ondelete="CASCADE"),
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    fecha_entrega: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        server_default=func.current_date(),
    )

    cantidad_balones: Mapped[int] = mapped_column(Integer)
    total_soles: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    tipo_balon: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="NORMAL",
        server_default="NORMAL",
    )
    marca_balon: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="PETROPERU",
        server_default="PETROPERU",
    )
    precio_unitario_centavos: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    monto_total_centavos: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    pagado: Mapped[bool] = mapped_column(Boolean, default=True)
    saldo_pendiente: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    monto_pendiente_centavos: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    cliente: Mapped["Cliente"] = relationship(back_populates="pedidos")
    direccion: Mapped["Direccion"] = relationship(back_populates="pedidos")
    movimientos_stock: Mapped[list["MovimientoStock"]] = relationship(
        back_populates="pedido"
    )


class StockJornada(Base):
    __tablename__ = "stock_jornadas"
    __table_args__ = (
        CheckConstraint("stock_inicial >= 0", name="ck_stock_jornadas_inicial_ge_0"),
        CheckConstraint(
            "stock_final_fisico IS NULL OR stock_final_fisico >= 0",
            name="ck_stock_jornadas_final_ge_0",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    stock_inicial: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_actual: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_final_fisico: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cerrado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    movimientos: Mapped[list["MovimientoStock"]] = relationship(
        back_populates="stock_jornada",
        cascade="all, delete-orphan",
    )


class MovimientoStock(Base):
    __tablename__ = "movimientos_stock"
    __table_args__ = (
        CheckConstraint(
            "tipo IN ('INICIO_DIA', 'ENTRADA', 'SALIDA_PEDIDO', 'AJUSTE')",
            name="ck_movimientos_stock_tipo_valido",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_jornada_id: Mapped[int] = mapped_column(
        ForeignKey("stock_jornadas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fecha: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    cantidad_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_resultante: Mapped[int] = mapped_column(Integer, nullable=False)
    pedido_id: Mapped[int | None] = mapped_column(
        ForeignKey("pedidos.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    marca_balon: Mapped[str | None] = mapped_column(String(30), nullable=True)
    tipo_balon: Mapped[str | None] = mapped_column(String(30), nullable=True)
    observacion: Mapped[str | None] = mapped_column(String(250), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    stock_jornada: Mapped["StockJornada"] = relationship(back_populates="movimientos")
    pedido: Mapped["Pedido | None"] = relationship(back_populates="movimientos_stock")
