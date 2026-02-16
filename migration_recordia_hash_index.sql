-- Migración: Agregar índice para recordia_hash
-- Ejecuta esto UNA VEZ si ya tienes datos existentes

-- Crear índice parcial para búsquedas eficientes por hash Recordia
-- (solo indexa filas donde recordia_hash NO es NULL)
CREATE INDEX IF NOT EXISTS idx_responses_recordia_hash 
ON responses (recordia_hash) 
WHERE recordia_hash IS NOT NULL;

-- Comentario: Este índice permite búsquedas forenses rápidas por hash
-- sin indexar todas las filas antiguas que no tienen hash
