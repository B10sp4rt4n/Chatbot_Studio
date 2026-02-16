import os
import hashlib
import json
from datetime import datetime
from pathlib import Path
import tomllib
from psycopg import connect
from psycopg.rows import dict_row
from psycopg.types.json import Json


# =========================
# Recordia: Hash generation
# =========================
def generate_recordia_hash(prompt_text: str, response_text: str, metadata: dict = None) -> str:
    """
    Genera hash SHA-256 forense de la interacción completa.
    
    Incluye:
    - prompt_text: Input del usuario
    - response_text: Output del modelo
    - metadata: model_used, latency_ms, status, timestamp
    
    Este hash es único e inmutable para trazabilidad Recordia.
    """
    # Construir payload canónico
    payload = {
        "prompt": prompt_text,
        "response": response_text,
        "model": metadata.get("model") if metadata else None,
        "latency_ms": metadata.get("latency_ms") if metadata else None,
        "status": metadata.get("status") if metadata else "complete",
        "timestamp": metadata.get("timestamp") if metadata else None
    }
    
    # Serializar de forma determinística (ordenado por keys)
    canonical_json = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    
    # Hash SHA-256
    return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()


def generate_hash(data: str) -> str:
    """Alias simple para generar hash SHA-256 (compatibilidad API Recordia)."""
    return hashlib.sha256((data or "").encode("utf-8")).hexdigest()


def _read_database_url_from_secrets_file():
    secrets_path = Path(".streamlit/secrets.toml")
    if not secrets_path.exists():
        return ""
    try:
        with secrets_path.open("rb") as f:
            data = tomllib.load(f)
        return str(data.get("DATABASE_URL", "")).strip()
    except Exception:
        return ""


def get_database_url():
    env_url = os.getenv("DATABASE_URL", "").strip()
    if env_url:
        return env_url
    return _read_database_url_from_secrets_file()


def get_db():
    """Obtiene conexión PostgreSQL (Neon) usando DATABASE_URL."""
    database_url = get_database_url()
    if not database_url:
        raise RuntimeError("Falta DATABASE_URL. Configura la cadena de conexión de Neon PostgreSQL.")
    return connect(database_url, row_factory=dict_row)


def init_db(schema_path="schema.sql"):
    """Inicializa la base de datos usando el schema SQL."""
    with get_db() as conn:
        with conn.cursor() as cur:
            with open(schema_path, "r", encoding="utf-8") as f:
                cur.execute(f.read())
            cur.execute("ALTER TABLE responses ADD COLUMN IF NOT EXISTS blockchain_tx_hash TEXT")
            cur.execute("ALTER TABLE responses ADD COLUMN IF NOT EXISTS blockchain_network TEXT")
            cur.execute("ALTER TABLE responses ADD COLUMN IF NOT EXISTS anchored_at TIMESTAMPTZ")
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_responses_recordia_hash
                ON responses (recordia_hash)
                WHERE recordia_hash IS NOT NULL
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_responses_blockchain_tx_hash
                ON responses (blockchain_tx_hash)
                WHERE blockchain_tx_hash IS NOT NULL
                """
            )
            cur.execute(
                """
                INSERT INTO tenants (name)
                SELECT 'default'
                WHERE NOT EXISTS (
                    SELECT 1 FROM tenants WHERE name = 'default'
                )
                """
            )
        conn.commit()


def create_tenant(name):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH existing AS (
                    SELECT id, name, created_at
                    FROM tenants
                    WHERE name = %s
                ), inserted AS (
                    INSERT INTO tenants (name)
                    SELECT %s
                    WHERE NOT EXISTS (SELECT 1 FROM existing)
                    RETURNING id, name, created_at
                )
                SELECT id, name, created_at FROM inserted
                UNION ALL
                SELECT id, name, created_at FROM existing
                LIMIT 1
                """,
                (name, name),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def list_tenants():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, created_at FROM tenants ORDER BY id ASC")
            return cur.fetchall()


def create_project(tenant_id, name, description):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO projects (tenant_id, name, description)
                VALUES (%s, %s, %s)
                RETURNING id, tenant_id, name, description, created_at
                """,
                (tenant_id, name, description),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def list_projects(tenant_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tenant_id, name, description, created_at
                FROM projects
                WHERE tenant_id = %s
                ORDER BY created_at DESC
                """,
                (tenant_id,),
            )
            return cur.fetchall()


def create_session(tenant_id, project_id, title):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sessions (tenant_id, project_id, title)
                VALUES (%s, %s, %s)
                RETURNING id, tenant_id, project_id, title, created_at
                """,
                (tenant_id, project_id, title),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def list_sessions(tenant_id, project_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tenant_id, project_id, title, created_at
                FROM sessions
                WHERE tenant_id = %s AND project_id = %s
                ORDER BY created_at DESC
                """,
                (tenant_id, project_id),
            )
            return cur.fetchall()


def add_message(tenant_id, session_id, role, content, metadata=None):
    payload = Json(metadata) if metadata is not None else None
    with get_db() as conn:
        with conn.cursor() as cur:
            if role in ("system", "user"):
                cur.execute(
                    """
                    INSERT INTO prompts (tenant_id, session_id, actor, prompt_text, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (tenant_id, session_id, role, content, payload),
                )
                row = cur.fetchone()
                message_id = row["id"]
            elif role == "assistant":
                prompt_id = metadata.get("prompt_id") if isinstance(metadata, dict) else None
                if not prompt_id:
                    cur.execute(
                        """
                        SELECT id, prompt_text
                        FROM prompts
                        WHERE tenant_id = %s AND session_id = %s
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        (tenant_id, session_id),
                    )
                    prompt_row = cur.fetchone()
                    if not prompt_row:
                        raise ValueError("No existe prompt previo para asociar la respuesta.")
                    prompt_id = prompt_row["id"]
                    prompt_text = prompt_row["prompt_text"]
                else:
                    # Si se provee prompt_id, obtener el texto
                    cur.execute(
                        """
                        SELECT prompt_text
                        FROM prompts
                        WHERE id = %s AND tenant_id = %s
                        """,
                        (prompt_id, tenant_id),
                    )
                    prompt_row = cur.fetchone()
                    if not prompt_row:
                        raise ValueError("Prompt no encontrado.")
                    prompt_text = prompt_row["prompt_text"]

                latency_ms = metadata.get("latency_ms") if isinstance(metadata, dict) else None
                model_used = metadata.get("model") if isinstance(metadata, dict) else None
                
                # Determinar status basado en metadata
                status = "complete"  # default
                if isinstance(metadata, dict):
                    if not metadata.get("is_complete", True):
                        finish_reason = metadata.get("finish_reason", "")
                        if finish_reason == "length":
                            status = "truncated"
                        elif finish_reason == "error" or metadata.get("error"):
                            status = "error"
                        else:
                            status = "partial"
                
                # ===== RECORDIA: Generar hash forense de la interacción =====
                recordia_metadata = {
                    "model": model_used,
                    "latency_ms": latency_ms,
                    "status": status,
                    "timestamp": None  # Se genera automáticamente en BD
                }
                recordia_hash = generate_recordia_hash(prompt_text, content, recordia_metadata)

                cur.execute(
                    """
                    INSERT INTO responses (
                        tenant_id, prompt_id, session_id, response_text,
                        status, latency_ms, model_used, recordia_hash, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (tenant_id, prompt_id, session_id, content, status, latency_ms, model_used, recordia_hash, payload),
                )
                row = cur.fetchone()
                message_id = row["id"]
            else:
                raise ValueError("Rol inválido. Usa: system, user o assistant.")
        conn.commit()
    return message_id


def log_interaction_to_recordia(tenant_id, project_id, session_id, prompt, response, latency, model_used):
    """
    Registra una interacción completa en Recordia validando alcance tenant/project/session.

    Flujo:
    1) Inserta prompt de usuario
    2) Inserta respuesta asistente (genera hash forense automáticamente)
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM sessions
                WHERE id = %s AND tenant_id = %s AND project_id = %s
                """,
                (session_id, tenant_id, project_id),
            )
            session_row = cur.fetchone()
            if not session_row:
                raise ValueError("Sesión inválida para tenant/proyecto.")

    add_message(tenant_id, session_id, "user", prompt, {"kind": "recordia_prompt"})
    response_id = add_message(
        tenant_id,
        session_id,
        "assistant",
        response,
        {
            "model": model_used,
            "latency_ms": latency,
            "is_complete": True,
            "finish_reason": "stop",
            "source": "recordia",
        },
    )

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT recordia_hash
                FROM responses
                WHERE id = %s AND tenant_id = %s
                """,
                (response_id, tenant_id),
            )
            row = cur.fetchone()
            return {
                "response_id": response_id,
                "recordia_hash": row["recordia_hash"] if row else None,
            }


def get_messages(tenant_id, session_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    actor AS role,
                    prompt_text AS content,
                    NULL AS status,
                    metadata,
                    created_at
                FROM prompts
                WHERE tenant_id = %s AND session_id = %s

                UNION ALL

                SELECT
                    id,
                    'assistant' AS role,
                    response_text AS content,
                    status,
                    metadata,
                    created_at
                FROM responses
                WHERE tenant_id = %s AND session_id = %s

                ORDER BY created_at ASC
                """,
                (tenant_id, session_id, tenant_id, session_id),
            )
            return cur.fetchall()


def get_conversation_context(tenant_id: int, session_id: int, limit_messages: int = 30):
    """
    Recupera historial de conversación para contexto del modelo.

    Seguridad:
    - Filtra estrictamente por tenant_id y session_id.

    Args:
        tenant_id: Tenant activo
        session_id: Sesión activa
        limit_messages: Máximo de mensajes a devolver (últimos N)
    """
    safe_limit = max(1, min(int(limit_messages), 200))

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, content, created_at
                FROM (
                    SELECT
                        actor AS role,
                        prompt_text AS content,
                        created_at
                    FROM prompts
                    WHERE tenant_id = %s AND session_id = %s

                    UNION ALL

                    SELECT
                        'assistant' AS role,
                        response_text AS content,
                        created_at
                    FROM responses
                    WHERE tenant_id = %s AND session_id = %s
                ) AS all_messages
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (tenant_id, session_id, tenant_id, session_id, safe_limit),
            )
            rows = cur.fetchall()

    rows.reverse()
    return rows


# =========================
# Recordia: Funciones forenses
# =========================

def get_interaction_by_hash(recordia_hash: str):
    """
    Recupera una interacción completa por su hash Recordia.
    
    Útil para:
    - Auditoría forense
    - Verificación de integridad
    - Búsqueda de interacciones específicas
    
    Returns: dict con prompt, response y metadata completa
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    r.id AS response_id,
                    r.tenant_id,
                    r.session_id,
                    r.prompt_id,
                    r.response_text,
                    r.status,
                    r.latency_ms,
                    r.model_used,
                    r.recordia_hash,
                    r.created_at AS response_timestamp,
                    p.prompt_text,
                    p.actor AS prompt_actor,
                    p.created_at AS prompt_timestamp,
                    s.title AS session_title,
                    pr.name AS project_name,
                    t.name AS tenant_name
                FROM responses r
                JOIN prompts p ON r.prompt_id = p.id
                JOIN sessions s ON r.session_id = s.id
                JOIN projects pr ON s.project_id = pr.id
                JOIN tenants t ON r.tenant_id = t.id
                WHERE r.recordia_hash = %s
                """,
                (recordia_hash,),
            )
            return cur.fetchone()


def verify_interaction_integrity(tenant_id: int, response_id: int) -> dict:
    """
    Verifica la integridad de una interacción recalculando su hash.
    
    Returns:
        {
            "is_valid": bool,
            "stored_hash": str,
            "calculated_hash": str,
            "status": str
        }
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    r.recordia_hash,
                    r.response_text,
                    r.status,
                    r.latency_ms,
                    r.model_used,
                    p.prompt_text
                FROM responses r
                JOIN prompts p ON r.prompt_id = p.id
                WHERE r.id = %s AND r.tenant_id = %s
                """,
                (response_id, tenant_id),
            )
            row = cur.fetchone()
            
            if not row or not row["recordia_hash"]:
                return {
                    "is_valid": False,
                    "error": "Response not found or hash not generated"
                }
            
            # Recalcular hash
            metadata = {
                "model": row["model_used"],
                "latency_ms": row["latency_ms"],
                "status": row["status"],
                "timestamp": None
            }
            calculated_hash = generate_recordia_hash(
                row["prompt_text"], 
                row["response_text"], 
                metadata
            )
            
            return {
                "is_valid": calculated_hash == row["recordia_hash"],
                "stored_hash": row["recordia_hash"],
                "calculated_hash": calculated_hash,
                "status": row["status"]
            }


def get_recordia_audit_log(tenant_id: int, limit: int = 100):
    """
    Obtiene log de auditoría Recordia con todas las interacciones rastreables.
    
    Args:
        tenant_id: ID del tenant
        limit: Número máximo de registros (default: 100)
    
    Returns: Lista de interacciones con hash Recordia
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    r.id,
                    r.recordia_hash,
                    r.status,
                    r.model_used,
                    r.latency_ms,
                    r.created_at,
                    s.title AS session_title,
                    pr.name AS project_name,
                    LENGTH(p.prompt_text) AS prompt_length,
                    LENGTH(r.response_text) AS response_length
                FROM responses r
                JOIN prompts p ON r.prompt_id = p.id
                JOIN sessions s ON r.session_id = s.id
                JOIN projects pr ON s.project_id = pr.id
                WHERE r.tenant_id = %s 
                  AND r.recordia_hash IS NOT NULL
                ORDER BY r.created_at DESC
                LIMIT %s
                """,
                (tenant_id, limit),
            )
            return cur.fetchall()


def get_recordia_audit_log_filtered(
    tenant_id: int,
    project_id: int | None = None,
    session_id: int | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: int = 500,
):
    """Log de auditoría Recordia con filtros por tenant/proyecto/sesión/fecha."""
    query = """
        SELECT
            r.id,
            r.prompt_id,
            r.session_id,
            s.project_id,
            p.prompt_text,
            r.response_text,
            r.status,
            r.model_used,
            r.latency_ms,
            r.recordia_hash,
            r.blockchain_tx_hash,
            r.blockchain_network,
            r.anchored_at,
            r.created_at,
            s.title AS session_title,
            pr.name AS project_name
        FROM responses r
        JOIN prompts p ON p.id = r.prompt_id
        JOIN sessions s ON s.id = r.session_id
        JOIN projects pr ON pr.id = s.project_id
        WHERE r.tenant_id = %s
          AND p.tenant_id = %s
          AND s.tenant_id = %s
          AND pr.tenant_id = %s
    """
    params = [tenant_id, tenant_id, tenant_id, tenant_id]

    if project_id is not None:
        query += " AND s.project_id = %s"
        params.append(project_id)
    if session_id is not None:
        query += " AND r.session_id = %s"
        params.append(session_id)
    if start_at is not None:
        query += " AND r.created_at >= %s"
        params.append(start_at)
    if end_at is not None:
        query += " AND r.created_at <= %s"
        params.append(end_at)

    query += " ORDER BY r.created_at DESC LIMIT %s"
    params.append(limit)

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()


def verify_recordia_hash(tenant_id: int, project_id: int, session_id: int, recordia_hash: str) -> dict:
    """Verifica hash bajo alcance estricto de tenant/proyecto/sesión."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    r.id,
                    r.recordia_hash,
                    r.status,
                    r.model_used,
                    r.latency_ms,
                    p.prompt_text,
                    r.response_text
                FROM responses r
                JOIN prompts p ON p.id = r.prompt_id
                JOIN sessions s ON s.id = r.session_id
                WHERE r.tenant_id = %s
                  AND p.tenant_id = %s
                  AND s.tenant_id = %s
                  AND s.project_id = %s
                  AND r.session_id = %s
                  AND r.recordia_hash = %s
                LIMIT 1
                """,
                (tenant_id, tenant_id, tenant_id, project_id, session_id, recordia_hash),
            )
            row = cur.fetchone()
            if not row:
                return {"valid": False, "reason": "hash_not_found_in_scope"}

            recalculated = generate_recordia_hash(
                row["prompt_text"],
                row["response_text"],
                {
                    "model": row["model_used"],
                    "latency_ms": row["latency_ms"],
                    "status": row["status"],
                    "timestamp": None,
                },
            )
            return {
                "valid": recalculated == row["recordia_hash"],
                "response_id": row["id"],
                "stored_hash": row["recordia_hash"],
                "calculated_hash": recalculated,
            }


def set_blockchain_anchor(tenant_id: int, response_id: int, tx_hash: str, network: str):
    """Guarda evidencia de anclaje blockchain en la respuesta (aislada por tenant)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE responses
                SET blockchain_tx_hash = %s,
                    blockchain_network = %s,
                    anchored_at = NOW()
                WHERE id = %s AND tenant_id = %s
                RETURNING id
                """,
                (tx_hash, network, response_id, tenant_id),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("No se pudo registrar anclaje blockchain para este tenant/response_id.")
        conn.commit()