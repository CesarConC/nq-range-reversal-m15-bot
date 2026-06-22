"""
Inserta o actualiza cuentas en la tabla 'account' a partir de un fichero JSON.

Uso:
    python3 -m persistence.scripts.seed_accounts                        # lee accounts.json en la raiz del proyecto
    python3 -m persistence.scripts.seed_accounts /ruta/mis_cuentas.json # ruta personalizada

El JSON debe ser una lista de objetos con los campos de la tabla Account.
Consulta persistence/scripts/accounts.example.json para ver el formato.

Comportamiento:
  - Si la cuenta ya existe (mismo account_id): actualiza todos los campos.
  - Si no existe: la inserta.
  - Si --dry-run: muestra los cambios sin escribir nada en la DB.
"""
import argparse
import json
import logging
import sys
from pathlib import Path

import persistence.base  # noqa: F401
from persistence.init_db import create_db_and_tables
from persistence.models import Account
from persistence.session import get_session
from persistence.common import now_utc

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("seed_accounts")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JSON = PROJECT_ROOT / "accounts.json"


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        logger.error("Fichero no encontrado: %s", path)
        sys.exit(1)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        logger.error("El JSON debe ser una lista de objetos.")
        sys.exit(1)
    return data


def seed(json_path: Path, dry_run: bool = False) -> None:
    rows = _load_json(json_path)
    logger.info("Leyendo %d cuenta(s) de %s", len(rows), json_path)

    create_db_and_tables()

    inserted = updated = errors = 0

    with get_session() as db:
        for raw in rows:
            account_id = raw.get("account_id", "<sin id>")
            try:
                existing = db.get(Account, account_id)

                if existing is None:
                    account = Account(**raw)
                    action = "INSERT"
                else:
                    for field, value in raw.items():
                        if field not in ("account_id", "created_at"):
                            setattr(existing, field, value)
                    existing.updated_at = now_utc()
                    account = existing
                    action = "UPDATE"

                if dry_run:
                    logger.info("[DRY-RUN] %s account_id=%s label=%s",
                                action, account.account_id, account.label)
                else:
                    db.add(account)
                    db.commit()
                    logger.info("%s account_id=%s label=%s",
                                action, account.account_id, account.label)

                if action == "INSERT":
                    inserted += 1
                else:
                    updated += 1

            except Exception as exc:
                logger.error("Error en account_id=%s: %s", account_id, exc)
                errors += 1

    prefix = "[DRY-RUN] " if dry_run else ""
    logger.info("%sResumen: %d insertadas, %d actualizadas, %d errores",
                prefix, inserted, updated, errors)

    if errors:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed de la tabla account desde JSON.")
    parser.add_argument(
        "json_file",
        nargs="?",
        default=str(DEFAULT_JSON),
        help=f"Ruta al JSON de cuentas (por defecto: {DEFAULT_JSON})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra los cambios sin escribir en la base de datos.",
    )
    args = parser.parse_args()
    seed(Path(args.json_file), dry_run=args.dry_run)


if __name__ == "__main__":
    main()