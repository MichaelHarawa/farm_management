"""Reproduce schema checks or migrate/seed a NEW disposable copy of the local farm.

Never migrates/activates the source database. No credentials/data rows in output.
The restored DB and temporary dump are created by this invocation only.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
EVIDENCE = ROOT / "docs/mobile/evidence"


def emit(filename, data):
    (EVIDENCE / filename).write_text(json.dumps(data, indent=2, default=str)+"\n", encoding="utf-8")
    print(f"Generated evidence: {filename}", flush=True)


def business_audit(audit):
    # The existing audit includes migration readiness. Creating/applying these
    # additive migrations changes that diagnostic, not money or source records.
    return {"issues": [issue for issue in audit["issues"] if issue["code"] != "unapplied_migrations"],
            "counts": {key: value for key, value in audit["summary"].items() if key not in {"issues", "critical", "warnings"}}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["checks", "schema", "restore", "preservation"])
    parser.add_argument("--container", default="farm_postgres_db")
    args = parser.parse_args()
    import django
    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.db import connection, connections, transaction
    import phase01_baseline as baseline

    if args.mode == "checks":
        call_command("check", verbosity=1)
        call_command("makemigrations", check=True, dry_run=True, verbosity=1)
        emit("phase02-backend-checks.json", {"django_check": "passed", "migration_drift": False})
        return

    if args.mode == "schema":
        from django.urls import include, path
        from drf_spectacular.generators import SchemaGenerator
        from drf_spectacular.validation import validate_schema
        schema = SchemaGenerator(patterns=[path("api/v1/mobile-sync/", include("apps.mobile_sync.urls"))]).get_schema(request=None, public=True)
        validate_schema(schema)
        target = ROOT / "docs/mobile/contracts/sync-api-v1.openapi.json"
        target.write_text(json.dumps(schema, indent=2)+"\n", encoding="utf-8")
        emit("phase02-schema.json", {"validated": True, "openapi": schema["openapi"],
            "paths": len(schema["paths"]), "methods": sum(len([key for key in value if key in {"get", "post"}]) for value in schema["paths"].values()),
            "artifact": str(target.relative_to(ROOT))})
        return

    if connection.settings_dict["HOST"] not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Requires the verified local PostgreSQL connection.")
    if args.mode == "preservation":
        baseline.OUTPUT = EVIDENCE / "phase02-database-after.json"
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
            baseline.snapshot()
        before = json.loads((EVIDENCE / "phase02-database-before.json").read_text(encoding="utf-8"))
        after = json.loads(baseline.OUTPUT.read_text(encoding="utf-8"))
        unchanged = before["fingerprints"] == after["fingerprints"] and business_audit(before["finance_audit"]) == business_audit(after["finance_audit"])
        emit("phase02-preservation.json", {"database": after["database"], "fingerprinted_tables": len(after["fingerprints"]),
            "business_fingerprints_unchanged": before["fingerprints"] == after["fingerprints"],
            "finance_audit_unchanged": before["finance_audit"] == after["finance_audit"],
            "finance_business_audit_unchanged": business_audit(before["finance_audit"]) == business_audit(after["finance_audit"]),
            "unapplied": after["unapplied"], "sync_capture_enabled": settings.MOBILE_SYNC_CAPTURE,
            "sync_api_enabled": settings.MOBILE_SYNC_ENABLED})
        if not unchanged:
            raise SystemExit("Source baseline changed: inspect evidence before claiming preservation.")
        return

    source = connection.settings_dict["NAME"]
    user = connection.settings_dict["USER"]
    owned = "mobile_phase02_restore_" + uuid.uuid4().hex[:12]
    dump = "/tmp/" + owned + ".dump"
    created = False
    started = time.monotonic()
    from psycopg2 import sql

    def docker(*arguments):
        subprocess.run(["docker", "exec", args.container, *arguments], check=True, capture_output=True, text=True)

    try:
        with connection._nodb_cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname=%s", [owned])
            if cursor.fetchone() or owned == source:
                raise SystemExit("Refusing pre-existing/source restore target.")
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(owned)))
            created = True
        print(f"Read-only dump source: {source}; NEW owned restore DB: {owned}", flush=True)
        docker("pg_dump", "-U", user, "--dbname", source, "--format=custom", "--file", dump)
        docker("pg_restore", "-U", user, "--dbname", owned, "--no-owner", "--no-acl", dump)
        connections.close_all()
        settings.DATABASES["default"]["NAME"] = owned
        connection.settings_dict["NAME"] = owned
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            if cursor.fetchone()[0] != owned:
                raise SystemExit("Restore connection identity mismatch.")
        baseline.OUTPUT = EVIDENCE / "phase02-restored-before.json"
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
            baseline.snapshot()
        call_command("migrate", interactive=False, verbosity=1)
        call_command("seed_sync", database_name=owned, verbosity=1)
        baseline.OUTPUT = EVIDENCE / "phase02-restored-after.json"
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
            baseline.snapshot()
        before = json.loads((EVIDENCE / "phase02-restored-before.json").read_text(encoding="utf-8"))
        after = json.loads(baseline.OUTPUT.read_text(encoding="utf-8"))
        from apps.mobile_sync.models import SyncChange, SyncEntity, SyncStreamState
        summary = {"source_database": source, "owned_database": owned,
            "fingerprinted_tables": len(after["fingerprints"]),
            "business_fingerprints_unchanged": before["fingerprints"] == after["fingerprints"],
            "finance_audit_unchanged": before["finance_audit"] == after["finance_audit"],
            "finance_business_audit_unchanged": business_audit(before["finance_audit"]) == business_audit(after["finance_audit"]),
            "migration_readiness_before": before["finance_audit"]["migration_state"],
            "migration_readiness_after": after["finance_audit"]["migration_state"],
            "unapplied_after": after["unapplied"], "sync_entities": SyncEntity.objects.count(),
            "sync_changes": SyncChange.objects.count(), "ready": SyncStreamState.objects.get(pk=1).ready,
            "elapsed_seconds": round(time.monotonic()-started, 3)}
        if not summary["business_fingerprints_unchanged"] or not summary["finance_business_audit_unchanged"] or summary["unapplied_after"]:
            raise AssertionError("Restored migration/seed changed business baseline.")
    finally:
        connections.close_all()
        settings.DATABASES["default"]["NAME"] = source
        connection.settings_dict["NAME"] = source
        if created:
            with connection._nodb_cursor() as cursor:
                cursor.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()", [owned])
                cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(owned)))
            docker("rm", "-f", dump)  # Exact generated file inside the Linux container.
    summary["owned_database_removed"] = True
    summary["temporary_dump_removed"] = True
    emit("phase02-restored-migration.json", summary)


if __name__ == "__main__":
    main()
