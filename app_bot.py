import os, re, json, time
import pandas as pd
import streamlit as st

# --- DB helpers (tu módulo existente)
from db import (
    init_db, create_tenant, list_tenants, create_project, list_projects, create_session, list_sessions,
    add_message, get_messages
)

# =========================
# Config & Helpers
# =========================
st.set_page_config(page_title="Chatbot Studio Personal", page_icon="🤖", layout="wide")
st.title("🤖 Chatbot Studio Personal — Proyectos y Prompts")

# ---- DB init ----
try:
    init_db("schema.sql")
except Exception as e:
    st.error(f"No se pudo inicializar la base PostgreSQL/Neon: {e}")
    st.stop()

# ---- Model utilities ----
MODEL_OPTIONS = [
    "gpt-4o",        # 4o multimodal
    "gpt-4o-mini",   # 4o económico / rápido
    "o1-preview",    # reasoning
    "o1-mini"        # reasoning económico
]
REASONING_MODELS = {"o1-preview", "o1-mini"}

ALIAS_MAP = {
    "gpt 4": "gpt-4o",
    "gpt-4": "gpt-4o",
    "gpt 4.0": "gpt-4o",
    "gpt-4.0": "gpt-4o",
    "4o": "gpt-4o",
    "4o mini": "gpt-4o-mini",
    "gpt4o": "gpt-4o",
    "gpt 4o": "gpt-4o",
}

def normalize_model(name: str) -> str:
    if not name:
        return ""
    key = name.strip().lower()
    key = key.replace("_", "-").replace("—", "-")
    key = re.sub(r"\s+", " ", key)
    if key in ALIAS_MAP:
        return ALIAS_MAP[key]
    # heurística: cambia espacios por guiones si parece familia gpt/o1
    key2 = key.replace(" ", "-")
    # si alguien pone 'gpt-4.0' lo mapeamos a gpt-4o
    if key2 in ("gpt-4.0", "gpt4.0", "gpt-4-0"):
        return "gpt-4o"
    # validar que el modelo parece válido (empieza con gpt- o o1-)
    if not (key2.startswith("gpt-") or key2.startswith("o1-") or key2.startswith("o1")):
        return "gpt-4o"  # fallback por defecto
    return key2

def model_supports_reasoning(model: str) -> bool:
    m = (model or "").strip().lower()
    return any(m.startswith(pref) for pref in REASONING_MODELS)

def sanitize(txt: str) -> str:
    # Emails -> [REDACTED_EMAIL]; Teléfonos -> [REDACTED_PHONE]
    txt = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", txt)
    txt = re.sub(r"\b\+?\d[\d\s\-().]{7,}\b", "[REDACTED_PHONE]", txt)
    return txt

# =========================
# Sidebar Config
# =========================
st.sidebar.header("Configuración")

st.sidebar.subheader("Tenant")
new_tenant_name = st.sidebar.text_input("Nuevo tenant (opcional)", value="")
if st.sidebar.button("Crear tenant") and new_tenant_name.strip():
    try:
        create_tenant(new_tenant_name.strip())
        st.sidebar.success("Tenant creado")
    except Exception as e:
        st.sidebar.error(f"No se pudo crear tenant: {e}")

try:
    tenants = list_tenants()
except Exception as e:
    st.error(f"No se pudieron cargar tenants: {e}")
    st.stop()

if not tenants:
    t = create_tenant("default")
    tenants = [t]

tenant_index = st.sidebar.selectbox(
    "Tenant activo",
    options=list(range(len(tenants))),
    format_func=lambda i: f"{i + 1} — {tenants[i]['name']}"
)
tenant_id = int(tenants[tenant_index]["id"])

api_key = os.environ.get("OPENAI_API_KEY", "")
if not api_key:
    api_key = st.secrets.get("OPENAI_API_KEY", "")

model_choice = st.sidebar.selectbox("Modelo (sugerido)", options=MODEL_OPTIONS, index=0)
model_custom = st.sidebar.text_input("Modelo personalizado (opcional)", value="")
model = normalize_model(model_custom) if model_custom.strip() else model_choice

temperature = st.sidebar.slider("Creatividad (temperature)", 0.0, 1.0, 0.2, 0.05)
reasoning_effort = st.sidebar.select_slider(
    "Esfuerzo de razonamiento (solo modelos o1*)",
    options=["low","medium","high"],
    value="medium"
)

# Información contextual en la sidebar
if not api_key:
    st.sidebar.warning("Falta OpenAI API Key. Configúrala en .streamlit/secrets.toml o OPENAI_API_KEY.")

if model_supports_reasoning(model):
    st.sidebar.info(f"El modelo **{model}** soporta `reasoning.effort`.")
else:
    st.sidebar.caption(f"El modelo **{model}** no soporta `reasoning.effort`; se omitirá automáticamente.")

st.sidebar.caption("Configuración recomendada: `.streamlit/secrets.toml`.")

# =========================
# Proyectos
# =========================
st.subheader("1) Proyectos")
with st.form("new_project"):
    name = st.text_input("Nombre del proyecto", placeholder="Mi chatbot personal / Asistente ventas / Soporte interno")
    desc = st.text_area("Descripción", placeholder="Objetivo, tono, público, límites…")
    submitted = st.form_submit_button("Crear proyecto")
    if submitted and name:
        p = create_project(tenant_id, name, desc)
        st.success(f"Proyecto creado: {p['name']}")

projects = list_projects(tenant_id)
if not projects:
    st.info("Crea tu primer proyecto arriba.")
    st.stop()

project_index = st.selectbox(
    "Selecciona proyecto",
    options=list(range(len(projects))),
    format_func=lambda i: f"{i + 1} — {projects[i]['name']}"
)
project_id = int(projects[project_index]["id"])

# =========================
# Conversaciones
# =========================
st.subheader("2) Conversaciones")
with st.form("new_session"):
    title = st.text_input("Título de la conversación", placeholder="Exploración inicial / Pruebas de tono / FAQs")
    s_sub = st.form_submit_button("Crear conversación")
    if s_sub and title:
        s = create_session(tenant_id, project_id, title)
        st.success(f"Creada conversación: {s['title']}")

sessions = list_sessions(tenant_id, project_id)
if not sessions:
    st.info("Crea una conversación arriba.")
    st.stop()

session_index = st.selectbox(
    "Selecciona conversación",
    options=list(range(len(sessions))),
    format_func=lambda i: f"{i + 1} — {sessions[i]['title']}"
)
session_id = int(sessions[session_index]["id"])

# =========================
# Prompt box
# =========================
st.subheader("3) Prompt")
sys_role = st.text_area("System (opcional)", placeholder="Define reglas del chatbot, tono o políticas.", height=80)
user_prompt = st.text_area("User", placeholder="Escribe tu prompt para este chatbot.", height=160)

colA, colB, colC = st.columns(3)
anonymize = colA.checkbox("Anonimizar (emails/teléfonos)", value=True)
save_only = colB.checkbox("Solo guardar (no enviar a LLM)", value=False)
show_raw = colC.checkbox("Mostrar respuesta RAW", value=False)

def build_input(sys_role: str, user_text: str) -> str:
    if sys_role.strip():
        return f"SYSTEM:\n{sys_role.strip()}\n\nUSER:\n{user_text.strip()}"
    return user_text.strip()

if st.button("➤ Enviar / Guardar turno"):
    # Guardar system si viene
    if sys_role.strip():
        add_message(tenant_id, session_id, "system", sys_role, {"kind": "role"})

    text_to_send = sanitize(user_prompt) if anonymize else user_prompt
    add_message(tenant_id, session_id, "user", text_to_send, {"temperature": temperature, "reasoning_effort": reasoning_effort})

    if save_only:
        st.success("Turno guardado (no se llamó al LLM).")
    else:
        if not api_key:
            st.error("Falta OpenAI API Key. Configúrala en .streamlit/secrets.toml con OPENAI_API_KEY.")
        elif not model:
            st.error("Debes seleccionar o escribir un modelo válido.")
        else:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=api_key)

                full_input = build_input(sys_role, text_to_send)
                req_kwargs = {
                    "model": model,
                    "input": full_input,
                    "temperature": float(temperature),
                    "stream": True,  # Habilitar streaming
                }
                # Modo seguro: solo enviamos reasoning si el modelo lo soporta
                if model_supports_reasoning(model):
                    req_kwargs["reasoning"] = {"effort": reasoning_effort}

                t0 = time.time()
                stream = client.responses.create(**req_kwargs)
                
                # Contenedor para la respuesta en vivo
                response_container = st.empty()
                status_container = st.empty()
                
                assistant_text = ""
                finish_reason = None
                error_occurred = False
                error_message = ""
                
                try:
                    status_container.info("⏳ Generando respuesta...")
                    for chunk in stream:
                        # Los eventos de tipo 'response.output_text.delta' contienen fragmentos de texto
                        if chunk.type == 'response.output_text.delta':
                            if hasattr(chunk, 'delta') and chunk.delta:
                                assistant_text += chunk.delta
                                response_container.markdown(f"**Respuesta:**\n\n{assistant_text}")
                        
                        # Evento final con respuesta completa
                        elif chunk.type == 'response.done':
                            if hasattr(chunk, 'response'):
                                resp = chunk.response
                                if hasattr(resp, 'status'):
                                    if resp.status == 'completed':
                                        finish_reason = 'stop'
                                    elif resp.status == 'incomplete':
                                        finish_reason = 'length'
                                    else:
                                        finish_reason = resp.status
                    
                    latency_ms = int((time.time() - t0) * 1000)
                    
                    # Determinar estado de completitud
                    if finish_reason == "stop":
                        status_icon = "✅"
                        status_text = "Respuesta completa"
                        is_complete = True
                    elif finish_reason == "length":
                        status_icon = "⚠️"
                        status_text = "Respuesta TRUNCADA (alcanzó límite de tokens)"
                        is_complete = False
                    elif finish_reason:
                        status_icon = "⚠️"
                        status_text = f"Respuesta terminó con: {finish_reason}"
                        is_complete = False
                    else:
                        status_icon = "✅"
                        status_text = "Respuesta recibida"
                        is_complete = True
                    
                except Exception as stream_error:
                    error_occurred = True
                    error_message = str(stream_error)
                    latency_ms = int((time.time() - t0) * 1000)
                    status_icon = "❌"
                    status_text = f"ERROR durante streaming: {error_message}"
                    is_complete = False
                    finish_reason = "error"
                
                # Guardar siempre lo que llegó (aunque sea parcial)
                if assistant_text:
                    metadata = {
                        "model": model,
                        "latency_ms": latency_ms,
                        "finish_reason": finish_reason,
                        "is_complete": is_complete,
                        "streamed": True
                    }
                    if error_occurred:
                        metadata["error"] = error_message
                    
                    add_message(tenant_id, session_id, "assistant", assistant_text, metadata)
                    status_container.success(f"{status_icon} {status_text} — {latency_ms} ms — Guardado en BD")
                else:
                    # No llegó nada de contenido
                    status_container.error(f"❌ No se recibió contenido: {error_message if error_occurred else 'Stream vacío'}")
                
                if show_raw and assistant_text:
                    with st.expander("Metadata de la respuesta"):
                        st.json({
                            "text_length": len(assistant_text),
                            "latency_ms": latency_ms,
                            "finish_reason": finish_reason,
                            "is_complete": is_complete,
                            "error": error_message if error_occurred else None
                        })
                        
            except Exception as e:
                st.error(f"❌ Error al iniciar streaming: {e}")

# =========================
# Historial
# =========================
st.subheader("4) Historial")

# Filtro para el historial
col_filter1, col_filter2 = st.columns([2, 1])
with col_filter1:
    show_all = st.checkbox("Mostrar todos los mensajes (incluye incompletos/errores)", value=True)
with col_filter2:
    show_status_column = st.checkbox("Mostrar columna de estado", value=True)

rows = get_messages(tenant_id, session_id)
if rows:
    # Filtrar si es necesario
    if not show_all:
        rows = [r for r in rows if r["role"] != "assistant" or r.get("status") == "complete"]
    
    # Función para icono de status
    def status_icon(role, status):
        if role != "assistant":
            return ""
        if status == "complete":
            return "✅"
        elif status == "truncated":
            return "⚠️ TRUNCADO"
        elif status == "error":
            return "❌ ERROR"
        elif status == "partial":
            return "⚠️ PARCIAL"
        return "❓"
    
    # Construir dataframe
    df_data = []
    for idx, r in enumerate(rows, start=1):
        row_data = {
            "turno": idx,
            "role": r["role"],
            "content": r["content"][:200] + "..." if len(r["content"]) > 200 else r["content"],
        }
        if show_status_column:
            row_data["estado"] = status_icon(r["role"], r.get("status"))
        row_data["created_at"] = r["created_at"]
        df_data.append(row_data)
    
    df = pd.DataFrame(df_data)
    st.dataframe(df, width="stretch", height=320)
    
    # Estadísticas de calidad
    assistant_messages = [r for r in rows if r["role"] == "assistant"]
    if assistant_messages:
        complete_count = sum(1 for r in assistant_messages if r.get("status") == "complete")
        total_assistant = len(assistant_messages)
        st.caption(f"📊 Respuestas completas: **{complete_count}/{total_assistant}** ({int(complete_count/total_assistant*100)}%)")

    # Export JSONL con metadata de status
    col_exp1, col_exp2 = st.columns(2)
    with col_exp1:
        # Export completo con status
        jsonl_full = "\n".join(json.dumps(
            {
                "role": r["role"],
                "content": r["content"],
                "status": r.get("status") if r["role"] == "assistant" else None
            },
            ensure_ascii=False
        ) for r in rows)
        st.download_button(
            "📥 Exportar JSONL completo",
            data=jsonl_full.encode("utf-8"),
            file_name=f"session_{session_id}_full.jsonl",
            mime="application/jsonl"
        )
    
    with col_exp2:
        # Export solo mensajes completos (para referencias limpias)
        complete_rows = [r for r in rows if r["role"] != "assistant" or r.get("status") == "complete"]
        jsonl_clean = "\n".join(json.dumps(
            {"role": r["role"], "content": r["content"]},
            ensure_ascii=False
        ) for r in complete_rows)
        st.download_button(
            "✅ Exportar solo completos",
            data=jsonl_clean.encode("utf-8"),
            file_name=f"session_{session_id}_clean.jsonl",
            mime="application/jsonl"
        )
else:
    st.info("Sin mensajes todavía.")

st.caption("Tip: Usa 'Solo guardar' para preparar prompts sin gastar tokens; luego desmarca para probarlos.")