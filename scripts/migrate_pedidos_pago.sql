-- HU009 / HU012 / HU024: columnas de pago y entrega en pedidos (idempotente).
-- Uso: docker exec -i consolidador-postgres psql -U consolidador -d consolidador < scripts/migrate_pedidos_pago.sql
BEGIN;
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS payment_status VARCHAR(20) NOT NULL DEFAULT 'Pendiente';
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS operation_code VARCHAR(100);
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS payment_proof_url VARCHAR(255);
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS payment_validated_by VARCHAR(50);
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS payment_validated_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS delivery_receiver VARCHAR(150);
UPDATE pedidos SET status = 'Pendiente de pago' WHERE status = 'Pendiente';
COMMIT;
