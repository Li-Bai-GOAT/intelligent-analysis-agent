from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "sandbox_bindings"
            ADD COLUMN IF NOT EXISTS "status" VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
            ADD COLUMN IF NOT EXISTS "last_activity_at" TIMESTAMPTZ NULL,
            ADD COLUMN IF NOT EXISTS "lease_expires_at" TIMESTAMPTZ NULL,
            ADD COLUMN IF NOT EXISTS "released_at" TIMESTAMPTZ NULL,
            ADD COLUMN IF NOT EXISTS "release_attempts" INT NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS "last_error" TEXT NULL,
            ADD COLUMN IF NOT EXISTS "runtime_seen_at" TIMESTAMPTZ NULL,
            ADD COLUMN IF NOT EXISTS "config_version" VARCHAR(100) NOT NULL DEFAULT 'v1';

        UPDATE "sandbox_bindings"
        SET "status" = CASE WHEN "is_active" THEN 'ACTIVE' ELSE 'RELEASED' END;

        UPDATE "sandbox_bindings"
        SET "last_activity_at" = "updated_at"
        WHERE "last_activity_at" IS NULL;

        CREATE INDEX IF NOT EXISTS "idx_sandbox_bin_status_385ba6"
            ON "sandbox_bindings" ("status");
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_sandbox_bin_status_385ba6";
        ALTER TABLE "sandbox_bindings"
            DROP COLUMN IF EXISTS "config_version",
            DROP COLUMN IF EXISTS "runtime_seen_at",
            DROP COLUMN IF EXISTS "last_error",
            DROP COLUMN IF EXISTS "release_attempts",
            DROP COLUMN IF EXISTS "released_at",
            DROP COLUMN IF EXISTS "lease_expires_at",
            DROP COLUMN IF EXISTS "last_activity_at",
            DROP COLUMN IF EXISTS "status";
    """


# Aerich 0.9+ requires each migration to carry the model state that follows
# this additive migration. The repository had no historical Aerich baseline,
# so this is the first complete schema snapshot.
MODELS_STATE = (
    "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"
    "ulj8KBZ/r9PLz/8D4V0/oQ=="
)
