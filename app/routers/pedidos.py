import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import get_current_user
from app.models import Insumo, MovimientoStock, Pedido, PedidoItem, Producto, User
from app.schemas import PedidoCreate, PedidoStatusUpdate, PedidoUpdate
from app.stock import necesidades, stock_reservado

router = APIRouter(prefix="/api/pedidos", tags=["pedidos"])

CANALES_VALIDOS = {"WhatsApp", "Instagram", "Directo"}
TRANSICIONES_PERMITIDAS: dict[str, set[str]] = {
    "Pendiente": {"Confirmado", "Cancelado"},
    "Confirmado": {"Entregado", "Cancelado"},
    "Entregado": set(),
    "Cancelado": set(),
}


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _serializar(pedido: Pedido) -> dict:
    return {
        "id": pedido.id,
        "number": pedido.number,
        "customer": pedido.customer,
        "date": pedido.date,
        "channel": pedido.channel,
        "notes": pedido.notes,
        "status": pedido.status,
        "created": pedido.created.isoformat(),
        "items": [
            {
                "productId": int(i.product_id) if str(i.product_id).isdigit() else i.product_id,
                "name": i.name,
                "price": i.price,
                "quantity": i.quantity,
                "recipe": json.loads(i.recipe or "[]"),
            }
            for i in pedido.items
        ],
    }


def _construir_items(db: Session, payload_items: list) -> list[PedidoItem]:
    if not payload_items:
        raise _bad_request("Agrega al menos un producto.")

    ids = [it.productId for it in payload_items]
    productos = db.scalars(
        select(Producto).options(selectinload(Producto.recipe)).where(Producto.id.in_(ids))
    ).all()
    por_id = {p.id: p for p in productos}

    nuevos_items: list[PedidoItem] = []
    for item in payload_items:
        prod = por_id.get(item.productId)
        if prod is None or not prod.recipe:
            raise _bad_request("Cada producto debe tener una receta definida.")
        receta_copia = [
            {"ingredientId": r.insumo_id, "quantity": r.quantity} for r in prod.recipe
        ]
        nuevos_items.append(
            PedidoItem(
                product_id=str(prod.id),
                name=prod.name,
                price=prod.price,
                quantity=item.quantity,
                recipe=json.dumps(receta_copia),
            )
        )
    return nuevos_items


@router.get("")
def listar_pedidos(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    stmt = select(Pedido).options(selectinload(Pedido.items)).order_by(Pedido.id.desc())
    return [_serializar(p) for p in db.scalars(stmt).all()]


@router.post("", status_code=status.HTTP_201_CREATED)
def crear_pedido(
    payload: PedidoCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    if payload.channel not in CANALES_VALIDOS:
        raise _bad_request("Canal inválido.")

    items = _construir_items(db, payload.items)
    ultimo = db.scalar(select(func.max(Pedido.number)))
    nuevo_numero = (ultimo or 0) + 1

    pedido = Pedido(
        number=nuevo_numero,
        customer=payload.customer,
        date=payload.date,
        channel=payload.channel,
        notes=payload.notes,
        status="Pendiente",
        items=items,
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
    insumos = db.scalars(
        select(Insumo).where(Insumo.id.in_(necesario)).order_by(Insumo.name)
    ).all()
    por_id = {i.id: i for i in insumos}
    for insumo_id, cantidad in necesario.items():
        insumo = por_id.get(insumo_id)
        disponible = (insumo.stock if insumo else 0.0) - reservado.get(insumo_id, 0.0)
        if round(disponible - cantidad, 6) < 0:
            nombre = insumo.name if insumo else f"#{insumo_id}"
            raise _bad_request(f"Stock insuficiente: {nombre}. Revisa la lista de compras.")


def _entregar(db: Session, pedido: Pedido) -> None:
    """Descuenta el stock y registra los movimientos. Todo o nada."""
    necesario = necesidades(pedido.items)
    if not necesario:
        return
    insumos = db.scalars(
        select(Insumo).where(Insumo.id.in_(necesario)).order_by(Insumo.id).with_for_update()
    ).all()
    por_id = {i.id: i for i in insumos}

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
    """HU012, HU014 y HU016: Cambiar estado, reservar, descontar o cancelar liberando reservas."""
    pedido = db.scalar(
        select(Pedido).options(selectinload(Pedido.items)).where(Pedido.id == pedido_id)
    )
    if not pedido:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado")

    destino = payload.status
    if destino not in TRANSICIONES_PERMITIDAS.get(pedido.status, set()):
        raise _bad_request("Cambio de estado no permitido.")

    if destino == "Confirmado":
        _confirmar(db, pedido)
    elif destino == "Entregado":
        _entregar(db, pedido)

    pedido.status = destino
    db.commit()
    db.refresh(pedido)
    return _serializar(pedido)


@router.put("/{pedido_id}")
def editar_pedido(
    pedido_id: int,
    payload: PedidoUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """HU013: Editar pedido antes de preparación."""
    pedido = db.scalar(
        select(Pedido).options(selectinload(Pedido.items)).where(Pedido.id == pedido_id)
    )
    if not pedido:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado")

    if pedido.status not in {"Pendiente", "Confirmado"}:
        raise _bad_request(
            "No se puede editar el pedido porque ya fue entregado o cancelado."
        )
    if payload.channel not in CANALES_VALIDOS:
        raise _bad_request("Canal inválido.")

    nuevos_items = _construir_items(db, payload.items)

    if pedido.status == "Confirmado":
        necesario = necesidades(nuevos_items)
        reservado = stock_reservado(db, excluir_pedido_id=pedido.id)
        insumos = db.scalars(select(Insumo).where(Insumo.id.in_(necesario))).all()
        por_id = {i.id: i for i in insumos}
        for insumo_id, cantidad in necesario.items():
            insumo = por_id.get(insumo_id)
            disponible = (insumo.stock if insumo else 0.0) - reservado.get(insumo_id, 0.0)
            if round(disponible - cantidad, 6) < 0:
                nombre = insumo.name if insumo else f"#{insumo_id}"
                raise _bad_request(f"Stock insuficiente para editar: {nombre}.")

    pedido.customer = payload.customer
    pedido.date = payload.date
    pedido.channel = payload.channel
    pedido.notes = payload.notes
    pedido.items.clear()
    db.flush()
    pedido.items.extend(nuevos_items)

    db.commit()
    db.refresh(pedido)
    return _serializar(pedido)


@router.post("/validar-stock")
def validar_disponibilidad_stock(
    payload: PedidoCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """HU015 y HU017: Validar disponibilidad de stock y devolver alerta detallada de faltantes (HTTP 409)."""
    items = _construir_items(db, payload.items)
    necesario = necesidades(items)
    reservado = stock_reservado(db)
    insumos = db.scalars(select(Insumo).where(Insumo.id.in_(necesario))).all()
    por_id = {i.id: i for i in insumos}

    faltantes = []
    for insumo_id, requerido in necesario.items():
        insumo = por_id.get(insumo_id)
        disponible = round(max(0.0, (insumo.stock if insumo else 0.0) - reservado.get(insumo_id, 0.0)), 6)
        if round(requerido - disponible, 6) > 0:
            faltante = round(requerido - disponible, 6)
            unidad = insumo.unit.value if insumo else ""
            nombre = insumo.name if insumo else f"#{insumo_id}"
            faltantes.append(
                {
                    "insumo_id": insumo_id,
                    "nombre": nombre,
                    "unidad": unidad,
                    "requerido": requerido,
                    "disponible": disponible,
                    "faltante": faltante,
                    "mensaje": f"Falta: {nombre} — {faltante} {unidad} (Disponible: {disponible} {unidad} / Requerido: {requerido} {unidad})",
                }
            )

    if faltantes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": " | ".join(f["mensaje"] for f in faltantes),
                "faltantes": faltantes,
            },
        )
    return {"ok": True, "message": "Stock suficiente para confirmar el pedido."}