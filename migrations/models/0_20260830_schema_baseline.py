from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    """Idempotent baseline for both an existing database and an empty restore target."""
    return r'''
        CREATE TABLE IF NOT EXISTS "agent_states" (
            "id" SERIAL NOT NULL PRIMARY KEY,
            "user_id" VARCHAR(128) NOT NULL,
            "session_id" VARCHAR(128) NOT NULL DEFAULT 'default',
            "round_id" INT NOT NULL,
            "state" JSONB NOT NULL,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT "uid_agent_state_user_id_74890b" UNIQUE ("user_id", "session_id", "round_id")
        );
        CREATE INDEX IF NOT EXISTS "idx_agent_state_user_id_a3b04b" ON "agent_states" ("user_id");
        CREATE INDEX IF NOT EXISTS "idx_agent_state_session_140215" ON "agent_states" ("session_id");

        CREATE TABLE IF NOT EXISTS "knowledge_items" (
            "id" UUID NOT NULL PRIMARY KEY,
            "title" VARCHAR(256) NOT NULL,
            "content" TEXT NOT NULL,
            "category" VARCHAR(64) NOT NULL,
            "metadata" JSONB,
            "milvus_id" VARCHAR(128),
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS "idx_knowledge_i_title_95e65d" ON "knowledge_items" ("title");
        CREATE INDEX IF NOT EXISTS "idx_knowledge_i_categor_eaf465" ON "knowledge_items" ("category");

        CREATE TABLE IF NOT EXISTS "sandbox_agents" (
            "id" SERIAL NOT NULL PRIMARY KEY,
            "name" VARCHAR(64) NOT NULL UNIQUE,
            "description" VARCHAR(1024) NOT NULL,
            "mode" VARCHAR(20) NOT NULL DEFAULT 'all',
            "tools" JSONB NOT NULL,
            "permission" JSONB NOT NULL,
            "temperature" DOUBLE PRECISION,
            "max_steps" INT,
            "hidden" BOOL NOT NULL DEFAULT FALSE,
            "content" TEXT NOT NULL,
            "enabled" BOOL NOT NULL DEFAULT TRUE,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS "sandbox_bindings" (
            "id" UUID NOT NULL PRIMARY KEY,
            "user_id" VARCHAR(100) NOT NULL,
            "session_id" VARCHAR(100) NOT NULL UNIQUE,
            "sandbox_id" VARCHAR(100) NOT NULL,
            "sandbox_type" VARCHAR(50) NOT NULL DEFAULT 'data_analysis',
            "workspace_path" VARCHAR(512) NOT NULL DEFAULT '/workspace',
            "mount_dir" VARCHAR(512),
            "is_active" BOOL NOT NULL DEFAULT TRUE,
            "status" VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
            "last_activity_at" TIMESTAMPTZ,
            "lease_expires_at" TIMESTAMPTZ,
            "released_at" TIMESTAMPTZ,
            "release_attempts" INT NOT NULL DEFAULT 0,
            "last_error" TEXT,
            "runtime_seen_at" TIMESTAMPTZ,
            "config_version" VARCHAR(100) NOT NULL DEFAULT 'v1',
            "synced_file_ids" JSONB NOT NULL,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS "idx_sandbox_bin_user_id_db5085" ON "sandbox_bindings" ("user_id");
        CREATE INDEX IF NOT EXISTS "idx_sandbox_bin_session_6fdcc7" ON "sandbox_bindings" ("session_id");
        CREATE INDEX IF NOT EXISTS "idx_sandbox_bin_status_385ba6" ON "sandbox_bindings" ("status");

        CREATE TABLE IF NOT EXISTS "sandbox_mcps" (
            "id" SERIAL NOT NULL PRIMARY KEY,
            "name" VARCHAR(64) NOT NULL UNIQUE,
            "mcp_type" VARCHAR(20) NOT NULL,
            "url" VARCHAR(500),
            "command" JSONB NOT NULL,
            "headers" JSONB NOT NULL,
            "environment" JSONB NOT NULL,
            "enabled" BOOL NOT NULL DEFAULT TRUE,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS "sandbox_skills" (
            "id" SERIAL NOT NULL PRIMARY KEY,
            "name" VARCHAR(64) NOT NULL UNIQUE,
            "description" VARCHAR(1024) NOT NULL,
            "metadata" JSONB NOT NULL,
            "enabled" BOOL NOT NULL DEFAULT TRUE,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS "sandbox_skill_permissions" (
            "id" SERIAL NOT NULL PRIMARY KEY,
            "permission" VARCHAR(10) NOT NULL DEFAULT 'allow',
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "agent_id" INT NOT NULL REFERENCES "sandbox_agents" ("id") ON DELETE CASCADE,
            "skill_id" INT NOT NULL REFERENCES "sandbox_skills" ("id") ON DELETE CASCADE,
            CONSTRAINT "uid_sandbox_ski_skill_i_4b1d29" UNIQUE ("skill_id", "agent_id")
        );

        CREATE TABLE IF NOT EXISTS "sessions" (
            "id" UUID NOT NULL PRIMARY KEY,
            "session_id" VARCHAR(128) NOT NULL,
            "user_id" VARCHAR(128) NOT NULL,
            "name" VARCHAR(200),
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT "uid_sessions_user_id_47540f" UNIQUE ("user_id", "session_id")
        );
        CREATE INDEX IF NOT EXISTS "idx_sessions_session_4dac79" ON "sessions" ("session_id");
        CREATE INDEX IF NOT EXISTS "idx_sessions_user_id_80072d" ON "sessions" ("user_id");

        CREATE TABLE IF NOT EXISTS "session_messages" (
            "id" SERIAL NOT NULL PRIMARY KEY,
            "message" JSONB NOT NULL,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "session_id" UUID NOT NULL REFERENCES "sessions" ("id") ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS "users" (
            "id" UUID NOT NULL PRIMARY KEY,
            "username" VARCHAR(64) NOT NULL UNIQUE,
            "password_hash" VARCHAR(256) NOT NULL,
            "is_admin" BOOL NOT NULL DEFAULT FALSE,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS "idx_users_usernam_266d85" ON "users" ("username");

        CREATE TABLE IF NOT EXISTS "system_prompts" (
            "id" SERIAL NOT NULL PRIMARY KEY,
            "name" VARCHAR(64) NOT NULL UNIQUE,
            "title" VARCHAR(128) NOT NULL,
            "content" TEXT NOT NULL,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "updated_by_id" UUID REFERENCES "users" ("id") ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS "idx_system_prom_name_7940df" ON "system_prompts" ("name");

        CREATE TABLE IF NOT EXISTS "user_files" (
            "id" UUID NOT NULL PRIMARY KEY,
            "user_id" VARCHAR(100) NOT NULL,
            "filename" VARCHAR(255) NOT NULL,
            "original_name" VARCHAR(255) NOT NULL,
            "content_type" VARCHAR(100),
            "size" BIGINT NOT NULL DEFAULT 0,
            "local_path" VARCHAR(512) NOT NULL,
            "session_id" VARCHAR(100),
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS "idx_user_files_user_id_380b4e" ON "user_files" ("user_id");
        CREATE INDEX IF NOT EXISTS "idx_user_files_session_80aac0" ON "user_files" ("session_id");

        CREATE TABLE IF NOT EXISTS "aerich" (
            "id" SERIAL NOT NULL PRIMARY KEY,
            "version" VARCHAR(255) NOT NULL,
            "app" VARCHAR(100) NOT NULL,
            "content" JSONB NOT NULL
        );
    '''


async def downgrade(db: BaseDBAsyncClient) -> str:
    raise RuntimeError(
        "The schema baseline cannot be downgraded. Restore a verified backup instead."
    )
