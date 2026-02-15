import os
from pathlib import Path
import tomllib
from psycopg import connect
from psycopg.rows import dict_row
from psycopg.types.json import Json


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
                        SELECT id
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

                latency_ms = metadata.get("latency_ms") if isinstance(metadata, dict) else None
                model_used = metadata.get("model") if isinstance(metadata, dict) else None
                recordia_hash = metadata.get("recordia_hash") if isinstance(metadata, dict) else None
                
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