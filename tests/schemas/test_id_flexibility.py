from datetime import date, datetime
from decimal import Decimal

from app.schemas.cliente import ClienteOut
from app.schemas.pedido import PedidoCreate, PedidoOut
from app.schemas.stock import MovimientoStockOut


UUID_STR = "a1b2c3d4-e5f6-47g8-h9i0-j1k2l3m4n5o6"


def _cliente_kwargs(id_value):
    return dict(
        id=id_value,
        alias="Test",
        telefono="999999999",
        direccion="Las Higueras 371",
    )


def test_cliente_out_acepta_int_id():
    cliente = ClienteOut(**_cliente_kwargs(123))
    assert cliente.id == 123
    assert isinstance(cliente.id, int)


def test_cliente_out_acepta_uuid_string_id():
    cliente = ClienteOut(**_cliente_kwargs(UUID_STR))
    assert cliente.id == UUID_STR
    assert isinstance(cliente.id, str)


def test_pedido_create_acepta_int_cliente_id():
    pedido = PedidoCreate(cliente_id=42, cantidad_balones=1, total_soles=Decimal("30.00"))
    assert pedido.cliente_id == 42


def test_pedido_create_acepta_uuid_cliente_id():
    pedido = PedidoCreate(
        cliente_id=UUID_STR,
        cantidad_balones=1,
        total_soles=Decimal("30.00"),
    )
    assert pedido.cliente_id == UUID_STR


def _pedido_out_kwargs(id_value, cliente_id, direccion_id):
    return dict(
        id=id_value,
        cliente_id=cliente_id,
        direccion_id=direccion_id,
        created_at=datetime(2026, 5, 14, 10, 0, 0),
        fecha_entrega=date(2026, 5, 14),
        cantidad_balones=2,
        total_soles=Decimal("60.00"),
        tipo_balon="NORMAL",
        marca_balon="PETROPERU",
        precio_unitario_centavos=3000,
        monto_total_centavos=6000,
        pagado=True,
        saldo_pendiente=Decimal("0.00"),
        monto_pendiente_centavos=0,
    )


def test_pedido_out_acepta_int_ids():
    pedido = PedidoOut(**_pedido_out_kwargs(1, 2, 3))
    assert pedido.id == 1
    assert pedido.cliente_id == 2
    assert pedido.direccion_id == 3


def test_pedido_out_acepta_uuid_ids():
    pedido = PedidoOut(**_pedido_out_kwargs(UUID_STR, UUID_STR, UUID_STR))
    assert pedido.id == UUID_STR
    assert pedido.cliente_id == UUID_STR
    assert pedido.direccion_id == UUID_STR


def _movimiento_kwargs(id_value, pedido_id):
    return dict(
        id=id_value,
        tipo="ENTRADA",
        cantidad_delta=5,
        stock_resultante=10,
        pedido_id=pedido_id,
        observacion=None,
        created_at=datetime(2026, 5, 14, 10, 0, 0),
    )


def test_movimiento_stock_out_acepta_int_ids():
    mov = MovimientoStockOut(**_movimiento_kwargs(1, 2))
    assert mov.id == 1
    assert mov.pedido_id == 2


def test_movimiento_stock_out_acepta_uuid_ids():
    mov = MovimientoStockOut(**_movimiento_kwargs(UUID_STR, UUID_STR))
    assert mov.id == UUID_STR
    assert mov.pedido_id == UUID_STR


def test_movimiento_stock_out_acepta_pedido_id_none():
    mov = MovimientoStockOut(**_movimiento_kwargs(1, None))
    assert mov.pedido_id is None
