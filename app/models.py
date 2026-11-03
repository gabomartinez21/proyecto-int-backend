import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

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


class CategoriaProducto(str, enum.Enum):
    viandas = "Viandas"
    postres = "Postres"
    eventos = "Eventos"
    otros = "Otros"


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

    items: Mapped[list["PedidoItem"]] = relationship(
        cascade="all, delete-orphan", order_by="PedidoItem.id"
    )


class PedidoItem(Base):
    __tablename__ = "pedido_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id", ondelete="CASCADE"))
    product_id: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(150))
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column()
    # Copia JSON [{ingredientId, quantity}] de la receta al momento de crear el pedido:
    # si luego cambia la receta del producto, el pedido conserva la que tenía.
    recipe: Mapped[str] = mapped_column(Text)


class Producto(Base):
    __tablename__ = "productos"

    id: Mapped[int] = mapped_column(primary_key=True)
    # La unicidad sin distinguir mayúsculas se valida en el router (func.lower).
    name: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    category: Mapped[CategoriaProducto] = mapped_column(
        Enum(
            CategoriaProducto,
            name="categoria_producto",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    price: Mapped[float] = mapped_column(Float, default=0.0)
    description: Mapped[str] = mapped_column(String(500), default="")

    recipe: Mapped[list["RecetaItem"]] = relationship(
        cascade="all, delete-orphan", order_by="RecetaItem.id"
    )


class RecetaItem(Base):
    __tablename__ = "receta_items"
    __table_args__ = (UniqueConstraint("producto_id", "insumo_id", name="uq_receta_producto_insumo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id", ondelete="CASCADE"))
    insumo_id: Mapped[int] = mapped_column(ForeignKey("insumos.id"))
    quantity: Mapped[float] = mapped_column(Float)
