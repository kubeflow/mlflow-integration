"""Database migration for MLflow backend and registry stores.

Bootstraps new databases, upgrades existing schemas via Alembic, and
verifies the final revision matches the expected head.
"""

import os
import sys

import mlflow.store.db.utils as db_utils
from mlflow.version import VERSION

EXIT_UNSUPPORTED_BACKEND = 11
EXIT_UNSUPPORTED_REGISTRY = 12
EXIT_REVISION_MISMATCH = 13
EXIT_REVISION_RESOLUTION_FAILURE = 14
EXIT_RETRYABLE_FAILURE = 15

TERMINAL_REVISION_RESOLUTION_PATTERNS = (
    "can't locate revision identified by",
    "multiple heads are present",
    "cycle is detected in revisions",
    "dependency cycle detected",
)


def supports_sql_migration(uri):
    dialect = uri.split(":", 1)[0].split("+", 1)[0]
    return dialect in ("sqlite", "postgresql", "mysql")


def fail(message, exit_code, log_message=None):
    print(log_message or message, file=sys.stderr)
    try:
        with open("/dev/termination-log", "w", encoding="utf-8") as f:
            f.write(message)
    except OSError:
        pass
    raise SystemExit(exit_code)


def classify_exception(exc):
    lower_message = (str(exc) or exc.__class__.__name__).lower()
    for pattern in TERMINAL_REVISION_RESOLUTION_PATTERNS:
        if pattern in lower_message:
            return (
                "migration failed: Alembic could not resolve the revision graph",
                EXIT_REVISION_RESOLUTION_FAILURE,
            )
    return (
        "migration failed due to a retryable database or migration error",
        EXIT_RETRYABLE_FAILURE,
    )


def migrate_store(name, uri):
    engine = db_utils.create_sqlalchemy_engine_with_retry(uri)
    current_rev = db_utils._get_schema_version(engine)
    print(f"{name} store current revision: {current_rev!r}")
    if not current_rev:
        print(f"{name} store has no Alembic revision; bootstrapping schema")
        db_utils._initialize_tables(engine)
    else:
        print(f"{name} store upgrading from revision {current_rev!r}")
        db_utils._upgrade_db(engine)

    final_rev = db_utils._get_schema_version(engine)
    latest_rev = db_utils._get_latest_schema_revision()
    if final_rev != latest_rev:
        fail(
            f"{name} store revision {final_rev!r} does not match head {latest_rev!r}",
            EXIT_REVISION_MISMATCH,
        )
    print(f"{name} store migrated to revision {final_rev!r}")


def main():
    backend_uri = os.environ.get("MLFLOW_BACKEND_STORE_URI", "").strip()
    registry_uri = os.environ.get("MLFLOW_REGISTRY_STORE_URI", "").strip()

    if backend_uri and not supports_sql_migration(backend_uri):
        fail(
            "migration only supports SQL backend store URIs",
            EXIT_UNSUPPORTED_BACKEND,
        )
    if registry_uri and registry_uri != backend_uri and not supports_sql_migration(registry_uri):
        fail(
            "migration only supports SQL registry store URIs",
            EXIT_UNSUPPORTED_REGISTRY,
        )

    stores = []
    if backend_uri:
        stores.append(("backend", backend_uri))
    if registry_uri and registry_uri != backend_uri:
        stores.append(("registry", registry_uri))

    if not stores:
        print("No SQL backend or registry stores require migration")
        return 0

    print(f"Running migration with MLflow {VERSION}")
    for name, uri in stores:
        migrate_store(name, uri)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        message, exit_code = classify_exception(exc)
        fail(message, exit_code, f"{message} ({exc.__class__.__name__})")
