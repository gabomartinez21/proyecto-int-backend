from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import get_current_user, require_owner
from app.models import Insumo, MovimientoStock, Pedido, User
from app.schemas import CompraConfirmarItem, InsumoOut
from app.stock import ESTADO_CONFIRMADO, necesidades

router = APIRouter(prefix="/api/compras", tags=["compras"])


@router.get("/lista-semanal")
def generar_lista_semanal(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    inicio: Annotated[date | None, Query(alias="fecha_inicio")] = None,
    fin: Annotated[date | None, Query(alias="fecha_fin")] = None,
):
    """HU021 y HU022: Generar lista de compra semanal automática con costo estimado."""
    inicio = inicio or date.today()
    fin = fin or inicio + timedelta(days=6)
    if fin < inicio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fecha_fin no puede ser anterior a fecha_inicio.",
        )
    # Pedido.date se guarda como texto ISO (YYYY-MM-DD), que se ordena igual que la fecha.
    fecha_inicio, fecha_fin = inicio.isoformat(), fin.isoformat()
    pedidos_rango = db.scalars(
        select(Pedido)
        .options(selectinload(Pedido.items))
        .where(
            Pedido.status.in_(["Pendiente", ESTADO_CONFIRMADO]),
            Pedido.date >= fecha_inicio,
            Pedido.date <= fecha_fin,
        )
    ).all()

    pedidos_fuera = db.scalars(
        select(Pedido)
        .options(selectinload(Pedido.items))
        .where(
            Pedido.status == ESTADO_CONFIRMADO,
            (Pedido.date < fecha_inicio) | (Pedido.date > fecha_fin),
        )
    ).all()

    requerido_map = necesidades([it for p in pedidos_rango for it in p.items])
    reservado_fuera = necesidades([it for p in pedidos_fuera for it in p.items])

    insumos = db.scalars(select(Insumo).order_by(Insumo.name)).all()
    items = []
    presupuesto_total = 0.0

    for ins in insumos:
        req = round(requerido_map.get(ins.id, 0.0), 6)
        if req <= 0:
            continue
        disp = round(max(0.0, ins.stock - reservado_fuera.get(ins.id, 0.0)), 6)
        comprar = round(max(0.0, req - disp), 6)
        costo_estimado = round(comprar * ins.cost, 2)
        presupuesto_total = round(presupuesto_total + costo_estimado, 2)
        items.append(
            {
                "id": str(ins.id),
                "name": ins.name,
                "unit": ins.unit.value,
                "stock": ins.stock,
                "minimum": ins.minimum,
                "cost": ins.cost,
                "required": req,
                "available": disp,
                "buy": comprar,
                "estimatedCost": costo_estimado,
            }
        )

    faltantes = [x for x in items if x["buy"] > 0]
    mensaje = (
        "Stock suficiente para los pedidos de la semana."
        if not faltantes
        else f"Se requieren {len(faltantes)} insumos por comprar."
    )

    return {
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "mensaje": mensaje,
        "presupuesto_estimado": presupuesto_total,
        "items": items,
    }


@router.post("/confirmar-item", response_model=InsumoOut)
def confirmar_item_comprado(
    payload: CompraConfirmarItem,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_owner)],
):
    """HU023: Ingreso rápido de insumos comprados para actualizar el almacén."""
    insumo = db.get(Insumo, payload.insumo_id)
    if not insumo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo inexistente")

    insumo.stock = round(insumo.stock + payload.quantity, 6)
    db.add(
        MovimientoStock(
            insumo_id=insumo.id,
            ingredient=insumo.name,
            quantity=payload.quantity,
            unit=insumo.unit.value,
            note=payload.note.strip() or "Compra semanal confirmada",
        )
    )
    db.commit()
    db.refresh(insumo)
    return insumo
