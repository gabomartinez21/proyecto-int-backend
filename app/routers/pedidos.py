import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import get_current_user, require_owner
from app.models import Insumo, MovimientoStock, Pedido, PedidoItem, Producto, User
from app.schemas import PedidoCreate, PedidoStatusUpdate, PedidoUpdate
from app.stock import ESTADO_CONFIRMADO, necesidades, stock_reservado

router = APIRouter(prefix="/api/pedidos", tags=["pedidos"])

CANALES = ["WhatsApp", "Instagram", "Directo"]
ESTADO_PENDIENTE = "Pendiente de pago"
ESTADO_EN_PREPARACION = "En preparación"
ESTADO_LISTO = "Listo para entrega"
ESTADO_ENTREGADO = "Entregado"
ESTADO_CANCELADO = "Cancelado"
ESTADOS = [
    ESTADO_PENDIENTE, ESTADO_CONFIRMADO, ESTADO_EN_PREPARACION,
    ESTADO_LISTO, ESTADO_ENTREGADO, ESTADO_CANCELADO,
]
TRANSICIONES: dict[str, set[str]] = {
    ESTADO_PENDIENTE: {ESTADO_CONFIRMADO, ESTADO_CANCELADO},
    ESTADO_CONFIRMADO: {ESTADO_EN_PREPARACION, ESTADO_CANCELADO},
    ESTADO_EN_PREPARACION: {ESTADO_LISTO},
    ESTADO_LISTO: {ESTADO_ENTREGADO},
}
EDITABLES = {ESTADO_PENDIENTE, ESTADO_CONFIRMADO}
PAGO_VALIDADO = "Validado"
MAX_COMPROBANTE_BYTES = 5 * 1024 * 1024
COMPROBANTES_DIR = Path("uploads/comprobantes")
TIPOS_COMPROBANTE = {"image/jpeg": (".jpg", b"\xff\xd8"), "image/png": (".png", b"\x89PNG")}


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _product_id_out(valor: str) -> int | str:
    # Los pedidos antiguos (de antes de migrar productos) pueden tener ids no numéricos.
    return int(valor) if valor.isdigit() else valor


def _serializar(pedido: Pedido) -> dict:
    return {
        "id": str(pedido.id),
        "number": pedido.number,
        "customer": pedido.customer,
        "date": pedido.date,
        "channel": pedido.channel,
        "notes": pedido.notes,
        "status": pedido.status,
        "created": pedido.created.isoformat(),
        "paymentStatus": pedido.payment_status,
        "operationCode": pedido.operation_code,
        "paymentProofUrl": pedido.payment_proof_url,
        "paymentValidatedBy": pedido.payment_validated_by,
        "paymentValidatedAt": pedido.payment_validated_at.isoformat() if pedido.payment_validated_at else None,
        "deliveredAt": pedido.delivered_at.isoformat() if pedido.delivered_at else None,
        "deliveryReceiver": pedido.delivery_receiver,
        "items": [
            {
                "productId": _product_id_out(i.product_id),
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

    ids = {it.productId for it in payload_items}
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
    if payload.channel not in CANALES:
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
        status=ESTADO_PENDIENTE,
        items=items,
    )
    db.add(pedido)
    db.commit()
    db.refresh(pedido)
    return _serializar(pedido)


def _confirmar(
    db: Session,
    pedido: Pedido,
    items: list[PedidoItem] | None = None,
    mensaje: str = "Stock insuficiente: {nombre}. Revisa la lista de compras.",
) -> None:
    """Verifica que el stock libre (stock - reservado por otros confirmados) alcance."""
    necesario = necesidades(pedido.items if items is None else items)
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
            raise _bad_request(mensaje.format(nombre=nombre))


def _preparar(db: Session, pedido: Pedido) -> None:
    """HU016: al pasar a En preparación descuenta En Almacén (la reserva se libera sola al dejar Confirmado)."""
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
                note=f"Preparación de pedido #{pedido.number}",
            )
        )


def _obtener_para_actualizar(db: Session, pedido_id: int) -> Pedido:
    pedido = db.scalar(
        select(Pedido).options(selectinload(Pedido.items)).where(Pedido.id == pedido_id).with_for_update()
    )
    if not pedido:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado")
    return pedido


@router.put("/{pedido_id}/estado")
def cambiar_estado(
    pedido_id: int,
    payload: PedidoStatusUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """HU012, HU014 y HU016: avanzar estado; reservar al confirmar, descontar al preparar."""
    pedido = _obtener_para_actualizar(db, pedido_id)

    nuevo = payload.status
    if nuevo not in ESTADOS:
        raise _bad_request("Estado inválido.")
    if nuevo not in TRANSICIONES.get(pedido.status, set()):
        raise _bad_request("Cambio de estado no permitido.")

    try:
        if nuevo == ESTADO_CONFIRMADO:
            if pedido.payment_status != PAGO_VALIDADO:
                raise _bad_request("El pago debe ser validado por la dueña (HU024) antes de confirmar.")
            _confirmar(db, pedido)
        elif nuevo == ESTADO_EN_PREPARACION:
            _preparar(db, pedido)
        elif nuevo == ESTADO_ENTREGADO:
            receptor = (payload.receiver or "").strip()
            if not receptor:
                raise _bad_request("Para marcar Entregado indica quién recibió el pedido.")
            pedido.delivery_receiver = receptor
            pedido.delivered_at = datetime.now(timezone.utc)
        pedido.status = nuevo
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(pedido)
    return _serializar(pedido)


@router.patch("/{pedido_id}/validar-pago")
def validar_pago(
    pedido_id: int,
    db: Annotated[Session, Depends(get_db)],
    owner: Annotated[User, Depends(require_owner)],
    codigo_operacion: Annotated[str | None, Form()] = None,
    comprobante: Annotated[UploadFile | None, File()] = None,
):
    """HU024: la dueña valida el pago (JPG/PNG <= 5 MB o código) y, con stock suficiente, confirma y reserva."""
    pedido = _obtener_para_actualizar(db, pedido_id)
    if pedido.status != ESTADO_PENDIENTE:
        raise _bad_request("Solo se puede validar el pago de un pedido Pendiente de pago.")

    codigo = (codigo_operacion or "").strip() or None
    if comprobante is not None and not comprobante.filename:
        comprobante = None
    ya_validado = pedido.payment_status == PAGO_VALIDADO

    guardar: tuple[str, bytes] | None = None
    if not ya_validado:
        if comprobante is None and not codigo:
            raise _bad_request("Adjunta un comprobante (JPG/PNG) o ingresa el código de operación.")
        if comprobante is not None:
            tipo = TIPOS_COMPROBANTE.get(comprobante.content_type or "")
            if tipo is None:
                raise _bad_request("Formato no permitido: el comprobante debe ser JPG o PNG.")
            data = comprobante.file.read(MAX_COMPROBANTE_BYTES + 1)
            if len(data) > MAX_COMPROBANTE_BYTES:
                raise _bad_request("El comprobante supera el máximo de 5 MB.")
            if not data.startswith(tipo[1]):
                raise _bad_request("El archivo no es una imagen JPG/PNG válida.")
            guardar = (tipo[0], data)

    try:
        if not ya_validado:
            if guardar is not None:
                COMPROBANTES_DIR.mkdir(parents=True, exist_ok=True)
                nombre = f"pedido-{pedido.id}-{uuid.uuid4().hex}{guardar[0]}"
                (COMPROBANTES_DIR / nombre).write_bytes(guardar[1])
                pedido.payment_proof_url = f"uploads/comprobantes/{nombre}"
            pedido.operation_code = codigo
            pedido.payment_status = PAGO_VALIDADO
            pedido.payment_validated_by = owner.username
            pedido.payment_validated_at = datetime.now(timezone.utc)

        faltantes = _faltantes(db, pedido.items, excluir_pedido_id=pedido.id)
        if faltantes:
            # El pago queda validado, no se confirma ni se reserva (HU024 #4 / HU017).
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "Pago validado, pero falta stock: " + " | ".join(f["mensaje"] for f in faltantes),
                    "pagoValidado": True,
                    "faltantes": faltantes,
                },
            )
        pedido.status = ESTADO_CONFIRMADO
        db.commit()
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise

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
    pedido = _obtener_para_actualizar(db, pedido_id)

    if pedido.status not in EDITABLES:
        raise _bad_request("No se puede editar el pedido porque ya fue entregado o cancelado.")
    if payload.channel not in CANALES:
        raise _bad_request("Canal inválido.")
    # Se permite conservar la fecha original aunque ya haya pasado; una fecha nueva no puede ser pasada.
    if payload.date != pedido.date and payload.date < date.today().isoformat():
        raise _bad_request("La fecha de entrega no puede ser anterior a hoy.")

    nuevos_items = _construir_items(db, payload.items)

    try:
        if pedido.status == ESTADO_CONFIRMADO:
            _confirmar(db, pedido, nuevos_items, "Stock insuficiente para editar: {nombre}.")

        pedido.customer = payload.customer
        pedido.date = payload.date
        pedido.channel = payload.channel
        pedido.notes = payload.notes
        pedido.items.clear()
        db.flush()
        pedido.items.extend(nuevos_items)
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(pedido)
    return _serializar(pedido)


def _faltantes(db: Session, items: list[PedidoItem], excluir_pedido_id: int | None = None) -> list[dict]:
    """HU015 y HU017: disponible = En Almacén − reservado; devuelve el detalle de cada faltante."""
    necesario = necesidades(items)
    reservado = stock_reservado(db, excluir_pedido_id=excluir_pedido_id)
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
    return faltantes


@router.post("/validar-stock")
def validar_disponibilidad_stock(
    payload: PedidoCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """HU015 y HU017: Validar disponibilidad de stock y devolver alerta detallada de faltantes (HTTP 409)."""
    faltantes = _faltantes(db, _construir_items(db, payload.items))
    if faltantes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": " | ".join(f["mensaje"] for f in faltantes),
                "faltantes": faltantes,
            },
        )
    return {"ok": True, "message": "Stock suficiente para confirmar el pedido."}
