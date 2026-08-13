import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
# On Railway, attach a Volume. Railway exposes its path in
# RAILWAY_VOLUME_MOUNT_PATH, so catalog changes survive redeploys/restarts.
DATA_DIR = Path(os.getenv("RAILWAY_VOLUME_MOUNT_PATH", BASE_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SEED_CATALOG_PATH = BASE_DIR / "catalog.json"
CATALOG_PATH = DATA_DIR / "catalog.json"
ORDERS_PATH = DATA_DIR / "orders.json"

# Only this Telegram account has access to the admin panel.
ADMIN_ID = 7212962967
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# JSON STORAGE
# ---------------------------------------------------------

def read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        logger.exception("Cannot read %s: %s", path, error)
        return default


def write_json(path: Path, data: Any) -> bool:
    """Save a JSON file atomically to prevent corruption on an interrupted write."""
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)
        return True
    except OSError as error:
        logger.exception("Cannot write %s: %s", path, error)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def load_catalog() -> dict[str, Any]:
    # The first Railway run copies the catalog committed with the code into the
    # empty persistent volume. Later changes are read from the volume instead.
    if not CATALOG_PATH.exists() and SEED_CATALOG_PATH.exists() and CATALOG_PATH != SEED_CATALOG_PATH:
        try:
            shutil.copy2(SEED_CATALOG_PATH, CATALOG_PATH)
        except OSError as error:
            logger.exception("Cannot create initial catalog: %s", error)
    catalog = read_json(CATALOG_PATH, {"currency": "EUR", "categories": {}})
    if not isinstance(catalog, dict):
        return {"currency": "EUR", "categories": {}}
    if not isinstance(catalog.get("categories"), dict):
        catalog["categories"] = {}
    catalog.setdefault("currency", "EUR")
    return catalog
І
