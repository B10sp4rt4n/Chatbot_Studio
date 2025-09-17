import sqlite3
import json

DB_FILE = "chatbot_studio.sqlite"

def get_db():
    """Obtiene una conexión a la base de datos."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row # Permite acceder a las columnas por nombre
    return conn

def init_db(schema_path="schema.sql"):
    """Inicializa la base de datos usando el schema."""
    with get_db() as conn:
        with open(schema_path, 'r') as f:
            conn.executescript(f.read())
        conn.commit()
    print("Base de datos inicializada.")

def dict_from_row(row):
    """Convierte un objeto sqlite3.Row a un diccionario."""
    return dict(row) if row else None

# --- Proyectos ---

def create_project(name, description):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO projects (name, description) VALUES (?, ?)",
            (name, description)
        )
        project_id = cursor.lastrowid
        conn.commit()
        new_project = cursor.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict_from_row(new_project)

def list_projects():
    with get_db() as conn:
        rows = conn.cursor().execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
        return [dict_from_row(row) for row in rows]

# --- Sesiones/Conversaciones ---

def create_session(project_id, title):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sessions (project_id, title) VALUES (?, ?)",
            (project_id, title)
        )
        session_id = cursor.lastrowid
        conn.commit()
        new_session = cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict_from_row(new_session)

def list_sessions(project_id):
    with get_db() as conn:
        rows = conn.cursor().execute(
            "SELECT * FROM sessions WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,)
        ).fetchall()
        return [dict_from_row(row) for row in rows]

# --- Mensajes ---

def add_message(session_id, role, content, metadata=None):
    metadata_json = json.dumps(metadata) if metadata else None
    with get_db() as conn:
        conn.cursor().execute(
            "INSERT INTO messages (session_id, role, content, metadata) VALUES (?, ?, ?, ?)",
            (session_id, role, content, metadata_json)
        )
        conn.commit()

def get_messages(session_id):
    with get_db() as conn:
        rows = conn.cursor().execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,)
        ).fetchall()
        return [dict_from_row(row) for row in rows]