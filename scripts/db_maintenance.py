"""Safe PostgreSQL backup, Aerich migration, and restore verification workflow.

The project intentionally keeps one long-lived PostgreSQL database. Every
migration action creates a dated custom-format backup before Aerich runs.
Restore verification uses a short-lived database in the same PostgreSQL
container and removes it afterwards.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import socket
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402


DEFAULT_BACKUP_DIR = PROJECT_ROOT / "backups" / "database"
DEFAULT_CONTAINER = "data_analysis_postgres"
BASELINE_VERSION = "0_20260830_schema_baseline.py"


class MaintenanceError(RuntimeError):
    pass


def run(*args: str, capture: bool = False) -> str:
    completed = subprocess.run(
        list(args),
        check=False,
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "command failed").strip()
        raise MaintenanceError(f"{args[0]} failed: {detail}")
    return completed.stdout.strip() if capture else ""


def require_docker(container: str) -> None:
    if not shutil.which("docker"):
        raise MaintenanceError("Docker CLI is unavailable")
    run("docker", "inspect", "--type", "container", container, capture=True)
    running = run(
        "docker", "inspect", "--format", "{{.State.Running}}", container, capture=True
    )
    if running.lower() != "true":
        raise MaintenanceError(f"PostgreSQL container is not running: {container}")


def postgres(container: str, *args: str, capture: bool = False) -> str:
    return run("docker", "exec", container, *args, capture=capture)


def database_exists(container: str, database: str) -> bool:
    output = postgres(
        container,
        "psql",
        "-U",
        settings.DB_USER,
        "-d",
        "postgres",
        "-Atc",
        f"SELECT 1 FROM pg_database WHERE datname = '{database.replace("'", "''")}'",
        capture=True,
    )
    return output == "1"


def applied_migrations(container: str, database: str) -> list[str]:
    table = postgres(
        container,
        "psql",
        "-U",
        settings.DB_USER,
        "-d",
        database,
        "-Atc",
        "SELECT COALESCE(to_regclass('public.aerich')::text, '')",
        capture=True,
    )
    if not table:
        return []
    output = postgres(
        container,
        "psql",
        "-U",
        settings.DB_USER,
        "-d",
        database,
        "-Atc",
        "SELECT COALESCE(string_agg(version, ',' ORDER BY id), '') FROM aerich",
        capture=True,
    )
    return [value for value in output.split(",") if value]


def backup_database(
    container: str,
    database: str,
    backup_dir: Path,
    label: str = "pre_migration",
) -> Path:
    require_docker(container)
    if not database_exists(container, database):
        raise MaintenanceError(f"Database does not exist: {database}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    backup_path = (backup_dir / f"{database}_{timestamp}_{label}.dump").resolve()
    remote_path = f"/tmp/dataagent_{uuid.uuid4().hex}.dump"
    try:
        postgres(
            container,
            "pg_dump",
            "-U",
            settings.DB_USER,
            "-d",
            database,
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file",
            remote_path,
        )
        run("docker", "cp", f"{container}:{remote_path}", str(backup_path))
    finally:
        try:
            postgres(container, "rm", "-f", "--", remote_path)
        except MaintenanceError:
            pass

    if not backup_path.is_file() or backup_path.stat().st_size == 0:
        raise MaintenanceError("Backup file was not created or is empty")

    hasher = hashlib.sha256()
    with backup_path.open("rb") as backup_stream:
        for chunk in iter(lambda: backup_stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "database": database,
        "format": "postgresql-custom",
        "sha256": digest,
        "size": backup_path.stat().st_size,
        "applied_migrations": applied_migrations(container, database),
    }
    backup_path.with_suffix(".json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Backup created: {backup_path}")
    print(f"SHA256: {digest}")
    return backup_path


def backfill_baseline_metadata(container: str, database: str) -> None:
    """Place a new baseline before a legacy already-applied migration.

    Some existing databases may already record migration 1, which was added
    before the full baseline. Inserting the baseline with an older synthetic
    id preserves Aerich's downgrade order while avoiding any schema rewrite.
    """
    applied = applied_migrations(container, database)
    if BASELINE_VERSION in applied or not applied:
        return
    baseline_sql = f"""
        INSERT INTO aerich (id, version, app, content)
        SELECT COALESCE((SELECT MIN(id) - 1 FROM aerich), -1),
               '{BASELINE_VERSION}', app, content
        FROM aerich
        WHERE app = 'models'
        ORDER BY id DESC
        LIMIT 1
        ON CONFLICT (id) DO NOTHING
    """
    postgres(
        container,
        "psql",
        "-U",
        settings.DB_USER,
        "-d",
        database,
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        baseline_sql,
    )
    if BASELINE_VERSION not in applied_migrations(container, database):
        raise MaintenanceError("Failed to backfill the schema baseline metadata")
    print("Registered schema baseline before existing Aerich migrations.")


def aerich_executable() -> str:
    candidate = Path(sys.executable).with_name("aerich.exe" if sys.platform == "win32" else "aerich")
    if candidate.is_file():
        return str(candidate)
    executable = shutil.which("aerich")
    if not executable:
        raise MaintenanceError("Aerich executable is unavailable; run uv sync first")
    return executable


def migrate(container: str, backup_dir: Path) -> None:
    backup_database(container, settings.DB_NAME, backup_dir)
    backfill_baseline_metadata(container, settings.DB_NAME)
    run(aerich_executable(), "upgrade")
    heads = run(aerich_executable(), "heads", capture=True)
    if "No available heads" not in heads:
        raise MaintenanceError(f"Unapplied migrations remain: {heads}")
    print("Aerich is at repository head.")


def copy_backup_to_container(container: str, backup_file: Path) -> str:
    backup_file = backup_file.resolve()
    if not backup_file.is_file():
        raise MaintenanceError(f"Backup file does not exist: {backup_file}")
    remote_path = f"/tmp/dataagent_restore_{uuid.uuid4().hex}.dump"
    run("docker", "cp", str(backup_file), f"{container}:{remote_path}")
    return remote_path


def restore_into(container: str, backup_file: Path, target_database: str) -> None:
    remote_path = copy_backup_to_container(container, backup_file)
    try:
        postgres(
            container,
            "pg_restore",
            "-U",
            settings.DB_USER,
            "-d",
            target_database,
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
            remote_path,
        )
    finally:
        try:
            postgres(container, "rm", "-f", "--", remote_path)
        except MaintenanceError:
            pass


def verify_restore(container: str, backup_file: Path) -> None:
    require_docker(container)
    target = f"dataagent_restore_verify_{uuid.uuid4().hex[:12]}"
    try:
        postgres(container, "createdb", "-U", settings.DB_USER, target)
        restore_into(container, backup_file, target)
        table_count = postgres(
            container,
            "psql",
            "-U",
            settings.DB_USER,
            "-d",
            target,
            "-Atc",
            "SELECT count(*) FROM pg_tables WHERE schemaname='public'",
            capture=True,
        )
        migrations = applied_migrations(container, target)
        if int(table_count or "0") < 10:
            raise MaintenanceError(f"Restored schema is incomplete: {table_count} public tables")
        print(f"Restore verified: tables={table_count}, migrations={len(migrations)}")
    finally:
        if database_exists(container, target):
            postgres(container, "dropdb", "-U", settings.DB_USER, "--force", target)


def port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def restore_database(
    container: str,
    backup_file: Path,
    backup_dir: Path,
    confirmation: str | None,
) -> None:
    target = settings.DB_NAME
    if confirmation != target:
        raise MaintenanceError(f"Pass --confirm-restore {target} to replace the database")
    if port_is_open("127.0.0.1", settings.APP_PORT):
        raise MaintenanceError("Stop the DataAgent main service before restoring the live database")

    require_docker(container)
    backup_database(container, target, backup_dir, label="pre_restore")
    postgres(container, "dropdb", "-U", settings.DB_USER, "--force", "--if-exists", target)
    postgres(container, "createdb", "-U", settings.DB_USER, target)
    restore_into(container, backup_file, target)
    print(f"Database restored: {target}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("backup", "migrate", "heads", "verify-restore", "restore")
    )
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--backup-file", type=Path)
    parser.add_argument("--confirm-restore")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.action == "backup":
            backup_database(args.container, settings.DB_NAME, args.backup_dir, label="manual")
        elif args.action == "migrate":
            migrate(args.container, args.backup_dir)
        elif args.action == "heads":
            print(run(aerich_executable(), "heads", capture=True))
        elif args.action == "verify-restore":
            if not args.backup_file:
                raise MaintenanceError("--backup-file is required")
            verify_restore(args.container, args.backup_file)
        elif args.action == "restore":
            if not args.backup_file:
                raise MaintenanceError("--backup-file is required")
            restore_database(
                args.container,
                args.backup_file,
                args.backup_dir,
                args.confirm_restore,
            )
    except MaintenanceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
