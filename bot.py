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


CATALOG = load_catalog()


def save_catalog() -> bool:
    return write_json(CATALOG_PATH, CATALOG)


def save_order(order: dict[str, Any]) -> None:
    orders = read_json(ORDERS_PATH, [])
    if not isinstance(orders, list):
        orders = []
    orders.append(order)
    write_json(ORDERS_PATH, orders[-1000:])


# ---------------------------------------------------------
# CATALOG HELPERS
# ---------------------------------------------------------

def categories() -> dict[str, Any]:
    return CATALOG["categories"]


def category_get(category_key: str) -> Optional[dict[str, Any]]:
    category = categories().get(category_key)
    return category if isinstance(category, dict) else None


def brands_get(category_key: str) -> dict[str, Any]:
    category = category_get(category_key)
    if not category:
        return {}
    brands = category.get("brands")
    return brands if isinstance(brands, dict) else {}


def brand_get(category_key: str, brand_key: str) -> Optional[dict[str, Any]]:
    brand = brands_get(category_key).get(brand_key)
    return brand if isinstance(brand, dict) else None


def items_get(container: dict[str, Any]) -> list[Any]:
    items = container.get("items", [])
    return items if isinstance(items, list) else []


def currency() -> str:
    return str(CATALOG.get("currency", "EUR"))


def price_text(price: Any) -> str:
    try:
        return f"{float(price):g} {currency()}"
    except (ValueError, TypeError):
        return f"{price} {currency()}"


def cart_get(context: ContextTypes.DEFAULT_TYPE) -> list[dict[str, Any]]:
    return context.user_data.setdefault("cart", [])


def cart_total(cart: list[dict[str, Any]]) -> float:
    return round(sum(float(item["price"]) for item in cart), 2)


def parse_index(value: str) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def variant_name(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("name") or value.get("title") or "Без назви")
    return str(value)


def is_available(item: dict[str, Any]) -> bool:
    # Existing products without this field are considered available.
    return item.get("in_stock", True) is True


def set_available(item: dict[str, Any], available: bool) -> None:
    item["in_stock"] = available


def find_direct_product(
    category_key: str, brand_key: str, item_index: int
) -> Optional[dict[str, Any]]:
    brand = brand_get(category_key, brand_key)
    if not brand:
        return None
    products = items_get(brand)
    if not 0 <= item_index < len(products):
        return None
    product = products[item_index]
    if not isinstance(product, dict) or "name" not in product or "price" not in product:
        return None
    return product


def unique_key(prefix: str, collection: dict[str, Any]) -> str:
    number = 1
    while f"{prefix}_{number}" in collection:
        number += 1
    return f"{prefix}_{number}"


# ---------------------------------------------------------
# UI HELPERS
# ---------------------------------------------------------

def main_keyboard(user_id: Optional[int]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("🛍 Каталог", callback_data="catalog")],
        [InlineKeyboardButton("🛒 Кошик", callback_data="cart")],
    ]
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton("⚙️ Адмін-панель", callback_data="admin")])
    return InlineKeyboardMarkup(buttons)


async def answer_callback(update: Update) -> None:
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except BadRequest:
            pass


async def show_text(
    update: Update,
    text: str,
    keyboard: Optional[InlineKeyboardMarkup] = None,
) -> None:
    query = update.callback_query
    if query:
        try:
            await query.edit_message_text(text=text, reply_markup=keyboard)
            return
        except BadRequest as error:
            if "message is not modified" in str(error).lower():
                return
            logger.info("Message edit failed: %s", error)
    if update.effective_chat:
        await update.effective_chat.send_message(text=text, reply_markup=keyboard)


async def show_product(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    product: dict[str, Any],
    callback: str,
    back_callback: str,
) -> None:
    status = "✅ В наявності" if is_available(product) else "❌ Немає в наявності"
    text = f"🧾 {product['name']}\n💶 {price_text(product['price'])}\n{status}"
    buttons = []
    if is_available(product):
        buttons.append([InlineKeyboardButton("🛒 Додати в кошик", callback_data=callback)])
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data=back_callback)])
    keyboard = InlineKeyboardMarkup(buttons)

    # A Telegram file_id is saved after an admin uploads a picture. It is reliable
    # and does not require keeping image files on Railway.
    photo_id = product.get("photo")
    if photo_id and update.effective_chat:
        try:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=photo_id,
                caption=text,
                reply_markup=keyboard,
            )
            return
        except Exception as error:
            logger.warning("Cannot send product photo: %s", error)
    await show_text(update, text, keyboard)


def admin_allowed(update: Update) -> bool:
    return bool(update.effective_user and update.effective_user.id == ADMIN_ID)


async def deny_admin(update: Update) -> None:
    await answer_callback(update)
    await show_text(update, "⛔ Доступ до адмін-панелі заборонено.", main_keyboard(None))


# ---------------------------------------------------------
# CUSTOMER FLOW: CATALOG -> PRODUCT -> CART -> ORDER
# ---------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    user_id = update.effective_user.id if update.effective_user else None
    await show_text(update, "👋 Вітаємо!\n\nОберіть дію:", main_keyboard(user_id))


async def main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    user_id = update.effective_user.id if update.effective_user else None
    await show_text(update, "Оберіть дію:", main_keyboard(user_id))


async def catalog_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    buttons = [
        [InlineKeyboardButton(str(category.get("title", key)), callback_data=f"category:{key}")]
        for key, category in categories().items()
        if isinstance(category, dict)
    ]
    if not buttons:
        await show_text(update, "❌ Каталог поки порожній.", main_keyboard(None))
        return
    buttons.append([InlineKeyboardButton("⬅️ Головне меню", callback_data="main")])
    await show_text(update, "🛍 Каталог\n\nОберіть категорію:", InlineKeyboardMarkup(buttons))


async def category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    query = update.callback_query
    category_key = query.data.split(":", 1)[1] if query and query.data else ""
    category = category_get(category_key)
    if not category:
        await show_text(update, "❌ Категорію не знайдено.", main_keyboard(None))
        return
    brands = brands_get(category_key)
    buttons = [
        [InlineKeyboardButton(str(brand.get("title", key)), callback_data=f"brand:{category_key}:{key}")]
        for key, brand in brands.items()
        if isinstance(brand, dict)
    ]
    if not buttons:
        await show_text(update, "❌ У категорії поки немає товарів.", main_keyboard(None))
        return
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="catalog")])
    await show_text(
        update,
        f"{category.get('title', 'Категорія')}\n\nОберіть бренд:",
        InlineKeyboardMarkup(buttons),
    )


async def brand_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    query = update.callback_query
    parts = query.data.split(":") if query and query.data else []
    if len(parts) != 3:
        await show_text(update, "❌ Товар не знайдено.", main_keyboard(None))
        return
    _, category_key, brand_key = parts
    brand = brand_get(category_key, brand_key)
    if not brand:
        await show_text(update, "❌ Бренд не знайдено.", main_keyboard(None))
        return
    buttons: list[list[InlineKeyboardButton]] = []
    for index, item in enumerate(items_get(brand)):
        if not isinstance(item, dict):
            continue
        if "nicotine" in item and isinstance(item.get("items"), list):
            label = f"{item['nicotine']} — {price_text(item.get('price', ''))}"
            callback = f"variants:{category_key}:{brand_key}:{index}"
        elif "name" in item and "price" in item:
            icon = "✅" if is_available(item) else "❌"
            label = f"{item['name']} — {price_text(item['price'])} {icon}"
            callback = f"product:{category_key}:{brand_key}:{index}"
        else:
            continue
        buttons.append([InlineKeyboardButton(label, callback_data=callback)])
    if not buttons:
        await show_text(update, "❌ У цьому бренді товарів поки немає.", main_keyboard(None))
        return
    buttons.extend([
        [InlineKeyboardButton("🛒 Кошик", callback_data="cart")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"category:{category_key}")],
    ])
    await show_text(update, f"{brand.get('title', 'Товари')}\n\nОберіть товар:", InlineKeyboardMarkup(buttons))


async def product_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    query = update.callback_query
    parts = query.data.split(":") if query and query.data else []
    if len(parts) != 4:
        await show_text(update, "❌ Товар не знайдено.", main_keyboard(None))
        return
    _, category_key, brand_key, index_text = parts
    index = parse_index(index_text)
    product = find_direct_product(category_key, brand_key, index) if index is not None else None
    if not product:
        await show_text(update, "❌ Товар не знайдено.", main_keyboard(None))
        return
    await show_product(
        update, context, product,
        f"add:direct:{category_key}:{brand_key}:{index}",
        f"brand:{category_key}:{brand_key}",
    )


async def variants_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    query = update.callback_query
    parts = query.data.split(":") if query and query.data else []
    if len(parts) != 4:
        await show_text(update, "❌ Товар не знайдено.", main_keyboard(None))
        return
    _, category_key, brand_key, parent_text = parts
    parent_index = parse_index(parent_text)
    brand = brand_get(category_key, brand_key)
    products = items_get(brand) if brand else []
    if parent_index is None or not 0 <= parent_index < len(products):
        await show_text(update, "❌ Товар не знайдено.", main_keyboard(None))
        return
    parent = products[parent_index]
    if not isinstance(parent, dict):
        await show_text(update, "❌ Товар не знайдено.", main_keyboard(None))
        return
    buttons = [
        [InlineKeyboardButton(variant_name(flavor), callback_data=f"add:variant:{category_key}:{brand_key}:{parent_index}:{number}")]
        for number, flavor in enumerate(items_get(parent))
    ]
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"brand:{category_key}:{brand_key}")])
    await show_text(update, f"{parent.get('nicotine', 'Варіанти')}\n\nОберіть смак:", InlineKeyboardMarkup(buttons))


def resolve_cart_item(key: str) -> Optional[dict[str, Any]]:
    parts = key.split(":")
    try:
        if parts[0] == "direct" and len(parts) == 4:
            _, category_key, brand_key, index_text = parts
            index = parse_index(index_text)
            product = find_direct_product(category_key, brand_key, index) if index is not None else None
            if product and is_available(product):
                return {"key": key, "name": str(product["name"]), "price": float(product["price"])}
        if parts[0] == "variant" and len(parts) == 5:
            _, category_key, brand_key, parent_text, flavor_text = parts
            parent_index, flavor_index = parse_index(parent_text), parse_index(flavor_text)
            brand = brand_get(category_key, brand_key)
            products = items_get(brand) if brand else []
            if parent_index is None or flavor_index is None or not 0 <= parent_index < len(products):
                return None
            parent = products[parent_index]
            if not isinstance(parent, dict):
                return None
            flavors = items_get(parent)
            if not 0 <= flavor_index < len(flavors):
                return None
            return {
                "key": key,
                "name": f"{brand.get('title', '')} {parent.get('nicotine', '')} — {variant_name(flavors[flavor_index])}",
                "price": float(parent["price"]),
            }
    except (KeyError, TypeError, ValueError):
        return None
    return None


async def add_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    query = update.callback_query
    key = query.data.split(":", 1)[1] if query and query.data else ""
    item = resolve_cart_item(key)
    if not item:
        await show_text(update, "❌ Товар недоступний або вже не існує.", main_keyboard(None))
        return
    cart_get(context).append(item)
    await show_text(
        update,
        f"✅ Додано в кошик\n\n🧾 {item['name']}\n💶 {price_text(item['price'])}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Додати ще", callback_data="catalog")],
            [InlineKeyboardButton("🛒 Перейти в кошик", callback_data="cart")],
        ]),
    )


async def cart_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    cart = cart_get(context)
    if not cart:
        await show_text(update, "🛒 Кошик порожній.", main_keyboard(None))
        return
    items = "\n".join(f"{number}. {item['name']} — {price_text(item['price'])}" for number, item in enumerate(cart, 1))
    await show_text(
        update,
        f"🛒 Ваше замовлення:\n\n{items}\n\n💰 Разом: {price_text(cart_total(cart))}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Додати ще", callback_data="catalog")],
            [InlineKeyboardButton("➖ Прибрати останній", callback_data="remove_last")],
            [InlineKeyboardButton("🗑 Очистити кошик", callback_data="clear_cart")],
            [InlineKeyboardButton("✅ Оформити замовлення", callback_data="checkout")],
        ]),
    )


async def remove_last_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    cart = cart_get(context)
    if cart:
        cart.pop()
    await cart_handler(update, context)


async def clear_cart_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    context.user_data["cart"] = []
    await show_text(update, "🗑 Кошик очищено.", main_keyboard(None))


async def checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    if context.user_data.get("checkout_in_progress"):
        return
    context.user_data["checkout_in_progress"] = True
    try:
        cart = cart_get(context)
        user = update.effective_user
        if not cart or not user:
            await show_text(update, "🛒 Кошик порожній.", main_keyboard(None))
            return
        now = datetime.now()
        order_id = f"{user.id}-{int(now.timestamp())}"
        customer = f"@{user.username}" if user.username else f"ID: {user.id}"
        items = "\n".join(f"• {item['name']} — {price_text(item['price'])}" for item in cart)
        order_text = (
            "📦 НОВЕ ЗАМОВЛЕННЯ\n\n"
            f"🆔 {order_id}\n👤 {customer}\n📛 {user.full_name}\n\n"
            f"🛒 Товари:\n{items}\n\n💰 Разом: {price_text(cart_total(cart))}\n"
            f"🕒 {now.strftime('%d.%m.%Y %H:%M')}"
        )
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=order_text)
        except Exception as error:
            logger.exception("Cannot deliver order: %s", error)
            await show_text(update, "❌ Не вдалося передати замовлення. Спробуйте пізніше.", main_keyboard(None))
            return
        save_order({
            "order_id": order_id, "user_id": user.id, "username": user.username,
            "full_name": user.full_name, "items": cart, "total": cart_total(cart),
            "created_at": now.isoformat(timespec="seconds"),
        })
        context.user_data["cart"] = []
        await show_text(update, "✅ Замовлення прийнято! Адміністратор зв’яжеться з вами.", main_keyboard(user.id))
    finally:
        context.user_data.pop("checkout_in_progress", None)


# ---------------------------------------------------------
# ADMIN PANEL — AVAILABLE ONLY TO ADMIN_ID
# ---------------------------------------------------------

async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    if not admin_allowed(update):
        await deny_admin(update)
        return
    context.user_data.pop("admin_flow", None)
    await show_text(
        update,
        "⚙️ Адмін-панель\n\nКеруйте каталогом:",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("📁 Додати категорію", callback_data="admin_add_category")],
            [InlineKeyboardButton("🏷 Додати бренд", callback_data="admin_add_brand")],
            [InlineKeyboardButton("➕ Додати товар", callback_data="admin_add_product")],
            [InlineKeyboardButton("🛠 Керувати товарами", callback_data="admin_manage")],
            [InlineKeyboardButton("⬅️ Головне меню", callback_data="main")],
        ]),
    )


async def admin_add_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    if not admin_allowed(update):
        await deny_admin(update)
        return
    context.user_data["admin_flow"] = {"step": "category_title"}
    await show_text(update, "📁 Надішліть назву нової категорії.\nНаприклад: 💧 Рідини")


async def admin_add_brand_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    if not admin_allowed(update):
        await deny_admin(update)
        return
    buttons = [
        [InlineKeyboardButton(str(category.get("title", key)), callback_data=f"admin_brand_category:{key}")]
        for key, category in categories().items() if isinstance(category, dict)
    ]
    if not buttons:
        await show_text(update, "Спочатку додайте категорію.", InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Адмін-панель", callback_data="admin")]]))
        return
    await show_text(update, "🏷 Виберіть категорію для бренду:", InlineKeyboardMarkup(buttons))


async def admin_brand_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    if not admin_allowed(update):
        await deny_admin(update)
        return
    query = update.callback_query
    category_key = query.data.split(":", 1)[1] if query and query.data else ""
    if not category_get(category_key):
        await show_text(update, "❌ Категорію не знайдено.")
        return
    context.user_data["admin_flow"] = {"step": "brand_title", "category_key": category_key}
    await show_text(update, "🏷 Надішліть назву бренду.\nНаприклад: Vaporesso XROS")


async def admin_add_product_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    if not admin_allowed(update):
        await deny_admin(update)
        return
    buttons = [
        [InlineKeyboardButton(str(category.get("title", key)), callback_data=f"admin_product_category:{key}")]
        for key, category in categories().items() if isinstance(category, dict) and brands_get(key)
    ]
    if not buttons:
        await show_text(update, "Спочатку додайте категорію і бренд.", InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Адмін-панель", callback_data="admin")]]))
        return
    await show_text(update, "➕ Виберіть категорію для нового товару:", InlineKeyboardMarkup(buttons))


async def admin_product_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    if not admin_allowed(update):
        await deny_admin(update)
        return
    query = update.callback_query
    category_key = query.data.split(":", 1)[1] if query and query.data else ""
    buttons = [
        [InlineKeyboardButton(str(brand.get("title", key)), callback_data=f"admin_product_brand:{category_key}:{key}")]
        for key, brand in brands_get(category_key).items() if isinstance(brand, dict)
    ]
    if not buttons:
        await show_text(update, "❌ У категорії немає брендів.")
        return
    await show_text(update, "Виберіть бренд:", InlineKeyboardMarkup(buttons))


async def admin_product_brand_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    if not admin_allowed(update):
        await deny_admin(update)
        return
    query = update.callback_query
    parts = query.data.split(":") if query and query.data else []
    if len(parts) != 3 or not brand_get(parts[1], parts[2]):
        await show_text(update, "❌ Бренд не знайдено.")
        return
    context.user_data["admin_flow"] = {"step": "product_name", "category_key": parts[1], "brand_key": parts[2]}
    await show_text(update, "➕ Надішліть назву товару.")


async def admin_manage_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    if not admin_allowed(update):
        await deny_admin(update)
        return
    buttons = [
        [InlineKeyboardButton(str(category.get("title", key)), callback_data=f"admin_manage_category:{key}")]
        for key, category in categories().items() if isinstance(category, dict) and brands_get(key)
    ]
    await show_text(update, "🛠 Виберіть категорію:", InlineKeyboardMarkup(buttons or [[InlineKeyboardButton("⚙️ Назад", callback_data="admin")]]))


async def admin_manage_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    if not admin_allowed(update):
        await deny_admin(update)
        return
    query = update.callback_query
    category_key = query.data.split(":", 1)[1] if query and query.data else ""
    buttons = [
        [InlineKeyboardButton(str(brand.get("title", key)), callback_data=f"admin_manage_brand:{category_key}:{key}")]
        for key, brand in brands_get(category_key).items() if isinstance(brand, dict)
    ]
    await show_text(update, "Виберіть бренд:", InlineKeyboardMarkup(buttons or [[InlineKeyboardButton("⚙️ Назад", callback_data="admin")]]))


async def admin_manage_brand_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    if not admin_allowed(update):
        await deny_admin(update)
        return
    query = update.callback_query
    parts = query.data.split(":") if query and query.data else []
    if len(parts) != 3:
        await show_text(update, "❌ Бренд не знайдено.")
        return
    _, category_key, brand_key = parts
    brand = brand_get(category_key, brand_key)
    if not brand:
        await show_text(update, "❌ Бренд не знайдено.")
        return
    buttons = [
        [InlineKeyboardButton(f"{item['name']} {'✅' if is_available(item) else '❌'}", callback_data=f"admin_item:{category_key}:{brand_key}:{index}")]
        for index, item in enumerate(items_get(brand))
        if isinstance(item, dict) and "name" in item and "price" in item
    ]
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_manage")])
    await show_text(update, "Виберіть товар для редагування:", InlineKeyboardMarkup(buttons))


async def admin_item_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    if not admin_allowed(update):
        await deny_admin(update)
        return
    query = update.callback_query
    parts = query.data.split(":") if query and query.data else []
    index = parse_index(parts[3]) if len(parts) == 4 else None
    product = find_direct_product(parts[1], parts[2], index) if index is not None else None
    if not product:
        await show_text(update, "❌ Товар не знайдено.")
        return
    status = "в наявності ✅" if is_available(product) else "немає в наявності ❌"
    await show_text(
        update,
        f"🧾 {product['name']}\n💶 {price_text(product['price'])}\nСтатус: {status}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Змінити наявність", callback_data=f"admin_toggle:{parts[1]}:{parts[2]}:{index}")],
            [InlineKeyboardButton("🖼 Змінити фото", callback_data=f"admin_photo:{parts[1]}:{parts[2]}:{index}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"admin_manage_brand:{parts[1]}:{parts[2]}")],
        ]),
    )


async def admin_toggle_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    if not admin_allowed(update):
        await deny_admin(update)
        return
    query = update.callback_query
    parts = query.data.split(":") if query and query.data else []
    index = parse_index(parts[3]) if len(parts) == 4 else None
    product = find_direct_product(parts[1], parts[2], index) if index is not None else None
    if not product:
        await show_text(update, "❌ Товар не знайдено.")
        return
    set_available(product, not is_available(product))
    if save_catalog():
        await show_text(update, f"✅ Статус змінено: {'в наявності' if is_available(product) else 'немає в наявності'}.")
    else:
        await show_text(update, "❌ Не вдалося зберегти зміни.")


async def admin_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    if not admin_allowed(update):
        await deny_admin(update)
        return
    query = update.callback_query
    parts = query.data.split(":") if query and query.data else []
    if len(parts) != 4 or parse_index(parts[3]) is None:
        await show_text(update, "❌ Товар не знайдено.")
        return
    context.user_data["admin_flow"] = {"step": "replace_photo", "category_key": parts[1], "brand_key": parts[2], "item_index": int(parts[3])}
    await show_text(update, "🖼 Надішліть нове фото товару одним повідомленням.")


async def admin_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not admin_allowed(update) or not update.message or not update.message.text:
        return
    flow = context.user_data.get("admin_flow")
    if not isinstance(flow, dict):
        return
    text = update.message.text.strip()
    step = flow.get("step")
    if not text:
        return
    if step == "category_title":
        key = unique_key("category", categories())
        categories()[key] = {"title": text, "brands": {}}
        context.user_data.pop("admin_flow", None)
        save_catalog()
        await update.message.reply_text("✅ Категорію додано. Тепер можна додати бренд через /admin.")
    elif step == "brand_title":
        category = category_get(flow.get("category_key", ""))
        if not category:
            await update.message.reply_text("❌ Категорію не знайдено. Почніть заново: /admin")
            return
        brands = category.setdefault("brands", {})
        key = unique_key("brand", brands)
        brands[key] = {"title": text, "items": []}
        context.user_data.pop("admin_flow", None)
        save_catalog()
        await update.message.reply_text("✅ Бренд додано. Тепер можна додати товар через /admin.")
    elif step == "product_name":
        flow["name"] = text
        flow["step"] = "product_price"
        await update.message.reply_text("💶 Надішліть ціну цифрами, наприклад: 19.99")
    elif step == "product_price":
        try:
            price = float(text.replace(",", "."))
            if price < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Вкажіть коректну ціну: наприклад 19 або 19.99")
            return
        flow["price"] = price
        flow["step"] = "product_photo"
        await update.message.reply_text("🖼 Надішліть фото товару або напишіть «пропустити».")
    elif step == "product_photo" and text.lower() in {"пропустити", "-", "skip"}:
        flow["step"] = "product_availability"
        await update.message.reply_text("Товар у наявності? Напишіть: так або ні")
    elif step == "product_availability":
        answer = text.lower()
        if answer not in {"так", "ні", "yes", "no"}:
            await update.message.reply_text("Напишіть лише «так» або «ні».")
            return
        brand = brand_get(flow.get("category_key", ""), flow.get("brand_key", ""))
        if not brand:
            await update.message.reply_text("❌ Бренд не знайдено. Почніть заново: /admin")
            return
        product = {"name": flow["name"], "price": flow["price"], "in_stock": answer in {"так", "yes"}}
        if flow.get("photo"):
            product["photo"] = flow["photo"]
        brand.setdefault("items", []).append(product)
        context.user_data.pop("admin_flow", None)
        save_catalog()
        await update.message.reply_text("✅ Товар додано до каталогу.")


async def admin_photo_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not admin_allowed(update) or not update.message or not update.message.photo:
        return
    flow = context.user_data.get("admin_flow")
    if not isinstance(flow, dict):
        return
    photo_id = update.message.photo[-1].file_id
    if flow.get("step") == "product_photo":
        flow["photo"] = photo_id
        flow["step"] = "product_availability"
        await update.message.reply_text("Товар у наявності? Напишіть: так або ні")
    elif flow.get("step") == "replace_photo":
        product = find_direct_product(flow.get("category_key", ""), flow.get("brand_key", ""), flow.get("item_index", -1))
        if not product:
            await update.message.reply_text("❌ Товар не знайдено. Почніть заново: /admin")
            return
        product["photo"] = photo_id
        context.user_data.pop("admin_flow", None)
        if save_catalog():
            await update.message.reply_text("✅ Фото товару оновлено.")
        else:
            await update.message.reply_text("❌ Не вдалося зберегти фото.")


async def unknown_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    user_id = update.effective_user.id if update.effective_user else None
    await show_text(update, "Це меню вже неактуальне.", main_keyboard(user_id))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception: %s", context.error)


async def post_init(application: Application) -> None:
    """Polling cannot work while this bot has an active webhook."""
    await application.bot.delete_webhook(drop_pending_updates=True)
    logger.info("Telegram webhook cleared; polling is ready")


def build_application() -> Application:
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(False)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_handler))
    app.add_handler(CallbackQueryHandler(main_handler, pattern=r"^main$"))
    app.add_handler(CallbackQueryHandler(catalog_handler, pattern=r"^catalog$"))
    app.add_handler(CallbackQueryHandler(category_handler, pattern=r"^category:"))
    app.add_handler(CallbackQueryHandler(brand_handler, pattern=r"^brand:"))
    app.add_handler(CallbackQueryHandler(product_handler, pattern=r"^product:"))
    app.add_handler(CallbackQueryHandler(variants_handler, pattern=r"^variants:"))
    app.add_handler(CallbackQueryHandler(add_handler, pattern=r"^add:"))
    app.add_handler(CallbackQueryHandler(cart_handler, pattern=r"^cart$"))
    app.add_handler(CallbackQueryHandler(remove_last_handler, pattern=r"^remove_last$"))
    app.add_handler(CallbackQueryHandler(clear_cart_handler, pattern=r"^clear_cart$"))
    app.add_handler(CallbackQueryHandler(checkout_handler, pattern=r"^checkout$"))
    app.add_handler(CallbackQueryHandler(admin_handler, pattern=r"^admin$"))
    app.add_handler(CallbackQueryHandler(admin_add_category_handler, pattern=r"^admin_add_category$"))
    app.add_handler(CallbackQueryHandler(admin_add_brand_handler, pattern=r"^admin_add_brand$"))
    app.add_handler(CallbackQueryHandler(admin_brand_category_handler, pattern=r"^admin_brand_category:"))
    app.add_handler(CallbackQueryHandler(admin_add_product_handler, pattern=r"^admin_add_product$"))
    app.add_handler(CallbackQueryHandler(admin_product_category_handler, pattern=r"^admin_product_category:"))
    app.add_handler(CallbackQueryHandler(admin_product_brand_handler, pattern=r"^admin_product_brand:"))
    app.add_handler(CallbackQueryHandler(admin_manage_handler, pattern=r"^admin_manage$"))
    app.add_handler(CallbackQueryHandler(admin_manage_category_handler, pattern=r"^admin_manage_category:"))
    app.add_handler(CallbackQueryHandler(admin_manage_brand_handler, pattern=r"^admin_manage_brand:"))
    app.add_handler(CallbackQueryHandler(admin_item_handler, pattern=r"^admin_item:"))
    app.add_handler(CallbackQueryHandler(admin_toggle_handler, pattern=r"^admin_toggle:"))
    app.add_handler(CallbackQueryHandler(admin_photo_handler, pattern=r"^admin_photo:"))
    app.add_handler(MessageHandler(filters.PHOTO, admin_photo_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_text_router))
    app.add_handler(CallbackQueryHandler(unknown_callback_handler))
    app.add_error_handler(error_handler)
    return app


def main() -> None:
    logger.info("Bot started")
    build_application().run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
