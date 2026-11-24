"""Migraciones livianas e idempotentes para bases Postgres ya creadas.

`Base.metadata.create_all` crea tablas nuevas pero no agrega columnas a las existentes,
así que aquí se aplican (una sola vez, con IF NOT EXISTS) los cambios de HU009/HU012/HU024.
"""
from sqlalchemy import text
from sqlalchemy.engine import Engine

PEDIDOS_PAGO_Y_ENTREGA = [
    "ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS payment_status VARCHAR(20) NOT NULL DEFAULT 'Pendiente'",
    "ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS operation_code VARCHAR(100)",
    "ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS payment_proof_url VARCHAR(255)",
    "ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS payment_validated_by VARCHAR(50)",
    "ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS payment_validated_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS delivery_receiver VARCHAR(150)",
    # HU009: el estado inicial pasa de "Pendiente" a "Pendiente de pago".
    "UPDATE pedidos SET status = 'Pendiente de pago' WHERE status = 'Pendiente'",
]


def migrate(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        for statement in PEDIDOS_PAGO_Y_ENTREGA:
            conn.execute(text(statement))
