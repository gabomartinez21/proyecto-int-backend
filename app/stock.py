"""Cálculo de insumos necesarios y reservados por pedidos.

Siempre se usa la receta COPIADA en cada PedidoItem (no la receta actual del producto),
para que un cambio de receta no altere pedidos ya creados.
"""
import json
from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Pedido, PedidoItem

ESTADO_CONFIRMADO = "Confirmado"


def necesidades(items: Iterable[PedidoItem]) -> dict[int, float]:
    """Suma receta × cantidad de cada línea, agrupado por insumo_id."""
    total: dict[int, float] = defaultdict(float)
    for item in items:
        for linea in json.loads(item.recipe or "[]"):
            total[int(linea["ingredientId"])] += float(linea["quantity"]) * item.quantity
    return {k: round(v, 6) for k, v in total.items()}


def stock_reservado(db: Session, excluir_pedido_id: int | None = None) -> dict[int, float]:
    """Insumos reservados por los pedidos en estado Confirmado (opcionalmente excluyendo uno)."""
    stmt = (
        select(PedidoItem)
        .join(Pedido, PedidoItem.pedido_id == Pedido.id)
        .where(Pedido.status == ESTADO_CONFIRMADO)
    )
    if excluir_pedido_id is not None:
        stmt = stmt.where(Pedido.id != excluir_pedido_id)
    return necesidades(db.scalars(stmt).all())
