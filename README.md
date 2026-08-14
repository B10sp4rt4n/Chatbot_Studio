# Chatbot_Studio

Chatbot Studio con soporte multitenant sobre Neon PostgreSQL.

## Governance Event Contract v0.1

La rama de gobierno incorpora un núcleo append-only independiente de la UI existente. Cada paso de la interacción produce un evento con identidad, estampa temporal, secuencia por tenant y hashes SHA-256 encadenados.

Componentes nuevos:

- `chatbot_studio/contracts`: modelos del evento canónico.
- `chatbot_studio/recordia`: canonicalización, sellado y verificación.
- `chatbot_studio/stores`: EventStore SQLite para desarrollo y pruebas.
- `chatbot_studio/api`: API FastAPI v0.1.
- `chatbot_studio/projections.py`: reconstrucción del paquete de interacción.
- `schemas/interaction-event-v0.1.schema.json`: JSON Schema interoperable.
- `docs/event-contract-v0.1.md`: reglas semánticas y temporales.

La preservación HotVault se registra como un nuevo evento `EVIDENCE_VAULTED`; no modifica el registro Recordia ya sellado.

### Ejecutar pruebas del contrato

```bash
python -m unittest discover -v
```

### Generar ejemplos con hashes reales

```bash
python -m examples.v0_1.build_examples
```

### Levantar la API v0.1

```bash
pip install -r requirements-dev.txt
uvicorn chatbot_studio.api.app:app --host 0.0.0.0 --port 8000
```

El EventStore usa `chatbot_studio_events.sqlite3` por defecto. Puede cambiarse con:

```bash
export CHATBOT_STUDIO_EVENT_DB="/ruta/segura/events.sqlite3"
```

> La API v0.1 es para desarrollo local. Aún no autentica al llamador: no debe exponerse como servicio multitenant hasta incorporar identidad y derivar el tenant de esa identidad.

Endpoints iniciales:

- `POST /v1/events`
- `GET /v1/events/{event_id}?tenant_id=...`
- `GET /v1/interactions/{interaction_id}?tenant_id=...`
- `GET /v1/users/{user_id}/usage?tenant_id=...`
- `GET /v1/tenants/{tenant_id}/metrics`
- `POST /v1/tenants/{tenant_id}/verify-chain`

## Requisitos

- Python 3.11+
- Variable `DATABASE_URL` apuntando a Neon (PostgreSQL)
- Variable opcional `OPENAI_API_KEY`

## Configuración rápida

1. Instala dependencias:

```bash
pip install -r requirements.txt
```

2. Exporta variables de entorno:

```bash
export DATABASE_URL="postgresql://USER:PASSWORD@HOST/DB?sslmode=require"
export OPENAI_API_KEY="tu_api_key"
```

Alternativa persistente con Streamlit secrets:

1. Crea `.streamlit/secrets.toml`
2. Define:

```toml
DATABASE_URL="postgresql://USER:PASSWORD@HOST/DB?sslmode=require"
OPENAI_API_KEY="tu_api_key"
```

3. Ejecuta la app:

```bash
streamlit run app_bot.py
```

## Esquema de datos (multitenant)

El proyecto usa estas tablas:

- `tenants`
- `projects` (con `tenant_id`)
- `sessions` (con `tenant_id`, `project_id`)
- `prompts` (con `tenant_id`, `session_id`, `actor`, `metadata`)
- `responses` (con `tenant_id`, `prompt_id`, `session_id`, `status`, `latency_ms`, `model_used`, `recordia_hash`)

Todas las consultas de negocio se filtran por `tenant_id` para aislamiento de datos.

## Control de calidad de respuestas

Cada respuesta del LLM incluye un campo **`status`** que indica su completitud:

| Status | Significado | Icono |
|--------|-------------|-------|
| `complete` | Respuesta generada completamente sin errores | ✅ |
| `truncated` | Cortada por límite de tokens (max_tokens) | ⚠️ TRUNCADO |
| `error` | Error durante generación (red, API, filtros) | ❌ ERROR |
| `partial` | Incompleta por otra razón (conexión cortada) | ⚠️ PARCIAL |

**Ventajas:**
- **Sin ambigüedad**: Siempre sabes si una respuesta es confiable para usar como referencia
- **Filtrado inteligente**: Exporta solo respuestas completas para fine-tuning o documentación
- **Trazabilidad**: Si el streaming falla, se guarda lo que llegó + metadata del error
- **Estadísticas**: Ve el % de respuestas completas vs problemáticas por sesión

**En la UI:**
- Filtra "Mostrar solo completos" para limitar historial a respuestas confiables
- Botón "Exportar solo completos" genera JSONL limpio sin respuestas parciales
- Indicadores visuales (✅⚠️❌) en cada mensaje del historial

## Integración Recordia (Trazabilidad Forense)

**Cada interacción tiene un hash SHA-256 único** que garantiza integridad y trazabilidad:

### Características

- **Hash automático**: Se genera al guardar cada respuesta
- **Contenido hasheado**: prompt + response + modelo + latency + status
- **Inmutable**: Hash único (constraint UNIQUE en BD)
- **Forense**: Permite verificación de integridad posterior

### Funciones de auditoría

```python
from db import get_interaction_by_hash, verify_interaction_integrity, get_recordia_audit_log

# Buscar interacción por hash
interaction = get_interaction_by_hash("e0c2a479e782...")
# Returns: {prompt_text, response_text, model_used, tenant_name, ...}

# Verificar integridad
integrity = verify_interaction_integrity(tenant_id=5, response_id=123)
# Returns: {"is_valid": True, "stored_hash": "...", "calculated_hash": "..."}

# Obtener log de auditoría
audit_log = get_recordia_audit_log(tenant_id=5, limit=100)
# Returns: Lista de interacciones con hash Recordia
```

### Casos de uso

1. **Compliance**: Hash inmutable para auditorías regulatorias
2. **Dispute resolution**: Verificar qué respondió exactamente el bot
3. **Data integrity**: Detectar modificaciones no autorizadas
4. **Forensic analysis**: Búsqueda rápida por hash único

### Verificación manual

```sql
-- Buscar interacción por hash
SELECT * FROM responses WHERE recordia_hash = 'hash_aqui';

-- Contar interacciones rastreables por tenant
SELECT tenant_id, COUNT(*) 
FROM responses 
WHERE recordia_hash IS NOT NULL 
GROUP BY tenant_id;
```

## Webhook de verificación (FastAPI)

Levanta la API para verificación externa de hashes:

```bash
uvicorn recordia_api:app --host 0.0.0.0 --port 8000
```

Endpoint principal:

```bash
POST /verify_hash
{
	"tenant_id": 1,
	"project_id": 2,
	"session_id": 3,
	"hash": "<recordia_hash>"
}
```

## Configuración blockchain (opcional)

En `.streamlit/secrets.toml` (o variables de entorno):

```toml
BLOCKCHAIN_PROVIDER_URL = "https://sepolia.infura.io/v3/<PROJECT_ID>"
BLOCKCHAIN_PRIVATE_KEY = "<private_key_hex>"
BLOCKCHAIN_FROM_ADDRESS = "0x..."
BLOCKCHAIN_NETWORK = "sepolia"
```

Con esto se habilita anclaje on-chain desde la UI de auditoría.
