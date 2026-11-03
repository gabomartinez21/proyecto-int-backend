from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import TipoMovimiento, UnidadMedida, UserRole


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


from typing import Any

class PedidoItemCreate(BaseModel):
    productId: str
    quantity: int

class PedidoCreate(BaseModel):
    customer: str
    date: str
    channel: str
    notes: str = ""
    items: list[PedidoItemCreate]

class PedidoStatusUpdate(BaseModel):
    status: str