import os, re, json, time
import pandas as pd
import streamlit as st

# --- DB helpers (tu módulo existente)
from db import (
    init_db, create_project, list_projects, create_session, list_sessions,
    add_message, get_messages
)

# =========================
# Config & Helpers
# =========================
st.set_page_config(page_title="Chatbot Studio Personal", page_icon="🤖", layout="wide")
st.title("🤖 Chatbot Studio Personal — Proyectos y Prompts")

# ---- DB init (one time) ----
if not os.path.exists("chatbot_studio.sqlite"):
    # asumiendo que tu init_db usa schema.sql para crear tablas
    init_db("schema.sql")

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

api_key = st.sidebar.text_input(
    "OpenAI API Key",
    type="password",
    help="Recomendado: variable de entorno OPENAI_API_KEY."
)
if not api_key:
    api_key = os.environ.get("OPENAI_API_KEY", "")

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
    st.sidebar.warning("Falta OpenAI API Key. Configúrala aquí o en OPENAI_API_KEY.")

if model_supports_reasoning(model):
    st.sidebar.info(f"El modelo **{model}** soporta `reasoning.effort`.")
else:
    st.sidebar.caption(f"El modelo **{model}** no soporta `reasoning.effort`; se omitirá automáticamente.")

st.sidebar.caption("Tip: guarda tu API key en la variable de entorno `OPENAI_API_KEY`.")

# =========================
# Proyectos
# =========================
st.subheader("1) Proyectos")
with st.form("new_project"):
    name = st.text_input("Nombre del proyecto", placeholder="Mi chatbot personal / Asistente ventas / Soporte interno")
    desc = st.text_area("Descripción", placeholder="Objetivo, tono, público, límites…")
    submitted = st.form_submit_button("Crear proyecto")
    if submitted and name:
        p = create_project(name, desc)
        st.success(f"Proyecto creado: {p['name']}")

projects = list_projects()
if not projects:
    st.info("Crea tu primer proyecto arriba.")
    st.stop()

proj_choice = st.selectbox("Selecciona proyecto", [f"{p['id']} — {p['name']}" for p in projects])
project_id = int(proj_choice.split(" — ")[0])

# =========================
# Conversaciones
# =========================
st.subheader("2) Conversaciones")
with st.form("new_session"):
    title = st.text_input("Título de la conversación", placeholder="Exploración inicial / Pruebas de tono / FAQs")
    s_sub = st.form_submit_button("Crear conversación")
    if s_sub and title:
        s = create_session(project_id, title)
        st.success(f"Creada conversación: {s['title']} (id {s['id']})")

sessions = list_sessions(project_id)
if not sessions:
    st.info("Crea una conversación arriba.")
    st.stop()

sess_choice = st.selectbox("Selecciona conversación", [f"{s['id']} — {s['title']}" for s in sessions])
session_id = int(sess_choice.split(" — ")[0])

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
        add_message(session_id, "system", sys_role, {"kind": "role"})

    text_to_send = sanitize(user_prompt) if anonymize else user_prompt
    add_message(session_id, "user", text_to_send, {"temperature": temperature, "reasoning_effort": reasoning_effort})

    if save_only:
        st.success("Turno guardado (no se llamó al LLM).")
    else:
        if not api_key:
            st.error("Falta OpenAI API Key. Configúrala en la barra lateral o en OPENAI_API_KEY.")
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
                }
                # Modo seguro: solo enviamos reasoning si el modelo lo soporta
                if model_supports_reasoning(model):
                    req_kwargs["reasoning"] = {"effort": reasoning_effort}

                t0 = time.time()
                resp = client.responses.create(**req_kwargs)
                latency_ms = int((time.time() - t0) * 1000)

                # Texto de respuesta (Responses API unificado)
                assistant_text = getattr(resp, "output_text", None)
                if not assistant_text:
                    # Fallback por si cambia el SDK
                    try:
                        assistant_text = json.dumps(resp.to_dict(), ensure_ascii=False)
                    except Exception:
                        assistant_text = str(resp)

                add_message(session_id, "assistant", assistant_text, {"model": model, "latency_ms": latency_ms})
                st.success(f"Respuesta recibida en {latency_ms} ms y guardada.")

                if show_raw:
                    with st.expander("RAW response"):
                        try:
                            st.json(resp.to_dict())
                        except Exception:
                            st.write(resp)
            except Exception as e:
                st.error(f"Error llamando al modelo: {e}")

# =========================
# Historial
# =========================
st.subheader("4) Historial")
rows = get_messages(session_id)
if rows:
    df = pd.DataFrame([{
        "id": r["id"],
        "role": r["role"],
        "content": r["content"],
        "created_at": r["created_at"]
    } for r in rows])
    st.dataframe(df, use_container_width=True, height=320)

    # Export JSONL
    jsonl = "\n".join(json.dumps(
        {"role": r["role"], "content": r["content"]},
        ensure_ascii=False
    ) for r in rows)
    st.download_button(
        "Exportar JSONL",
        data=jsonl.encode("utf-8"),
        file_name=f"session_{session_id}.jsonl",
        mime="application/jsonl"
    )
else:
    st.info("Sin mensajes todavía.")

st.caption("Tip: Usa 'Solo guardar' para preparar prompts sin gastar tokens; luego desmarca para probarlos.")