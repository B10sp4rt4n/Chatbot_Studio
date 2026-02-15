-- Migración: Agregar columna status a tabla responses
-- Ejecuta esto solo UNA VEZ si ya tienes datos existentes

-- Agregar columna status con default 'complete' para datos existentes
ALTER TABLE responses 
ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'complete' 
CHECK (status IN ('complete', 'truncated', 'error', 'partial'));

-- Crear índice para búsquedas eficientes por status
CREATE INDEX IF NOT EXISTS idx_responses_status ON responses (status);

-- Actualizar registros existentes: si tienen metadata con is_complete=false, actualizar status
UPDATE responses
SET status = CASE
    WHEN metadata->>'finish_reason' = 'length' THEN 'truncated'
    WHEN metadata->>'finish_reason' = 'error' OR metadata->>'error' IS NOT NULL THEN 'error'
    WHEN (metadata->>'is_complete')::boolean = false THEN 'partial'
    ELSE 'complete'
END
WHERE metadata IS NOT NULL;
