import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserRole(str, enum.Enum):
    owner = "owner"
    employee = "employee"


class UnidadMedida(str, enum.Enum):
    kg = "kg"
    L = "L"
    unidad = "unidad"


class TipoMovimiento(str, enum.Enum):
    entrada = "entrada"
    salida = "salida"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), default=UserRole.employee
    )
    is_active: Mapped[bool] = mapped_column(default=True)


class Insumo(Base):
    __tablename__ = "insumos"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    unit: Mapped[UnidadMedida] = mapped_column(Enum(UnidadMedida, name="unidad_medida"))
    stock: Mapped[float] = mapped_column(Float, default=0.0)
    minimum: Mapped[float] = mapped_column(Float, default=0.0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)


class MovimientoStock(Base):
    __tablename__ = "movimientos_stock"

    id: Mapped[int] = mapped_column(primary_key=True)
    insumo_id: Mapped[int] = mapped_column(ForeignKey("insumos.id", ondelete="CASCADE"))
    ingredient: Mapped[str] = mapped_column(String(150))
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(String(150))
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Pedido(Base):
    __tablename__ = "pedidos"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[int] = mapped_column(unique=True, index=True)
    customer: Mapped[str] = mapped_column(String(150))
    date: Mapped[str] = mapped_column(String(20))
    channel: Mapped[str] = mapped_column(String(50))
    notes: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(50), default="Pendiente")
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class PedidoItem(Base):
    __tablename__ = "pedido_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id", ondelete="CASCADE"))
    product_id: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(150))
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column()
    # Se guarda como JSON porque la receta puede cambiar en el futuro, pero el pedido mantiene la que tenía
    recipe: Mapped[str] = mapped_column(String(1000))