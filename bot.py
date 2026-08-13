import json
import logging
import os
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
)


# Files next to bot_clean.py
BASE_DIR = Path(__file__).resolve().parent
CATALOG_PATH = BASE_DIR / "catalog.json"
ORDERS_PATH = BASE_DIR / "orders.json"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")


def parse_admin_ids() -> list[int]:
    """Read one or several Telegram admin IDs from ADMIN_IDS."""
    raw = os.getenv("ADMIN_IDS", "")
    admin_ids = [
        int(part.strip())
        for part in raw.replace(";", ",").split(",")
        if part.strip().isdigit()
    ]
    if not admin_ids:
        raise RuntimeError("ADMIN_IDS is not set or contains no valid Telegram IDs")
    return admin_ids


ADMIN_IDS = parse_admin_ids()


def read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        logger.exception("Cannot read %s: %s", path, error)
        return default


def write_json(path: Path, data: Any) -> None:
    """Atomically save JSON so an interrupted write does not corrupt the file."""
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        logger.exception("Cannot write %s: %s", path, error)
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def load_catalog() -> dict[str, Any]:
    catalog = read_json(CATALOG_PATH, {})
    if not isinstance(catalog, dict):
        logger.error("catalog.json must contain a JSON object")
        return {}
    return catalog


CATALOG = load_catalog()
CURRENCY = str(CATALOG.get("currency", "EUR"))


def categories_get() -> dict[str, Any]:
    categories = CATALOG.get("categories", {})
    return categories if isinstance(categories, dict) else {}


def category_get(category_key: str) -> Optional[dict[str, Any]]:
    category = categories_get().get(category_key)
