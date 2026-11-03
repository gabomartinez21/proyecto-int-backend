import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import get_current_user
from app.models import Insumo, MovimientoStock, Pedido, PedidoItem, Producto, User
from app.schemas import PedidoCreate, PedidoStatusUpdate
from app.stock import ESTADO_CONFIRMADO, necesidades, stock_reservado

router = APIRouter(prefix="/api/pedidos", tags=["pedidos"])

CANALES = ["WhatsApp", "Instagram", "Directo"]
ESTADO_PENDIENTE = "Pendiente"
ESTADO_ENTREGADO = "Entregado"
ESTADO_CANCELADO = "Cancelado"
ESTADOS = [ESTADO_PENDIENTE, ESTADO_CONFIRMADO, ESTADO_ENTREGADO, ESTADO_CANCELADO]
TRANSICIONES: dict[str, set[str]] = {
    ESTADO_PENDIENTE: {ESTADO_CONFIRMADO, ESTADO_CANCELADO},
    ESTADO_CONFIRMADO: {ESTADO_ENTREGADO, ESTADO_CANCELADO},
}


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _product_id_out(valor: str) -> int | str:
    # Los pedidos antiguos (de antes de migrar productos) pueden tener ids no numéricos.
    return int(valor) if valor.isdigit() else valor


def _serializar(p: Pedido) -> dict:
    return {
        "id": str(p.id),
        "number": p.number,
        "customer": p.customer,
        "date": p.date,
        "channel": p.channel,
        "notes": p.notes,
        "status": p.status,
        "created": p.created.isoformat(),
        "items": [
            {
                "productId": _product_id_out(i.product_id),
                "name": i.name,
                "price": i.price,
                "quantity": i.quantity,
                "recipe": json.loads(i.recipe or "[]"),
            }
            for i in p.items
        ],
    }


@router.get("")
def listar_pedidos(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(get_current_user)]):
    stmt = select(Pedido).options(selectinload(Pedido.items)).order_by(Pedido.id.desc())
    return [_serializar(p) for p in db.scalars(stmt).all()]


@router.post("", status_code=status.HTTP_201_CREATED)
def crear_pedido(
    payload: PedidoCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    if not payload.items:
        raise _bad_request("Agrega al menos un producto.")
    if payload.channel not in CANALES:
        raise _bad_request("Canal inválido.")

    ids = {item.productId for item in payload.items}
    productos = {
        p.id: p
        for p in db.scalars(
            select(Producto).options(selectinload(Producto.recipe)).where(Producto.id.in_(ids))
        ).all()
    }
    if any(pid not in productos or not productos[pid].recipe for pid in ids):
        raise _bad_request("Cada producto debe tener una receta definida.")

    ultimo_numero = db.scalar(select(func.max(Pedido.number))) or 0
    pedido = Pedido(
        number=ultimo_numero + 1,
        customer=payload.customer.strip(),
        date=payload.date,
        channel=payload.channel,
        notes=payload.notes.strip(),
        status=ESTADO_PENDIENTE,
    )
    for item in payload.items:
        producto = productos[item.productId]
        receta = [{"ingredientId": r.insumo_id, "quantity": r.quantity} for r in producto.recipe]
        pedido.items.append(
            PedidoItem(
                product_id=str(producto.id),
                name=producto.name,
                price=producto.price,
                quantity=item.quantity,
                recipe=json.dumps(receta),
            )
        )
    db.add(pedido)
    db.commit()
    db.refresh(pedido)
    return _serializar(pedido)


def _confirmar(db: Session, pedido: Pedido) -> None:
    """Verifica que el stock libre (stock - reservado por otros confirmados) alcance."""
    necesario = necesidades(pedido.items)
    if not necesario:
        return
    reservado = stock_reservado(db, excluir_pedido_id=pedido.id)
    insumos = db.scalars(select(Insumo).where(Insumo.id.in_(necesario)).order_by(Insumo.name)).all()
    por_id = {i.id: i for i in insumos}
    for insumo_id, cantidad in necesario.items():
        insumo = por_id.get(insumo_id)
        disponible = (insumo.stock if insumo else 0.0) - reservado.get(insumo_id, 0.0)
        if round(disponible - cantidad, 6) < 0:
            nombre = insumo.name if insumo else f"#{insumo_id}"
            raise _bad_request(f"Stock insuficiente: {nombre}. Revisa la lista de compras.")


def _entregar(db: Session, pedido: Pedido) -> None:
    """Descuenta el stock y registra los movimientos. Todo o nada: si falta algo, no se toca nada."""
    necesario = necesidades(pedido.items)
    if not necesario:
        return
    insumos = db.scalars(
        select(Insumo).where(Insumo.id.in_(necesario)).order_by(Insumo.id).with_for_update()
    ).all()
    por_id = {i.id: i for i in insumos}

    # Primero se valida todo y recién después se modifica, para no dejar cambios a medias.
    for insumo_id, cantidad in necesario.items():
        insumo = por_id.get(insumo_id)
        if insumo is None or round(insumo.stock - cantidad, 6) < 0:
            raise _bad_request("Stock insuficiente.")

    for insumo_id, cantidad in necesario.items():
        insumo = por_id[insumo_id]
        insumo.stock = round(insumo.stock - cantidad, 6)
        db.add(
            MovimientoStock(
                insumo_id=insumo.id,
                ingredient=insumo.name,
                quantity=-cantidad,
                unit=insumo.unit.value,
                note=f"Entrega de pedido #{pedido.number}",
            )
        )


@router.put("/{pedido_id}/estado")
def cambiar_estado(
    pedido_id: int,
    payload: PedidoStatusUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    pedido = db.scalar(
        select(Pedido).options(selectinload(Pedido.items)).where(Pedido.id == pedido_id).with_for_update()
    )
    if not pedido:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado")

    nuevo = payload.status
    if nuevo not in ESTADOS:
        raise _bad_request("Estado inválido.")
    if nuevo not in TRANSICIONES.get(pedido.status, set()):
        raise _bad_request("Cambio de estado no permitido.")

    try:
        if nuevo == ESTADO_CONFIRMADO:
            _confirmar(db, pedido)
        elif nuevo == ESTADO_ENTREGADO:
            _entregar(db, pedido)
        pedido.status = nuevo
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(pedido)
    return _serializar(pedido)
