# Chatbot_Studio

Chatbot Studio con soporte multitenant sobre Neon PostgreSQL.

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
