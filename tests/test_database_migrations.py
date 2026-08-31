from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

from app import database
from app.config import Settings
from scripts.db_maintenance import (
    BASELINE_VERSION,
    MaintenanceError,
    backfill_baseline_metadata,
    restore_database,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DatabaseMigrationTests(unittest.IsolatedAsyncioTestCase):
    def test_repository_has_ordered_baseline_and_lifecycle_migration(self) -> None:
        self.assertEqual(
            database.expected_migration_versions(),
            [
                "0_20260830_schema_baseline.py",
                "1_20260829_sandbox_lifecycle.py",
            ],
        )

    def test_schema_auto_creation_defaults_off(self) -> None:
        settings = Settings(_env_file=None)
        self.assertFalse(settings.DB_AUTO_CREATE_SCHEMA)

    def test_production_rejects_schema_auto_creation(self) -> None:
        with self.assertRaisesRegex(ValueError, "DB_AUTO_CREATE_SCHEMA must be false"):
            Settings(
                _env_file=None,
                ENVIRONMENT="production",
                JWT_SECRET="configured-for-test",
                DB_AUTO_CREATE_SCHEMA=True,
            )

    async def test_migration_guard_accepts_repository_head(self) -> None:
        class Query:
            async def values_list(self, *_args, **_kwargs):
                return database.expected_migration_versions()

        class FakeAerich:
            @staticmethod
            def filter(**_kwargs):
                return Query()

        with patch.object(database, "Aerich", FakeAerich):
            await database.verify_migration_state()

    async def test_migration_guard_rejects_pending_version(self) -> None:
        class Query:
            async def values_list(self, *_args, **_kwargs):
                return ["0_20260830_schema_baseline.py"]

        class FakeAerich:
            @staticmethod
            def filter(**_kwargs):
                return Query()

        with patch.object(database, "Aerich", FakeAerich):
            with self.assertRaisesRegex(RuntimeError, "1_20260829_sandbox_lifecycle.py"):
                await database.verify_migration_state()

    async def test_baseline_is_idempotent_and_not_downgradable(self) -> None:
        path = PROJECT_ROOT / "migrations" / "models" / "0_20260830_schema_baseline.py"
        spec = importlib.util.spec_from_file_location("schema_baseline", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sql = await module.upgrade(None)
        self.assertIn('CREATE TABLE IF NOT EXISTS "users"', sql)
        self.assertIn('CREATE TABLE IF NOT EXISTS "aerich"', sql)
        with self.assertRaisesRegex(RuntimeError, "cannot be downgraded"):
            await module.downgrade(None)

    def test_live_restore_requires_exact_database_confirmation(self) -> None:
        with self.assertRaisesRegex(MaintenanceError, "--confirm-restore"):
            restore_database(
                "unused-container",
                Path("unused.dump"),
                Path("unused-backups"),
                confirmation=None,
            )

    def test_legacy_migration_metadata_registers_baseline_before_head(self) -> None:
        legacy = ["1_20260829_sandbox_lifecycle.py"]
        with (
            patch(
                "scripts.db_maintenance.applied_migrations",
                side_effect=[legacy, [BASELINE_VERSION, *legacy]],
            ),
            patch("scripts.db_maintenance.postgres") as postgres,
        ):
            backfill_baseline_metadata("postgres", "rca_agent")
        sql = postgres.call_args.args[-1]
        self.assertIn("MIN(id) - 1", sql)
        self.assertIn(BASELINE_VERSION, sql)


if __name__ == "__main__":
    unittest.main()
