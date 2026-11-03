import json
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user
from app.models import Pedido, PedidoItem, User
from app.schemas import PedidoCreate, PedidoStatusUpdate

router = APIRouter(prefix="/api/pedidos", tags=["pedidos"])

@router.get("")
def listar_pedidos(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(get_current_user)]):
    pedidos = db.scalars(select(Pedido).order_by(Pedido.id.desc())).all()
    resultado = []
    for p in pedidos:
        items = db.scalars(select(PedidoItem).where(PedidoItem.pedido_id == p.id)).all()
        items_lista = [{"productId": i.product_id, "name": i.name, "price": i.price, "quantity": i.quantity, "recipe": json.loads(i.recipe)} for i in items]
        resultado.append({"id": str(p.id), "number": p.number, "customer": p.customer, "date": p.date, "channel": p.channel, "notes": p.notes, "status": p.status, "created": p.created.isoformat(), "items": items_lista})
    return resultado

@router.post("", status_code=status.HTTP_201_CREATED)
def crear_pedido(payload: PedidoCreate, db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(get_current_user)]):
    ultimo_pedido = db.scalar(select(Pedido).order_by(Pedido.number.desc()))
    nuevo_numero = (ultimo_pedido.number + 1) if ultimo_pedido else 1
    
    nuevo_pedido = Pedido(number=nuevo_numero, customer=payload.customer, date=payload.date, channel=payload.channel, notes=payload.notes, status="Pendiente")
    db.add(nuevo_pedido)
    db.commit()
    db.refresh(nuevo_pedido)

    # Aquí el frontend manda los items. Como no hemos migrado Productos a Postgres aún, guardamos lo que manda el Front.
    for item in payload.items:
        nuevo_item = PedidoItem(pedido_id=nuevo_pedido.id, product_id=item.productId, name="Producto", price=0.0, quantity=item.quantity, recipe="[]")
        db.add(nuevo_item)
    
    db.commit()
    return {"id": str(nuevo_pedido.id), "number": nuevo_numero, "status": "Pendiente"}

@router.put("/{pedido_id}/estado")
def cambiar_estado(pedido_id: int, payload: PedidoStatusUpdate, db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(get_current_user)]):
    pedido = db.get(Pedido, pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    
    pedido.status = payload.status
    db.commit()
    return {"ok": True, "status": pedido.status}