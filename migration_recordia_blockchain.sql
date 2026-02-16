-- Migración: agregar soporte de anclaje blockchain para Recordia
-- Ejecutar una sola vez en instalaciones existentes.

ALTER TABLE responses
ADD COLUMN IF NOT EXISTS blockchain_tx_hash TEXT;

ALTER TABLE responses
ADD COLUMN IF NOT EXISTS blockchain_network TEXT;

ALTER TABLE responses
ADD COLUMN IF NOT EXISTS anchored_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_responses_blockchain_tx_hash
ON responses (blockchain_tx_hash)
WHERE blockchain_tx_hash IS NOT NULL;
