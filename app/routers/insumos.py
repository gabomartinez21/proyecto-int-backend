from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_owner
from app.models import Insumo, MovimientoStock, TipoMovimiento, User
from app.schemas import InsumoCreate, InsumoOut, MovimientoOut, StockMovementCreate

router = APIRouter(prefix="/api/insumos", tags=["insumos"])


@router.get("", response_model=list[InsumoOut])
def listar_insumos(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """HU007: Ver stock actual de todos los insumos."""
    return list(db.scalars(select(Insumo).order_by(Insumo.name)).all())


@router.post("", response_model=InsumoOut, status_code=status.HTTP_201_CREATED)
def crear_insumo(
    payload: InsumoCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_owner)],
):
    """HU005: Registrar insumo nuevo con stock inicial en 0 (solo dueño)."""
    existe = db.scalar(
        select(Insumo).where(func.lower(Insumo.name) == payload.name.lower())
    )
    if existe:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El insumo ya existe",
        )

    nuevo = Insumo(
        name=payload.name,
        unit=payload.unit,
        stock=0.0,
        minimum=payload.minimum,
        cost=payload.cost,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo


@router.post("/{insumo_id}/stock", response_model=InsumoOut)
def actualizar_stock(
    insumo_id: int,
    payload: StockMovementCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_owner)],
):
    """HU006 y HU008: Ingreso o salida manual de stock con motivo obligatorio."""
    insumo = db.get(Insumo, insumo_id)
    if not insumo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Insumo inexistente",
        )

    delta = payload.quantity if payload.kind == TipoMovimiento.entrada else -payload.quantity
    nuevo_stock = round(insumo.stock + delta, 6)

    if nuevo_stock < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay stock suficiente para esta salida",
        )

    insumo.stock = nuevo_stock
    mov = MovimientoStock(
        insumo_id=insumo.id,
        ingredient=insumo.name,
        quantity=delta,
        unit=insumo.unit.value,
        note=payload.note,
    )
    db.add(mov)
    db.commit()
    db.refresh(insumo)
    return insumo


@router.get("/movimientos", response_model=list[MovimientoOut])
def listar_movimientos(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Lista los últimos movimientos de stock."""
    stmt = select(MovimientoStock).order_by(MovimientoStock.id.desc()).limit(20)
    return list(db.scalars(stmt).all())