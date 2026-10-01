"""Run Phase 2 tests only on a new local owned PostgreSQL database.

Main farm connection is never a test target. The test DB is checked absent before
creation; cleanup terminates connections to ONLY this owned disposable name.
"""
import argparse
import json
import time
from pathlib import Path
import os
import sys
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labels", nargs="*", default=["apps.mobile_sync"])
    parser.add_argument("--output", help="Generated summary within docs/mobile/evidence")
    args = parser.parse_args()
    import django
    django.setup()
    from django.conf import settings
    from django.db import connection, connections
    from django.test.runner import DiscoverRunner

    if connection.settings_dict["HOST"] not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Tests require the verified local PostgreSQL server.")
    owned_name = "test_mobile_phase02_" + uuid.uuid4().hex[:12]
    source_name = connection.settings_dict["NAME"]
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_database WHERE datname=%s", [owned_name])
        if cursor.fetchone() or owned_name == source_name:
            raise SystemExit("Refusing pre-existing/source database.")
    settings.DATABASES["default"].setdefault("TEST", {})["NAME"] = owned_name
    connection.settings_dict.setdefault("TEST", {})["NAME"] = owned_name

    class OwnedRunner(DiscoverRunner):
        def suite_result(self, suite, result, **kwargs):
            self.evidence = {"tests_run": result.testsRun,
                "failures": [test.id() for test, _ in result.failures],
                "errors": [test.id() for test, _ in result.errors],
                "skipped": [str(test) for test, _ in result.skipped]}
            return super().suite_result(suite, result, **kwargs)

        def teardown_databases(self, old_config, **kwargs):
            connections.close_all()
            with connection._nodb_cursor() as cursor:
                cursor.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()", [owned_name])
            return super().teardown_databases(old_config, **kwargs)

    print(f"Source database (read only for discovery): {source_name}; NEW owned test DB: {owned_name}", flush=True)
    started = time.monotonic()
    runner = OwnedRunner(verbosity=2, interactive=False)
    result = runner.run_tests(args.labels)
    if args.output:
        output = (ROOT / args.output).resolve()
        if not output.is_relative_to((ROOT / "docs/mobile/evidence").resolve()):
            raise SystemExit("Evidence output must stay under docs/mobile/evidence.")
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname=%s", [owned_name])
            removed = cursor.fetchone() is None
        output.write_text(json.dumps({**runner.evidence, "labels": args.labels, "owned_database": owned_name,
            "database_removed": removed, "source_database": source_name, "elapsed_seconds": round(time.monotonic()-started, 3),
            "result": "passed" if not result else "failed"}, indent=2)+"\n", encoding="utf-8")
    raise SystemExit(bool(result))


if __name__ == "__main__":
    main()
