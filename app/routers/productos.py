from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import get_current_user, require_owner
from app.models import Insumo, Producto, RecetaItem, User
from app.schemas import ProductoCreate, ProductoOut, RecetaItemIn, RecetaUpdate

router = APIRouter(prefix="/api/productos", tags=["productos"])


def _serializar(producto: Producto) -> ProductoOut:
    return ProductoOut(
        id=producto.id,
        name=producto.name,
        category=producto.category,
        price=producto.price,
        description=producto.description,
        recipe=[RecetaItemIn(ingredientId=r.insumo_id, quantity=r.quantity) for r in producto.recipe],
    )


def _obtener_producto(db: Session, producto_id: int) -> Producto:
    producto = db.get(Producto, producto_id)
    if not producto:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto inexistente.")
    return producto


def _validar_nombre_unico(db: Session, name: str, excluir_id: int | None = None) -> None:
    stmt = select(Producto.id).where(func.lower(Producto.name) == name.lower())
    if excluir_id is not None:
        stmt = stmt.where(Producto.id != excluir_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un producto con ese nombre.",
        )


@router.get("", response_model=list[ProductoOut])
def listar_productos(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Lista el catálogo de productos con su receta, ordenado por nombre."""
    stmt = select(Producto).options(selectinload(Producto.recipe)).order_by(Producto.name)
    return [_serializar(p) for p in db.scalars(stmt).all()]


@router.post("", response_model=ProductoOut, status_code=status.HTTP_201_CREATED)
def crear_producto(
    payload: ProductoCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_owner)],
):
    """Registra un producto nuevo con receta vacía (solo dueño)."""
    _validar_nombre_unico(db, payload.name)
    producto = Producto(
        name=payload.name,
        category=payload.category,
        price=payload.price,
        description=payload.description,
    )
    db.add(producto)
    db.commit()
    db.refresh(producto)
    return _serializar(producto)


@router.put("/{producto_id}", response_model=ProductoOut)
def actualizar_producto(
    producto_id: int,
    payload: ProductoCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_owner)],
):
    """Edita nombre, categoría, precio y descripción (solo dueño). No toca la receta."""
    producto = _obtener_producto(db, producto_id)
    _validar_nombre_unico(db, payload.name, excluir_id=producto.id)

    producto.name = payload.name
    producto.category = payload.category
    producto.price = payload.price
    producto.description = payload.description
    db.commit()
    db.refresh(producto)
    return _serializar(producto)


@router.put("/{producto_id}/receta", response_model=ProductoOut)
def actualizar_receta(
    producto_id: int,
    payload: RecetaUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_owner)],
):
    """Reemplaza la receta completa del producto (solo dueño). Una lista vacía la borra."""
    producto = _obtener_producto(db, producto_id)

    ids = [linea.ingredientId for linea in payload.recipe]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No repitas un ingrediente.")

    if ids:
        existentes = set(db.scalars(select(Insumo.id).where(Insumo.id.in_(ids))).all())
        if existentes != set(ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Primero debes registrar el insumo.",
            )

    # delete-orphan borra las líneas anteriores; flush antes de insertar para no chocar
    # con la restricción única (producto_id, insumo_id).
    producto.recipe.clear()
    db.flush()
    producto.recipe.extend(
        RecetaItem(insumo_id=linea.ingredientId, quantity=linea.quantity) for linea in payload.recipe
    )
    db.commit()
    db.refresh(producto)
    return _serializar(producto)
