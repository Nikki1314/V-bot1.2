import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    InputMediaPhoto,
    Update,
)
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

# =========================================================
# PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

CATALOG_PATH = BASE_DIR / "catalog.json"
STOCK_PATH = BASE_DIR / "stock.json"
ORDERS_PATH = BASE_DIR / "orders.json"

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set")


def parse_admin_ids() -> List[int]:
    raw = os.getenv("ADMIN_IDS", "7212962967")
    result: List[int] = []
    raw = os.getenv("MANAGER_CHAT_I", 5522897576")
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            result.append(int(part))

    return result


ADMIN_IDS = parse_admin_ids()


}

# =========================================================
# JSON HELPERS
# =========================================================


def write_json(path: Path, data: Any) -> None:
    try:
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except Exception as e:
        logger.exception("Failed writing %s: %s", path, e)


def ensure_runtime_files() -> None:
    if not STOCK_PATH.exists():
        write_json(STOCK_PATH, {})
    if not ORDERS_PATH.exists():
        write_json(ORDERS_PATH, [])


def read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.exception("Failed reading %s: %s", path, e)
        return default


ensure_runtime_files()

CATALOG = read_json(CATALOG_PATH, {})
STOCK = read_json(STOCK_PATH, {})

if not isinstance(STOCK, dict):
    STOCK = {}

CURRENCY = CATALOG.get("currency", "EUR")

# =========================================================
# HELPERS
# =========================================================


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def item_key(*parts: Any) -> str:
    return ":".join(str(p) for p in parts)


def fmt_price(value: Any) -> str:
    try:
        return f"{float(value):g} {CURRENCY}"
    except Exception:
        return f"{value} {CURRENCY}"


def get_username(user) -> str:
    return f"@{user.username}" if user and user.username else f"id:{user.id}"


def cart_get(context: ContextTypes.DEFAULT_TYPE) -> List[Dict[str, Any]]:
    return context.user_data.setdefault("cart", [])


def cart_total(cart: List[Dict[str, Any]]) -> float:
    return round(sum(float(x["price"]) for x in cart), 2)


def stock_get(key: str) -> Dict[str, Any]:
    return STOCK.get(key, {"in_stock": True, "eta": None})


def stock_set(key: str, in_stock: bool, eta: Optional[str] = None) -> None:
    STOCK[key] = {
        "in_stock": in_stock,
        "eta": eta,
    }
    write_json(STOCK_PATH, STOCK)


def get_city_key(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("city_key", "Other")


def get_city_title(context: ContextTypes.DEFAULT_TYPE) -> str:
    city_key = get_city_key(context)

    if city_key == "Other":
        return context.user_data.get("custom_city", "Інше місто")

    return CITY_CONFIG.get(city_key, CITY_CONFIG["Other"])["title"]


def get_city_config(context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
    return CITY_CONFIG.get(get_city_key(context), CITY_CONFIG["Other"])


def save_order(order: Dict[str, Any]) -> None:
    orders = read_json(ORDERS_PATH, [])

    if not isinstance(orders, list):
        orders = []

    orders.append(order)
    write_json(ORDERS_PATH, orders[-1000:])


def extract_flavor_name(flavor: Any) -> str:
    if isinstance(flavor, str):
        return flavor

    if isinstance(flavor, dict):
        return str(flavor.get("name") or flavor.get("title") or flavor)

    return str(flavor)


def categories_get() -> Dict[str, Any]:
    categories = CATALOG.get("categories", {})
    return categories if isinstance(categories, dict) else {}


def category_get(cat_key: str) -> Optional[Dict[str, Any]]:
    return categories_get().get(cat_key)


def brand_get(cat_key: str, brand_key: str) -> Optional[Dict[str, Any]]:
    category = category_get(cat_key)

    if not category:
        return None

    brands = category.get("brands", {})
    if not isinstance(brands, dict):
        return None

    return brands.get(brand_key)


def items_get(container: Dict[str, Any]) -> List[Any]:
    items = container.get("items", [])
    return items if isinstance(items, list) else []


def parse_idx(value: str) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def has_city(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(context.user_data.get("city_key"))


def get_active_menu_id(context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    return context.user_data.get("active_menu_message_id")


def set_active_menu_id(
    context: ContextTypes.DEFAULT_TYPE,
    message_id: Optional[int],
) -> None:
    context.user_data["active_menu_message_id"] = message_id

# =========================================================
# UI HELPERS
# =========================================================


async def answer_callback(update: Update) -> None:
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass


async def delete_message_safe(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: Optional[int],
) -> None:
    if not message_id:
        return

    try:
        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=message_id,
        )
    except BadRequest as e:
        text = str(e).lower()
        if "message to delete not found" in text:
            return
        if "message can't be deleted" in text:
            return
        logger.exception("Delete message failed: %s", e)
    except Exception as e:
        logger.exception("Delete message failed: %s", e)


async def show_stale_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str = "⚠️ Це меню застаріло або вже недійсне. Я відкрив актуальне меню.",
) -> None:
    if has_city(context):
        await show_text(update, text, kb_main(), context=context)
        return

    await start(update, context)


def resolve_photo_source(photo: str) -> Tuple[Optional[str], Optional[Any]]:
    if not photo:
        logger.warning("Photo path is empty")
        return None, None

    if photo.startswith("http://") or photo.startswith("https://"):
        logger.info("Using remote photo: %s", photo)
        return "remote", photo

    path = (BASE_DIR / photo).resolve()

    if path.exists():
        logger.info("Using local photo: %s", path)
        return "local", path

    logger.warning("Photo file not found: %s", path)
    return None, None


async def show_text(
    update: Update,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    context: Optional[ContextTypes.DEFAULT_TYPE] = None,
    cleanup_user: bool = False,
) -> None:
    if update.callback_query:
        q = update.callback_query

        try:
            if q.message and q.message.photo:
                await q.edit_message_caption(
                    caption=text,
                    reply_markup=reply_markup,
                )
            else:
                await q.edit_message_text(
                    text=text,
                    reply_markup=reply_markup,
                )

            if context and q.message:
                set_active_menu_id(context, q.message.message_id)
            return

        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                return
        except Exception:
            logger.exception("show_text edit failed")

        if not q.message:
            return

        sent = await q.message.reply_text(
            text=text,
            reply_markup=reply_markup,
        )

        if context:
            previous_id = get_active_menu_id(context)
            set_active_menu_id(context, sent.message_id)

            if previous_id and previous_id != sent.message_id:
                await delete_message_safe(context, sent.chat_id, previous_id)

        return

    if update.message:
        previous_id = get_active_menu_id(context) if context else None

        sent = await update.message.reply_text(
            text=text,
            reply_markup=reply_markup,
        )

        if context:
            set_active_menu_id(context, sent.message_id)

            if previous_id and previous_id != sent.message_id:
                await delete_message_safe(context, sent.chat_id, previous_id)

            if cleanup_user:
                await delete_message_safe(
                    context,
                    update.effective_chat.id,
                    update.message.message_id,
                )


async def show_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    photo: str,
    caption: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    cleanup_user: bool = False,
) -> None:
    source_type, source = resolve_photo_source(photo)

    if source_type is None:
        await show_text(
            update,
            caption,
            reply_markup,
            context=context,
            cleanup_user=cleanup_user,
        )
        return

    try:
        if update.callback_query and update.callback_query.message:
            if source_type == "remote":
                await update.callback_query.edit_message_media(
                    media=InputMediaPhoto(media=source, caption=caption),
                    reply_markup=reply_markup,
                )
                set_active_menu_id(context, update.callback_query.message.message_id)
                return

            if source_type == "local":
                with open(source, "rb") as f:
                    await update.callback_query.edit_message_media(
                        media=InputMediaPhoto(
                            media=InputFile(f, filename=source.name),
                            caption=caption,
                        ),
                        reply_markup=reply_markup,
                    )
                set_active_menu_id(context, update.callback_query.message.message_id)
                return

    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            return
    except Exception as e:
        logger.exception("Photo send failed: %s", e)

    try:
        previous_id = get_active_menu_id(context)

        if source_type == "remote":
            sent = await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=source,
                caption=caption,
                reply_markup=reply_markup,
            )
        else:
            with open(source, "rb") as f:
                sent = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=InputFile(f, filename=source.name),
                    caption=caption,
                    reply_markup=reply_markup,
                )

        set_active_menu_id(context, sent.message_id)

        if previous_id and previous_id != sent.message_id:
            await delete_message_safe(context, sent.chat_id, previous_id)

        if cleanup_user and update.message:
            await delete_message_safe(
                context,
                update.effective_chat.id,
                update.message.message_id,
            )
        return

    except Exception as e:
        logger.exception("Photo send fallback failed: %s", e)

    await show_text(
        update,
        caption,
        reply_markup,
        context=context,
        cleanup_user=cleanup_user,
    )


async def send_message_safe(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
) -> bool:
    try:
        await context.bot.send_message(chat_id=chat_id, text=text)
        return True
    except Exception as e:
        logger.exception("Failed sending message to %s: %s", chat_id, e)
        return False


async def notify_targets(
    context: ContextTypes.DEFAULT_TYPE,
    recipients: List[int],
    text: str,
) -> Tuple[List[int], List[int]]:
    delivered: List[int] = []
    failed: List[int] = []

    for chat_id in recipients:
        if await send_message_safe(context, chat_id, text):
            delivered.append(chat_id)
        else:
            failed.append(chat_id)

    return delivered, failed

# =========================================================
# KEYBOARDS
# =========================================================


def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Каталог", callback_data="catalog")],
        [InlineKeyboardButton("🛒 Кошик", callback_data="cart")],
    ])


def kb_after_add() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Додати ще", callback_data="catalog")],
        [InlineKeyboardButton("🛒 Кошик", callback_data="cart")],
        [InlineKeyboardButton("⬅ На головну", callback_data="main")],
    ])

# =========================================================
# ITEM RESOLVER
# =========================================================


def resolve_item(key: str) -> Optional[Dict[str, Any]]:
    try:
        parts = key.split(":")
        kind = parts[0]

        if kind == "brand":
            if len(parts) != 4:
                return None

            _, cat_key, brand_key, idx = parts

            brand = brand_get(cat_key, brand_key)
            item_idx = parse_idx(idx)

            if not brand or item_idx is None:
                return None

            items = items_get(brand)
            if item_idx < 0 or item_idx >= len(items):
                return None

            item = items[item_idx]
            if not isinstance(item, dict):
                return None

            return {
                "key": key,
                "name": item["name"],
                "price": float(item["price"]),
                "photo": item.get("photo") or brand.get("photo"),
            }

        if kind == "nic":
            if len(parts) != 5:
                return None

            _, cat_key, brand_key, block_idx, flavor_idx = parts

            brand = brand_get(cat_key, brand_key)
            block_index = parse_idx(block_idx)
            flavor_index = parse_idx(flavor_idx)

            if not brand or block_index is None or flavor_index is None:
                return None

            brand_items = items_get(brand)
            if block_index < 0 or block_index >= len(brand_items):
                return None

            block = brand_items[block_index]
            if not isinstance(block, dict):
                return None

            flavors = items_get(block)
            if flavor_index < 0 or flavor_index >= len(flavors):
                return None

            flavor_name = extract_flavor_name(flavors[flavor_index])

            return {
                "key": key,
                "name": f"{brand.get('title')} {block.get('nicotine')} — {flavor_name}",
                "price": float(block["price"]),
                "photo": block.get("photo") or brand.get("photo"),
            }

        if kind == "flv":
            if len(parts) != 5:
                return None

            _, cat_key, brand_key, parent_idx, flavor_idx = parts

            brand = brand_get(cat_key, brand_key)
            parent_index = parse_idx(parent_idx)
            flavor_index = parse_idx(flavor_idx)

            if not brand or parent_index is None or flavor_index is None:
                return None

            brand_items = items_get(brand)
            if parent_index < 0 or parent_index >= len(brand_items):
                return None

            parent = brand_items[parent_index]
            if not isinstance(parent, dict):
                return None

            flavors = items_get(parent)
            if flavor_index < 0 or flavor_index >= len(flavors):
                return None

            flavor_name = extract_flavor_name(flavors[flavor_index])

            return {
                "key": key,
                "name": f"{parent.get('name')} — {flavor_name}",
                "price": float(parent["price"]),
                "photo": parent.get("photo") or brand.get("photo"),
            }

    except Exception as e:
        logger.exception("resolve_item failed: %s", e)

    return None

# =========================================================
# START
# =========================================================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📍 Берлін", callback_data="city:Berlin")],
        [InlineKeyboardButton("📍 Лейпциг", callback_data="city:Leipzig")],
        [InlineKeyboardButton("📍 Дрезден", callback_data="city:Dresden")],
        [InlineKeyboardButton("✍️ Інше місто", callback_data="city:Other")],
    ])

    await show_text(
        update,
        "👋 Вітаємо у ELF FOX\n\n📍 Оберіть ваше місто:",
        keyboard,
        context=context,
    )


async def city_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)

    q = update.callback_query
    if not q or not q.data:
        await show_stale_callback(update, context)
        return

    city_key = q.data.split(":", 1)[1]
    context.user_data["city_key"] = city_key

    if city_key == "Other":
        context.user_data["awaiting_city"] = True
        await show_text(update, "✍️ Напишіть назву вашого міста:", context=context)
        return

    await show_main(update, context)


async def show_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    city = get_city_title(context)

    await show_text(
        update,
        f"🦊 ELF FOX\n\n📍 Ваше місто: {city}\n\nОберіть дію:",
        kb_main(),
        context=context,
    )


async def main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    await show_main(update, context)

# =========================================================
# TEXT ROUTER
# =========================================================


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()

    if context.user_data.get("awaiting_city"):
        context.user_data["custom_city"] = text
        context.user_data["awaiting_city"] = False

        await show_main(update, context)
        await delete_message_safe(
            context,
            update.effective_chat.id,
            update.message.message_id,
        )
        return

    if context.user_data.get("reserve_key"):
        key = context.user_data["reserve_key"]
        item = resolve_item(key)

        if not item:
            await update.message.reply_text("❌ Товар не знайдено")
            return

        st = stock_get(key)

        reservation_text = (
            "📌 НОВЕ БРОНЮВАННЯ\n\n"
            f"👤 {get_username(update.effective_user)}\n"
            f"📍 Місто: {get_city_title(context)}\n\n"
            f"🧾 {item['name']}\n"
            f"💶 {fmt_price(item['price'])}\n"
            f"🗓 Очікується: {st.get('eta') or 'не вказано'}\n\n"
            f"💬 Контакт:\n{text}"
        )

        delivered, _ = await notify_targets(context, ADMIN_IDS, reservation_text)

        if not delivered:
            await show_text(
                update,
                "❌ Не вдалося передати бронювання. Спробуйте ще раз трохи пізніше.",
                kb_main(),
                context=context,
                cleanup_user=True,
            )
            return

        context.user_data.pop("reserve_key", None)

        await show_text(
            update,
            "✅ Бронювання передано адміну",
            kb_main(),
            context=context,
            cleanup_user=True,
        )
        return

    if not has_city(context):
        await start(update, context)
        await delete_message_safe(
            context,
            update.effective_chat.id,
            update.message.message_id,
        )
        return

    await show_text(
        update,
        "Я не очікував текст у цей момент. Скористайся кнопками нижче.",
        kb_main(),
        context=context,
        cleanup_user=True,
    )

# =========================================================
# CATALOG
# =========================================================


async def catalog_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)

    categories = categories_get()
    if not categories:
        await show_text(update, "❌ Каталог тимчасово недоступний", kb_main(), context=context)
        return

    keyboard = []

    for cat_key, cat in categories.items():
        keyboard.append([
            InlineKeyboardButton(cat["title"], callback_data=f"cat:{cat_key}")
        ])

    keyboard.append([
        InlineKeyboardButton("⬅ На головну", callback_data="main")
    ])

    await show_text(
        update,
        "🛍 Каталог\n\nОберіть категорію:",
        InlineKeyboardMarkup(keyboard),
        context=context,
    )


async def category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)

    q = update.callback_query
    if not q or not q.data:
        await show_stale_callback(update, context)
        return

    parts = q.data.split(":", 1)
    if len(parts) != 2:
        await show_stale_callback(update, context)
        return

    cat_key = parts[1]
    cat = category_get(cat_key)

    if not cat:
        await show_stale_callback(
            update,
            context,
            "❌ Категорію не знайдено. Відкрив актуальне меню.",
        )
        return

    brands = cat.get("brands", {})
    if not isinstance(brands, dict):
        await show_text(update, "❌ У категорії немає брендів", kb_main(), context=context)
        return

    keyboard = []

    for brand_key, brand in brands.items():
        keyboard.append([
            InlineKeyboardButton(
                brand["title"],
                callback_data=f"brand:{cat_key}:{brand_key}",
            )
        ])

    keyboard.append([
        InlineKeyboardButton("⬅ Назад", callback_data="catalog")
    ])

    await show_photo(
        update,
        context,
        cat.get("photo", ""),
        f"{cat['title']}\n\nОберіть бренд:",
        InlineKeyboardMarkup(keyboard),
    )


async def brand_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)

    q = update.callback_query
    if not q or not q.data:
        await show_stale_callback(update, context)
        return

    parts = q.data.split(":")
    if len(parts) != 3:
        await show_stale_callback(update, context)
        return

    _, cat_key, brand_key = parts
    brand = brand_get(cat_key, brand_key)

    if not brand:
        await show_stale_callback(
            update,
            context,
            "❌ Бренд не знайдено. Відкрив актуальне меню.",
        )
        return

    keyboard = []
    items = items_get(brand)

    for idx, item in enumerate(items):
        if isinstance(item, dict) and "nicotine" in item:
            keyboard.append([
                InlineKeyboardButton(
                    f"{item['nicotine']} — {fmt_price(item['price'])}",
                    callback_data=f"nic:{cat_key}:{brand_key}:{idx}",
                )
            ])
        elif isinstance(item, dict) and isinstance(item.get("items"), list):
            keyboard.append([
                InlineKeyboardButton(
                    f"{item['name']} — {fmt_price(item['price'])}",
                    callback_data=f"flavors:{cat_key}:{brand_key}:{idx}",
                )
            ])
        elif isinstance(item, dict):
            key = item_key("brand", cat_key, brand_key, idx)
            st = stock_get(key)

            if st.get("in_stock", True):
                label = f"{item['name']} — {fmt_price(item['price'])} ✅"
                callback = f"add:{key}"
            else:
                eta = st.get("eta")
                label = f"{item['name']} ❌"
                if eta:
                    label += f" ({eta})"
                callback = f"reserve:{key}"

            keyboard.append([
                InlineKeyboardButton(label, callback_data=callback)
            ])

    keyboard.append([
        InlineKeyboardButton("🛒 Кошик", callback_data="cart")
    ])
    keyboard.append([
        InlineKeyboardButton("⬅ Назад", callback_data=f"cat:{cat_key}")
    ])

    text = f"{brand['title']}"
    if brand.get("price_range"):
        text += f"\n💶 {brand['price_range']}"
    text += "\n\nОберіть товар:"

    await show_photo(
        update,
        context,
        brand.get("photo", ""),
        text,
        InlineKeyboardMarkup(keyboard),
    )


async def nicotine_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)

    q = update.callback_query
    if not q or not q.data:
        await show_stale_callback(update, context)
        return

    parts = q.data.split(":")
    if len(parts) != 4:
        await show_stale_callback(update, context)
        return

    _, cat_key, brand_key, block_idx = parts

    brand = brand_get(cat_key, brand_key)
    block_index = parse_idx(block_idx)

    if not brand or block_index is None:
        await show_stale_callback(update, context)
        return

    brand_items = items_get(brand)
    if block_index < 0 or block_index >= len(brand_items):
        await show_stale_callback(update, context)
        return

    block = brand_items[block_index]
    if not isinstance(block, dict):
        await show_stale_callback(update, context)
        return

    keyboard = []

    for idx, flavor in enumerate(items_get(block)):
        flavor_name = extract_flavor_name(flavor)
        key = item_key("nic", cat_key, brand_key, block_idx, idx)
        st = stock_get(key)

        if st.get("in_stock", True):
            label = f"{flavor_name} ✅"
            callback = f"add:{key}"
        else:
            eta = st.get("eta")
            label = f"{flavor_name} ❌"
            if eta:
                label += f" ({eta})"
            callback = f"reserve:{key}"

        keyboard.append([
            InlineKeyboardButton(label, callback_data=callback)
        ])

    keyboard.append([
        InlineKeyboardButton("⬅ Назад", callback_data=f"brand:{cat_key}:{brand_key}")
    ])

    await show_photo(
        update,
        context,
        block.get("photo") or brand.get("photo", ""),
        f"{brand['title']} {block['nicotine']}\n\nОберіть смак:",
        InlineKeyboardMarkup(keyboard),
    )


async def flavors_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)

    q = update.callback_query
    if not q or not q.data:
        await show_stale_callback(update, context)
        return

    parts = q.data.split(":")
    if len(parts) != 4:
        await show_stale_callback(update, context)
        return

    _, cat_key, brand_key, parent_idx = parts

    brand = brand_get(cat_key, brand_key)
    parent_index = parse_idx(parent_idx)

    if not brand or parent_index is None:
        await show_stale_callback(update, context)
        return

    brand_items = items_get(brand)
    if parent_index < 0 or parent_index >= len(brand_items):
        await show_stale_callback(update, context)
        return

    parent = brand_items[parent_index]
    if not isinstance(parent, dict):
        await show_stale_callback(update, context)
        return

    keyboard = []

    for idx, flavor in enumerate(items_get(parent)):
        flavor_name = extract_flavor_name(flavor)
        key = item_key("flv", cat_key, brand_key, parent_idx, idx)
        st = stock_get(key)

        if st.get("in_stock", True):
            label = f"{flavor_name} ✅"
            callback = f"add:{key}"
        else:
            eta = st.get("eta")
            label = f"{flavor_name} ❌"
            if eta:
                label += f" ({eta})"
            callback = f"reserve:{key}"

        keyboard.append([
            InlineKeyboardButton(label, callback_data=callback)
        ])

    keyboard.append([
        InlineKeyboardButton("⬅ Назад", callback_data=f"brand:{cat_key}:{brand_key}")
    ])

    await show_photo(
        update,
        context,
        parent.get("photo") or brand.get("photo", ""),
        f"{parent['name']}\n\nОберіть смак:",
        InlineKeyboardMarkup(keyboard),
    )

# =========================================================
# ADD / RESERVE
# =========================================================


async def add_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)

    q = update.callback_query
    if not q or not q.data:
        await show_stale_callback(update, context)
        return

    key = q.data.split(":", 1)[1]
    item = resolve_item(key)

    if not item:
        await show_text(update, "❌ Товар не знайдено", context=context)
        return

    st = stock_get(key)
    if not st.get("in_stock", True):
        await show_text(
            update,
            "❌ Цього товару вже немає в наявності",
            kb_main(),
            context=context,
        )
        return

    cart = cart_get(context)
    cart.append({
        "key": item["key"],
        "name": item["name"],
        "price": item["price"],
    })

    await show_photo(
        update,
        context,
        item.get("photo", ""),
        "✅ Додано в кошик\n\n"
        f"🧾 {item['name']}\n"
        f"💶 {fmt_price(item['price'])}",
        kb_after_add(),
    )


async def reserve_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)

    q = update.callback_query
    if not q or not q.data:
        await show_stale_callback(update, context)
        return

    key = q.data.split(":", 1)[1]
    item = resolve_item(key)

    if not item:
        await show_text(update, "❌ Товар не знайдено", context=context)
        return

    st = stock_get(key)
    context.user_data["reserve_key"] = key

    await show_text(
        update,
        "📌 Бронювання\n\n"
        f"🧾 {item['name']}\n"
        f"💶 {fmt_price(item['price'])}\n"
        f"🗓 Очікується: {st.get('eta') or 'дату уточнюйте'}\n\n"
        "✍️ Напишіть контакт або коментар:",
        context=context,
    )

# =========================================================
# CART
# =========================================================


async def cart_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)

    cart = cart_get(context)

    if not cart:
        await show_text(
            update,
            "🛒 Кошик порожній",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🛍 Каталог", callback_data="catalog")],
                [InlineKeyboardButton("⬅ На головну", callback_data="main")],
            ]),
            context=context,
        )
        return

    lines = [
        f"{idx + 1}. {item['name']} — {fmt_price(item['price'])}"
        for idx, item in enumerate(cart)
    ]

    text = (
        "🛒 Ваше замовлення:\n\n"
        + "\n".join(lines)
        + f"\n\n💰 Разом: {fmt_price(cart_total(cart))}"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Додати ще", callback_data="catalog")],
        [InlineKeyboardButton("➖ Прибрати останній", callback_data="remove_last")],
        [InlineKeyboardButton("🗑 Очистити кошик", callback_data="clear_cart")],
        [InlineKeyboardButton("✅ Оформити", callback_data="checkout")],
        [InlineKeyboardButton("⬅ На головну", callback_data="main")],
    ])

    await show_text(update, text, keyboard, context=context)


async def remove_last_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)

    cart = cart_get(context)
    if cart:
        cart.pop()

    await cart_handler(update, context)


async def clear_cart_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)

    context.user_data["cart"] = []

    await show_text(
        update,
        "🗑 Кошик очищено",
        kb_main(),
        context=context,
    )

# =========================================================
# CHECKOUT
# =========================================================


async def checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)

    if context.user_data.get("checkout_in_progress"):
        await show_text(
            update,
            "⏳ Замовлення вже обробляється. Зачекай кілька секунд.",
            context=context,
        )
        return

    context.user_data["checkout_in_progress"] = True

    try:
        user = update.effective_user
        cart = cart_get(context)

        if not cart:
            await show_text(update, "🛒 Кошик порожній", context=context)
            return

        unavailable = []

        for item in cart:
            st = stock_get(item["key"])
            if not st.get("in_stock", True):
                unavailable.append(item["name"])

        if unavailable:
            await show_text(
                update,
                "❌ Деякі товари вже не в наявності:\n\n"
                + "\n".join(f"• {x}" for x in unavailable),
                kb_main(),
                context=context,
            )
            return

        city = get_city_title(context)
        city_cfg = get_city_config(context)

        order_id = f"{user.id}-{int(datetime.now().timestamp())}"
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")

        items_text = "\n".join(
            f"• {item['name']} — {fmt_price(item['price'])}"
            for item in cart
        )

        order_text = (
            "📦 НОВЕ ЗАМОВЛЕННЯ\n\n"
            f"🆔 ID: {order_id}\n"
            f"👤 {get_username(user)}\n"
            f"📍 Місто: {city}\n\n"
            f"🛒 Товари:\n{items_text}\n\n"
            f"💰 Разом: {fmt_price(cart_total(cart))}\n"
            f"🕒 {timestamp}"
        )

        delivered_admins, failed_admins = await notify_targets(
            context,
            ADMIN_IDS,
            order_text,
        )

        courier_sent = await send_message_safe(
            context,
            city_cfg["courier_chat_id"],
            order_text,
        )

        if not delivered_admins and not courier_sent:
            await show_text(
                update,
                "❌ Не вдалося передати замовлення. Кошик збережено, спробуй ще раз трохи пізніше.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 Кошик", callback_data="cart")],
                    [InlineKeyboardButton("⬅ На головну", callback_data="main")],
                ]),
                context=context,
            )
            return

        save_order({
            "order_id": order_id,
            "city": city,
            "user_id": user.id,
            "items": cart,
            "total": cart_total(cart),
            "created_at": timestamp,
            "courier_sent": courier_sent,
            "admin_delivered": delivered_admins,
            "admin_failed": failed_admins,
        })

        context.user_data["cart"] = []

        if courier_sent:
            success_text = (
                "✅ Дякуємо за замовлення\n\n"
                f"Курʼєр звʼяжеться з вами:\n{city_cfg['courier_username']}"
            )
        else:
            success_text = (
                "✅ Замовлення прийнято\n\n"
                "Курʼєру не вдалося відправити повідомлення автоматично, "
                "але адміністратор уже отримав замовлення і звʼяжеться з вами."
            )

        await show_text(
            update,
            success_text,
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🛍 Каталог", callback_data="catalog")],
                [InlineKeyboardButton("⬅ На головну", callback_data="main")],
            ]),
            context=context,
        )
    finally:
        context.user_data.pop("checkout_in_progress", None)

# =========================================================
# FALLBACKS / ERRORS
# =========================================================


async def unknown_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    await show_stale_callback(update, context)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception: %s", context.error)

# =========================================================
# MAIN
# =========================================================


def build_application() -> Application:
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(False)
        .build()
    )

    app.add_handler(CommandHandler("start", start))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_router,
        )
    )

    app.add_handler(CallbackQueryHandler(city_handler, pattern=r"^city:"))
    app.add_handler(CallbackQueryHandler(main_handler, pattern=r"^main$"))

    app.add_handler(CallbackQueryHandler(catalog_handler, pattern=r"^catalog$"))
    app.add_handler(CallbackQueryHandler(category_handler, pattern=r"^cat:"))
    app.add_handler(CallbackQueryHandler(brand_handler, pattern=r"^brand:"))
    app.add_handler(CallbackQueryHandler(nicotine_handler, pattern=r"^nic:"))
    app.add_handler(CallbackQueryHandler(flavors_handler, pattern=r"^flavors:"))

    app.add_handler(CallbackQueryHandler(add_handler, pattern=r"^add:"))
    app.add_handler(CallbackQueryHandler(reserve_handler, pattern=r"^reserve:"))

    app.add_handler(CallbackQueryHandler(cart_handler, pattern=r"^cart$"))
    app.add_handler(CallbackQueryHandler(remove_last_handler, pattern=r"^remove_last$"))
    app.add_handler(CallbackQueryHandler(clear_cart_handler, pattern=r"^clear_cart$"))
    app.add_handler(CallbackQueryHandler(checkout_handler, pattern=r"^checkout$"))

    app.add_handler(CallbackQueryHandler(unknown_callback_handler))
    app.add_error_handler(error_handler)

    return app


def main() -> None:
    app = build_application()

    logger.info("Bot started")
    app.run_polling(
        close_loop=False,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
