"""Reproduce mobile discovery without changing the application's configured database.

Run with the repository virtual environment. Read modes use a PostgreSQL
read-only transaction. Tests require a local server and a brand-new named test DB.
No credentials or user/source-document contents are printed.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
OUTPUT = None


def emit(value):
    rendered = json.dumps(value, indent=2, default=str, sort_keys=True)
    if OUTPUT:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(rendered + "\n", encoding="utf-8")
        print(f"Generated evidence: {OUTPUT.relative_to(ROOT)}")
    else:
        print(rendered)


def snapshot():
    from django.apps import apps
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from apps.finance.services.audit import finance_audit_report

    fingerprints = {}
    for model in apps.get_models():
        if model._meta.app_label not in {"accounts", "poultry", "finance"}:
            continue
        digest = hashlib.sha256()
        count = 0
        for row in model.objects.order_by("pk").values().iterator(chunk_size=500):
            digest.update(json.dumps(row, sort_keys=True, default=str).encode())
            digest.update(b"\n")
            count += 1
        fingerprints[model._meta.label] = {"count": count, "sha256": digest.hexdigest()}
    # Include automatic M2M tables so roles cannot change unnoticed.
    user = apps.get_model("accounts.User")
    role_links = list(user.roles.through.objects.order_by("pk").values())
    fingerprints["accounts.User.roles"] = {
        "count": len(role_links),
        "sha256": hashlib.sha256(json.dumps(role_links, sort_keys=True, default=str).encode()).hexdigest(),
    }
    executor = MigrationExecutor(connection)
    audit = finance_audit_report()
    emit({
        "database": {"name": connection.settings_dict["NAME"], "host": connection.settings_dict["HOST"], "read_only": True},
        "migration_leaves": executor.loader.graph.leaf_nodes(),
        "unapplied": [(migration.app_label, migration.name) for migration, _ in executor.migration_plan(executor.loader.graph.leaf_nodes())],
        "fingerprints": fingerprints,
        "finance_audit": audit,
    })


def inventory():
    from django.apps import apps
    from drf_spectacular.generators import EndpointEnumerator
    rows = []
    for path, _, method, callback in EndpointEnumerator().get_api_endpoints():
        if not path.startswith("/api/v1/") or method in {"HEAD", "OPTIONS"} or "{format}" in path:
            continue
        cls = callback.cls
        action = getattr(callback, "actions", {}).get(method.lower(), method.lower())
        options = {**getattr(callback, "initkwargs", {})}
        view = cls(**options)
        view.action = action
        permissions = [permission.__name__ for permission in view.permission_classes]
        serializer = getattr(view, "serializer_class", None)
        rows.append({"path": path, "method": method, "view": cls.__name__, "action": action,
                     "permissions": permissions, "serializer": getattr(serializer, "__name__", None),
                     "pagination": getattr(getattr(view, "pagination_class", None), "__name__", None)})
    models = {}
    for model in apps.get_models():
        if model._meta.app_label not in {"accounts", "poultry", "finance"}:
            continue
        models[model._meta.label] = [{"name": field.name, "type": field.get_internal_type(),
                                    "null": field.null, "blank": field.blank,
                                    "max_length": field.max_length,
                                    "decimal_places": getattr(field, "decimal_places", None),
                                    "related_model": field.related_model._meta.label if field.is_relation and field.related_model else None}
                                   for field in model._meta.fields]
    emit({"endpoint_method_count": len(rows), "endpoints": rows, "models": models})


def contracts():
    """Validate the declarative request contract without touching Django/DB."""
    from jsonschema import Draft202012Validator, FormatChecker

    contract_dir = ROOT / "docs/mobile/contracts"
    schema = json.loads((contract_dir / "push-v1.schema.json").read_text(encoding="utf-8"))
    sample = json.loads((contract_dir / "mortality-record.example.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    formats = FormatChecker()

    # jsonschema's RFC3339 checker has an optional package dependency. Supply a
    # deterministic calendar check rather than treating an absent checker as valid.
    @formats.checks("date-time", raises=ValueError)
    def valid_instant(value):
        if not isinstance(value, str):
            return True  # JSONSchema's type constraint handles non-strings.
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None

    validator = Draft202012Validator(schema, format_checker=formats)
    validator.validate(sample)
    rejected = []

    def must_reject(label, mutate):
        candidate = copy.deepcopy(sample)
        mutate(candidate)
        if validator.is_valid(candidate):
            raise AssertionError(f"Invalid request unexpectedly passed: {label}")
        rejected.append(label)

    def change_payload(key, value):
        return lambda candidate: candidate["operations"][0]["payload"].__setitem__(key, value)

    must_reject("missing reporter", lambda c: c["operations"][0]["payload"].pop("reported_by_name"))
    must_reject("whitespace reporter", change_payload("reported_by_name", "   "))
    must_reject("caller-controlled age", change_payload("age_in_days", 4))
    must_reject("negative birds", change_payload("quantity_dead", -1))
    must_reject("number-valued UUID", change_payload("batch_uuid", 1))
    must_reject("invalid timestamp", change_payload("mortality_date", "2026-99-99T06:30:00Z"))
    must_reject("non-UTC timestamp", change_payload("mortality_date", "2026-10-01T08:30:00+02:00"))
    must_reject("unregistered action", lambda c: c["operations"][0].__setitem__("action", "delete"))
    must_reject("append revision", lambda c: c["operations"][0].__setitem__("base_version", "1"))
    must_reject("unknown envelope field", lambda c: c.__setitem__("actor_id", c["device_id"]))
    must_reject("oversized command count", lambda c: c.__setitem__("operations", c["operations"] * 51))
    must_reject("duplicate dependencies", lambda c: c["operations"][0].__setitem__("depends_on", [c["device_id"]] * 2))
    emit({"schema_valid": True, "example_valid": True, "invalid_cases_rejected": rejected,
          "note": "Shape tests only; PostgreSQL authorization/flock/idempotency behavior is Phase 2."})


def verify():
    """Check pack integrity and preserved table fingerprints; no database writes."""
    pack = ROOT / "docs/mobile"
    before = json.loads((pack / "evidence/database-before.json").read_text(encoding="utf-8"))
    after = json.loads((pack / "evidence/database-after.json").read_text(encoding="utf-8"))
    tables = set(before["fingerprints"]) | set(after["fingerprints"])
    changed = sorted(table for table in tables if before["fingerprints"].get(table) != after["fingerprints"].get(table))
    if changed or before["migration_leaves"] != after["migration_leaves"] or after["unapplied"]:
        raise AssertionError(f"Baseline mismatch: {changed}")
    link_count = 0
    markdown_files = list(pack.rglob("*.md"))
    for path in markdown_files:
        source = path.read_text(encoding="utf-8")
        if len(re.findall(r"^```", source, re.MULTILINE)) % 2:
            raise AssertionError(f"Unclosed fenced block: {path}")
        for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", source):
            if link.startswith(("http://", "https://", "#")):
                continue
            target = link.split("#", 1)[0]
            resolved_target = (path.parent / target).resolve()
            # A checkpoint may link the verification report generated by this
            # successful invocation; all other targets must already exist.
            if not resolved_target.exists() and resolved_target != OUTPUT:
                raise AssertionError(f"Missing link target in {path}: {link}")
            link_count += 1
    json_files = list(pack.rglob("*.json"))
    for path in json_files:
        json.loads(path.read_text(encoding="utf-8"))
    compile(Path(__file__).read_text(encoding="utf-8"), __file__, "exec")
    emit({"fingerprinted_tables": len(tables), "changed_tables": changed,
          "migration_leaves_unchanged": True, "unapplied_migrations": 0,
          "finance_audit_unchanged": before["finance_audit"] == after["finance_audit"],
          "markdown_files_checked": len(markdown_files), "local_links_checked": link_count,
          "json_files_checked": len(json_files), "script_compiles": True})


def main():
    global OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("snapshot", "inventory", "checks", "schema", "tests", "contracts", "verify"))
    parser.add_argument("--database", help="New local test DB name beginning test_mobile_phase01_")
    parser.add_argument("--output", help="Generated JSON evidence path within docs/mobile/evidence")
    args = parser.parse_args()
    if args.output:
        OUTPUT = (ROOT / args.output).resolve()
        if not OUTPUT.is_relative_to((ROOT / "docs/mobile/evidence").resolve()):
            raise SystemExit("Evidence output must stay under docs/mobile/evidence.")
    if args.mode == "contracts":
        contracts()
        return
    if args.mode == "verify":
        verify()
        return
    import django
    django.setup()
    from django.conf import settings
    from django.db import connection, transaction
    from django.core.management import call_command

    if args.mode == "tests":
        if connection.settings_dict["HOST"] not in {"localhost", "127.0.0.1", "::1"}:
            raise SystemExit("Test creation is restricted to a local PostgreSQL server.")
        name = args.database or "test_mobile_phase01_" + uuid.uuid4().hex[:12]
        if not name.startswith("test_mobile_phase01_") or not name.replace("_", "").isalnum():
            raise SystemExit("Invalid disposable database name.")
        if name == connection.settings_dict["NAME"]:
            raise SystemExit("Refusing to use the configured application database.")
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", [name])
            if cursor.fetchone():
                raise SystemExit("Refusing to reuse or delete a pre-existing database.")
        settings.DATABASES["default"].setdefault("TEST", {})["NAME"] = name
        connection.settings_dict.setdefault("TEST", {})["NAME"] = name
        from django.test.runner import DiscoverRunner
        print(f"Isolated PostgreSQL test database: {name}", flush=True)
        # DiscoverRunner creates this database, installs migrations, and removes
        # only the test DB it created. No keepdb/autoclobber fallback is used.
        result = DiscoverRunner(verbosity=1, interactive=False).run_tests([
            "apps.accounts", "apps.poultry", "apps.finance", "apps.inventory",
        ])
        raise SystemExit(bool(result))

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        if args.mode == "snapshot":
            snapshot()
        elif args.mode == "inventory":
            inventory()
        elif args.mode == "checks":
            call_command("check")
            call_command("makemigrations", check=True, dry_run=True)
            call_command("finance_preflight")
        elif args.mode == "schema":
            from drf_spectacular.generators import SchemaGenerator
            schema = SchemaGenerator().get_schema(request=None, public=True)
            from drf_spectacular.validation import validate_schema
            validate_schema(schema)
            emit({"openapi": schema["openapi"], "path_count": len(schema["paths"]),
                  "component_count": len(schema["components"]["schemas"]),
                  "schema_note": "Generation warnings/errors are inherited; see stderr. No generated mobile client should rely on unannotated APIView responses."})


if __name__ == "__main__":
    main()
