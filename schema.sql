CREATE TABLE IF NOT EXISTS tenants (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS projects (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_projects_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE,
    CONSTRAINT uq_projects_id_tenant UNIQUE (id, tenant_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    project_id BIGINT NOT NULL,
    title TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_sessions_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE,
    CONSTRAINT fk_sessions_project_tenant
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT uq_sessions_id_tenant UNIQUE (id, tenant_id)
);

CREATE TABLE IF NOT EXISTS prompts (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    session_id BIGINT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'user' CHECK (actor IN ('system', 'user')),
    prompt_text TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_prompts_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE,
    CONSTRAINT fk_prompts_session_tenant
        FOREIGN KEY (session_id, tenant_id) REFERENCES sessions (id, tenant_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS responses (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    prompt_id BIGINT NOT NULL,
    session_id BIGINT NOT NULL,
    response_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'complete' CHECK (status IN ('complete', 'truncated', 'error', 'partial')),
    latency_ms INTEGER,
    model_used TEXT,
    recordia_hash TEXT UNIQUE,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_responses_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE,
    CONSTRAINT fk_responses_prompt
        FOREIGN KEY (prompt_id) REFERENCES prompts (id) ON DELETE CASCADE,
    CONSTRAINT fk_responses_session_tenant
        FOREIGN KEY (session_id, tenant_id) REFERENCES sessions (id, tenant_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_projects_tenant ON projects (tenant_id);
CREATE INDEX IF NOT EXISTS idx_sessions_tenant_project ON sessions (tenant_id, project_id);
CREATE INDEX IF NOT EXISTS idx_prompts_tenant_session_created ON prompts (tenant_id, session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_responses_tenant_session_created ON responses (tenant_id, session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_responses_prompt_id ON responses (prompt_id);
CREATE INDEX IF NOT EXISTS idx_responses_status ON responses (status);