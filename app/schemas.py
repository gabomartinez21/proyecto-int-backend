from datetime import datetime, date
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import CategoriaProducto, TipoMovimiento, UnidadMedida, UserRole


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=72)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str
    role: UserRole


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole


# --- Schemas de Insumos y Stock (HU005, HU006, HU007, HU008) ---

class InsumoCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    unit: UnidadMedida
    minimum: float = Field(ge=0, le=1e9, default=0.0)
    cost: float = Field(gt=0, le=1e9)

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("El nombre del insumo debe tener al menos 2 caracteres")
        return v


class InsumoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    unit: UnidadMedida
    stock: float
    minimum: float
    cost: float


class StockMovementCreate(BaseModel):
    kind: TipoMovimiento
    quantity: float = Field(gt=0, le=1e9)
    note: str = Field(min_length=3, max_length=150)

    @field_validator("note")
    @classmethod
    def clean_note(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("El motivo es obligatorio")
        return v


class MovimientoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    insumo_id: int
    ingredient: str
    quantity: float
    unit: str
    note: str
    date: datetime


# --- Schemas de Productos y Recetas (HU001 - HU004) ---

class ProductoCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    category: CategoriaProducto
    price: float = Field(ge=0, le=1e9)
    description: str = Field(default="", max_length=500)

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("El nombre del producto es obligatorio")
        return v

    @field_validator("description")
    @classmethod
    def clean_description(cls, v: str) -> str:
        return v.strip()


class RecetaItemIn(BaseModel):
    ingredientId: int
    quantity: float = Field(gt=0, le=1e9)


class RecetaUpdate(BaseModel):
    recipe: list[RecetaItemIn]


class ProductoOut(BaseModel):
    id: int
    name: str
    category: CategoriaProducto
    price: float
    description: str
    recipe: list[RecetaItemIn]


# --- Schemas de Pedidos (Sprint 2 y Sprint 3: HU009 - HU017) ---

class PedidoItemCreate(BaseModel):
    productId: int
    quantity: int = Field(ge=1, le=10_000)


class _PedidoBase(BaseModel):
    customer: str = Field(max_length=150)
    date: str
    channel: str
    notes: str = Field(default="", max_length=500)
    items: list[PedidoItemCreate]

    @field_validator("customer")
    @classmethod
    def clean_customer(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("El cliente debe tener al menos 3 caracteres")
        return v

    @field_validator("notes")
    @classmethod
    def clean_notes(cls, v: str) -> str:
        return v.strip()

    @field_validator("date")
    @classmethod
    def validar_formato_fecha(cls, v: str) -> str:
        try:
            return datetime.strptime(v, "%Y-%m-%d").date().isoformat()
        except ValueError:
            raise ValueError("Formato de fecha inválido")


class PedidoCreate(_PedidoBase):
    @field_validator("date")
    @classmethod
    def validar_fecha_futura(cls, v: str) -> str:
        if v < date.today().isoformat():
            raise ValueError("La fecha de entrega no puede ser anterior a hoy.")
        return v


class PedidoUpdate(_PedidoBase):
    """HU013: Editar pedido antes de preparación.

    La fecha pasada se valida en el router: se permite conservar la fecha original del pedido.
    """


class PedidoStatusUpdate(BaseModel):
    status: str
    # HU012: obligatorio al marcar Entregado (receptor confirmado)
    receiver: str | None = Field(default=None, max_length=150)
    # HU012: obligatorio al marcar Entregado (receptor confirmado)
    receiver: str | None = Field(default=None, max_length=150)


# --- Schemas de Compras (Sprint 3: HU021, HU023) ---

class CompraConfirmarItem(BaseModel):
    """HU023: Ingreso rápido de insumos comprados."""
    insumo_id: int
    quantity: float = Field(gt=0, le=1e9)
    note: str = Field(default="Compra desde lista semanal", max_length=150)
