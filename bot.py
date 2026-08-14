import json
import logging
import os
import re
import shutil
from datetime import datetime, date
from pathlib import Path
from typing import Any, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("RAILWAY_VOLUME_MOUNT_PATH", BASE_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)

SEED_CATALOG_PATH = BASE_DIR / "catalog.json"
CATALOG_PATH = DATA_DIR / "catalog.json"
ORDERS_PATH = DATA_DIR / "orders.json"
USERS_PATH = DATA_DIR / "users.json"

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 7212962967
ORDER_ADMIN_IDS = (7212962967, 5522897576)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============================================================
# LOCALIZATION
# ============================================================

LANGS = {
    "uk": "🇺🇦 Українська",
    "ru": "🇷🇺 Русский",
    "de": "🇩🇪 Deutsch",
    "en": "🇬🇧 English",
}

T = {
    "uk": {
        "welcome": "👋 Вітаємо! Рада вас бачити.\n\nОберіть мову:",
        "language_saved": "Мову збережено.",
        "menu": "Оберіть дію:",
        "catalog": "🛍 Каталог",
        "cart": "🛒 Кошик",
        "empty_catalog": "❌ Каталог поки порожній.",
        "choose_category": "Оберіть категорію:",
        "choose_brand": "Оберіть бренд:",
        "no_products": "❌ У цій категорії поки немає товарів.",
        "back": "⬅️ Назад",
        "home": "🏠 Головне меню",
        "available": "✅ В наявності",
        "unavailable": "❌ Немає в наявності",
        "add_cart": "🛒 Додати в кошик",
        "added": "✅ Товар додано в кошик.",
        "add_more": "➕ Додати ще",
        "go_cart": "🛒 Перейти в кошик",
        "cart_empty": "🛒 Кошик порожній.",
        "remove_last": "➖ Прибрати останній",
        "clear_cart": "🗑 Очистити кошик",
        "checkout": "✅ Оформити замовлення",
        "total": "Разом",
        "order_start": "📦 Оформлення замовлення\n\nВкажіть місто або район доставки:",
        "order_date": "📅 Вкажіть дату отримання у форматі ДД.ММ.РРРР.\nНаприклад: 25.08.2026",
        "order_time": "🕒 Вкажіть бажаний час отримання.\nНаприклад: 18:30 або 18:00-19:00",
        "order_confirm": "Перевірте замовлення:",
        "confirm": "✅ Підтвердити",
        "cancel": "❌ Скасувати",
        "order_cancelled": "Оформлення скасовано.",
        "bad_date": "❌ Некоректна дата. Використайте ДД.ММ.РРРР і дату не раніше сьогодні.",
        "bad_time": "❌ Некоректний час. Наприклад: 18:30 або 18:00-19:00.",
        "city_too_short": "❌ Вкажіть місто або район трохи детальніше.",
        "order_sent": "✅ Замовлення прийнято!\n\nМи отримали ваші дані та зв’яжемося з вами для підтвердження.",
        "order_failed": "❌ Не вдалося передати замовлення. Спробуйте ще раз пізніше.",
        "not_found": "❌ Товар не знайдено.",
        "language": "🌐 Мова",
        "choose_language": "Оберіть мову:",
        "admin_denied": "⛔ Доступ заборонено.",
        "admin": "⚙️ Адмін-панель",
        "admin_categories": "📁 Категорії",
        "admin_add_category": "➕ Додати категорію",
        "admin_edit_category": "✏️ Редагувати категорію",
        "admin_delete_category": "🗑 Видалити категорію",
        "admin_add_product": "➕ Додати товар",
        "admin_manage_products": "🛠 Товари",
        "admin_broadcast": "📣 Розсилка",
        "admin_stats": "📊 Статистика",
        "admin_back": "⬅️ Адмін-панель",
        "admin_category_name": "Надішліть назву категорії.",
        "admin_category_photo": "Надішліть фото категорії або напишіть «пропустити».",
        "admin_product_name": "Надішліть назву товару.",
        "admin_product_price": "Надішліть ціну, наприклад 19.99",
        "admin_product_photo": "Надішліть фото товару або напишіть «пропустити».",
        "admin_product_stock": "Товар є в наявності? Напишіть: так або ні.",
        "admin_saved": "✅ Зміни збережено.",
        "admin_deleted": "✅ Видалено.",
        "admin_broadcast_text": "📣 Надішліть текст розсилки.\n\nПісля отримання тексту я покажу попередній перегляд.",
        "admin_broadcast_confirm": "Надіслати цю розсилку всім користувачам?",
        "admin_broadcast_done": "📣 Розсилку завершено.",
        "admin_no_categories": "Категорій ще немає.",
        "admin_no_products": "Товарів ще немає.",
        "skip": "пропустити",
    },
    "ru": {
        "welcome": "👋 Добро пожаловать!\n\nВыберите язык:",
        "language_saved": "Язык сохранён.",
        "menu": "Выберите действие:",
        "catalog": "🛍 Каталог",
        "cart": "🛒 Корзина",
        "empty_catalog": "❌ Каталог пока пуст.",
        "choose_category": "Выберите категорию:",
        "choose_brand": "Выберите бренд:",
        "no_products": "❌ В этой категории пока нет товаров.",
        "back": "⬅️ Назад",
        "home": "🏠 Главное меню",
        "available": "✅ В наличии",
        "unavailable": "❌ Нет в наличии",
        "add_cart": "🛒 Добавить в корзину",
        "added": "✅ Товар добавлен в корзину.",
        "add_more": "➕ Добавить ещё",
        "go_cart": "🛒 Перейти в корзину",
        "cart_empty": "🛒 Корзина пуста.",
        "remove_last": "➖ Убрать последний",
        "clear_cart": "🗑 Очистить корзину",
        "checkout": "✅ Оформить заказ",
        "total": "Итого",
        "order_start": "📦 Оформление заказа\n\nУкажите город или район доставки:",
        "order_date": "📅 Укажите дату получения в формате ДД.ММ.ГГГГ.\nНапример: 25.08.2026",
        "order_time": "🕒 Укажите желаемое время получения.\nНапример: 18:30 или 18:00-19:00",
        "order_confirm": "Проверьте заказ:",
        "confirm": "✅ Подтвердить",
        "cancel": "❌ Отменить",
        "order_cancelled": "Оформление отменено.",
        "bad_date": "❌ Некорректная дата. Используйте ДД.ММ.ГГГГ и дату не раньше сегодня.",
        "bad_time": "❌ Некорректное время. Например: 18:30 или 18:00-19:00.",
        "city_too_short": "❌ Укажите город или район подробнее.",
        "order_sent": "✅ Заказ принят!\n\nМы получили ваши данные и свяжемся с вами для подтверждения.",
        "order_failed": "❌ Не удалось передать заказ. Попробуйте позже.",
        "not_found": "❌ Товар не найден.",
        "language": "🌐 Язык",
        "choose_language": "Выберите язык:",
        "admin_denied": "⛔ Доступ запрещён.",
        "admin": "⚙️ Админ-панель",
        "admin_categories": "📁 Категории",
        "admin_add_category": "➕ Добавить категорию",
        "admin_edit_category": "✏️ Изменить категорию",
        "admin_delete_category": "🗑 Удалить категорию",
        "admin_add_product": "➕ Добавить товар",
        "admin_manage_products": "🛠 Товары",
        "admin_broadcast": "📣 Рассылка",
        "admin_stats": "📊 Статистика",
        "admin_back": "⬅️ Админ-панель",
        "admin_category_name": "Отправьте название категории.",
        "admin_category_photo": "Отправьте фото категории или напишите «пропустить».",
        "admin_product_name": "Отправьте название товара.",
        "admin_product_price": "Отправьте цену, например 19.99",
        "admin_product_photo": "Отправьте фото товара или напишите «пропустить».",
        "admin_product_stock": "Товар есть в наличии? Напишите: да или нет.",
        "admin_saved": "✅ Изменения сохранены.",
        "admin_deleted": "✅ Удалено.",
        "admin_broadcast_text": "📣 Отправьте текст рассылки.\n\nПосле этого я покажу предварительный просмотр.",
        "admin_broadcast_confirm": "Отправить эту рассылку всем пользователям?",
        "admin_broadcast_done": "📣 Рассылка завершена.",
        "admin_no_categories": "Категорий пока нет.",
        "admin_no_products": "Товаров пока нет.",
        "skip": "пропустить",
    },
    "de": {
        "welcome": "👋 Willkommen!\n\nBitte wählen Sie Ihre Sprache:",
        "language_saved": "Sprache gespeichert.",
        "menu": "Bitte wählen Sie:",
        "catalog": "🛍 Katalog",
        "cart": "🛒 Warenkorb",
        "empty_catalog": "❌ Der Katalog ist noch leer.",
        "choose_category": "Kategorie auswählen:",
        "choose_brand": "Marke auswählen:",
        "no_products": "❌ In dieser Kategorie gibt es noch keine Produkte.",
        "back": "⬅️ Zurück",
        "home": "🏠 Hauptmenü",
        "available": "✅ Verfügbar",
        "unavailable": "❌ Nicht verfügbar",
        "add_cart": "🛒 In den Warenkorb",
        "added": "✅ Produkt wurde hinzugefügt.",
        "add_more": "➕ Weiter einkaufen",
        "go_cart": "🛒 Zum Warenkorb",
        "cart_empty": "🛒 Der Warenkorb ist leer.",
        "remove_last": "➖ Letztes entfernen",
        "clear_cart": "🗑 Warenkorb leeren",
        "checkout": "✅ Bestellung aufgeben",
        "total": "Gesamt",
        "order_start": "📦 Bestellung\n\nBitte Stadt oder Bezirk für die Lieferung angeben:",
        "order_date": "📅 Bitte Lieferdatum im Format TT.MM.JJJJ eingeben.\nBeispiel: 25.08.2026",
        "order_time": "🕒 Gewünschte Lieferzeit eingeben.\nBeispiel: 18:30 oder 18:00-19:00",
        "order_confirm": "Bitte prüfen Sie Ihre Bestellung:",
        "confirm": "✅ Bestätigen",
        "cancel": "❌ Abbrechen",
        "order_cancelled": "Bestellung abgebrochen.",
        "bad_date": "❌ Ungültiges Datum. TT.MM.JJJJ und nicht vor heute verwenden.",
        "bad_time": "❌ Ungültige Uhrzeit. Beispiel: 18:30 oder 18:00-19:00.",
        "city_too_short": "❌ Bitte Stadt oder Bezirk genauer angeben.",
        "order_sent": "✅ Bestellung angenommen!\n\nWir haben Ihre Daten erhalten und melden uns zur Bestätigung.",
        "order_failed": "❌ Bestellung konnte nicht übermittelt werden. Bitte später erneut versuchen.",
        "not_found": "❌ Produkt nicht gefunden.",
        "language": "🌐 Sprache",
        "choose_language": "Sprache auswählen:",
        "admin_denied": "⛔ Zugriff verweigert.",
        "admin": "⚙️ Admin-Bereich",
        "admin_categories": "📁 Kategorien",
        "admin_add_category": "➕ Kategorie hinzufügen",
        "admin_edit_category": "✏️ Kategorie bearbeiten",
        "admin_delete_category": "🗑 Kategorie löschen",
        "admin_add_product": "➕ Produkt hinzufügen",
        "admin_manage_products": "🛠 Produkte",
        "admin_broadcast": "📣 Rundnachricht",
        "admin_stats": "📊 Statistik",
        "admin_back": "⬅️ Admin-Bereich",
        "admin_category_name": "Bitte Namen der Kategorie senden.",
        "admin_category_photo": "Kategorie-Foto senden oder „überspringen“ schreiben.",
        "admin_product_name": "Bitte Produktnamen senden.",
        "admin_product_price": "Bitte Preis senden, z. B. 19.99",
        "admin_product_photo": "Produktfoto senden oder „überspringen“ schreiben.",
        "admin_product_stock": "Ist das Produkt verfügbar? Ja oder Nein.",
        "admin_saved": "✅ Änderungen gespeichert.",
        "admin_deleted": "✅ Gelöscht.",
        "admin_broadcast_text": "📣 Bitte Text der Rundnachricht senden.\n\nDanach sehen Sie eine Vorschau.",
        "admin_broadcast_confirm": "Diese Nachricht an alle Benutzer senden?",
        "admin_broadcast_done": "📣 Rundnachricht abgeschlossen.",
        "admin_no_categories": "Noch keine Kategorien.",
        "admin_no_products": "Noch keine Produkte.",
        "skip": "überspringen",
    },
    "en": {
        "welcome": "👋 Welcome!\n\nPlease choose your language:",
        "language_saved": "Language saved.",
        "menu": "Choose an action:",
        "catalog": "🛍 Catalog",
        "cart": "🛒 Cart",
        "empty_catalog": "❌ The catalog is empty.",
        "choose_category": "Choose a category:",
        "choose_brand": "Choose a brand:",
        "no_products": "❌ There are no products in this category yet.",
        "back": "⬅️ Back",
        "home": "🏠 Main menu",
        "available": "✅ Available",
        "unavailable": "❌ Out of stock",
        "add_cart": "🛒 Add to cart",
        "added": "✅ Product added to cart.",
        "add_more": "➕ Continue shopping",
        "go_cart": "🛒 Go to cart",
        "cart_empty": "🛒 Your cart is empty.",
        "remove_last": "➖ Remove last",
        "clear_cart": "🗑 Clear cart",
        "checkout": "✅ Checkout",
        "total": "Total",
        "order_start": "📦 Checkout\n\nPlease enter the delivery city or district:",
        "order_date": "📅 Enter the delivery date as DD.MM.YYYY.\nExample: 25.08.2026",
        "order_time": "🕒 Enter the preferred delivery time.\nExample: 18:30 or 18:00-19:00",
        "order_confirm": "Please review your order:",
        "confirm": "✅ Confirm",
        "cancel": "❌ Cancel",
        "order_cancelled": "Checkout cancelled.",
        "bad_date": "❌ Invalid date. Use DD.MM.YYYY and a date that is not in the past.",
        "bad_time": "❌ Invalid time. Example: 18:30 or 18:00-19:00.",
        "city_too_short": "❌ Please enter a more specific city or district.",
        "order_sent": "✅ Order received!\n\nWe have your details and will contact you to confirm.",
        "order_failed": "❌ The order could not be sent. Please try again later.",
        "not_found": "❌ Product not found.",
        "language": "🌐 Language",
        "choose_language": "Choose a language:",
        "admin_denied": "⛔ Access denied.",
        "admin": "⚙️ Admin panel",
        "admin_categories": "📁 Categories",
        "admin_add_category": "➕ Add category",
        "admin_edit_category": "✏️ Edit category",
        "admin_delete_category": "🗑 Delete category",
        "admin_add_product": "➕ Add product",
        "admin_manage_products": "🛠 Products",
        "admin_broadcast": "📣 Broadcast",
        "admin_stats": "📊 Statistics",
        "admin_back": "⬅️ Admin panel",
        "admin_category_name": "Send the category name.",
        "admin_category_photo": "Send a category photo or type “skip”.",
        "admin_product_name": "Send the product name.",
        "admin_product_price": "Send the price, e.g. 19.99",
        "admin_product_photo": "Send a product photo or type “skip”.",
        "admin_product_stock": "Is the product available? Yes or no.",
        "admin_saved": "✅ Changes saved.",
        "admin_deleted": "✅ Deleted.",
        "admin_broadcast_text": "📣 Send the broadcast text.\n\nI will show you a preview before sending.",
        "admin_broadcast_confirm": "Send this broadcast to all users?",
        "admin_broadcast_done": "📣 Broadcast completed.",
        "admin_no_categories": "No categories yet.",
        "admin_no_products": "No products yet.",
        "skip": "skip",
    },
}


def tr(user_id: Optional[int], key: str) -> str:
    lang = get_user_language(user_id)
    return T.get(lang, T["uk"]).get(key, T["uk"].get(key, key))


def get_user_language(user_id: Optional[int]) -> str:
    if not user_id:
        return "uk"
    users = read_json(USERS_PATH, {})
    record = users.get(str(user_id), {})
    lang = record.get("language") if isinstance(record, dict) else None
    return lang if lang in LANGS else "uk"


def set_user_language(user_id: int, lang: str) -> None:
    if lang not in LANGS:
        return
    users = read_json(USERS_PATH, {})
    if not isinstance(users, dict):
        users = {}
    rec = users.setdefault(str(user_id), {})
    rec["language"] = lang
    rec["updated_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(USERS_PATH, users)


def register_user(update: Update) -> None:
    user = update.effective_user
    if not user:
        return
    users = read_json(USERS_PATH, {})
    if not isinstance(users, dict):
        users = {}
    rec = users.setdefault(str(user.id), {})
    rec.update({
        "user_id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    })
    rec.setdefault("language", "uk")
    write_json(USERS_PATH, users)


# ============================================================
# JSON STORAGE
# ============================================================

def read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Cannot read %s", path)
        return default


def write_json(path: Path, data: Any) -> bool:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
        return True
    except OSError:
        logger.exception("Cannot write %s", path)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def load_catalog() -> dict[str, Any]:
    if (
        not CATALOG_PATH.exists()
        and SEED_CATALOG_PATH.exists()
        and CATALOG_PATH != SEED_CATALOG_PATH
    ):
        try:
            shutil.copy2(SEED_CATALOG_PATH, CATALOG_PATH)
        except OSError:
            logger.exception("Cannot copy seed catalog")

    catalog = read_json(
        CATALOG_PATH,
        {"currency": "EUR", "categories": {}},
    )
    if not isinstance(catalog, dict):
        catalog = {"currency": "EUR", "categories": {}}
    if not isinstance(catalog.get("categories"), dict):
        catalog["categories"] = {}
    catalog.setdefault("currency", "EUR")
    return catalog


CATALOG = load_catalog()


def save_catalog() -> bool:
    return write_json(CATALOG_PATH, CATALOG)


def save_order(order: dict[str, Any]) -> bool:
    orders = read_json(ORDERS_PATH, [])
    if not isinstance(orders, list):
        orders = []
    orders.append(order)
    return write_json(ORDERS_PATH, orders[-2000:])


# ============================================================
# CATALOG COMPATIBILITY HELPERS
# ============================================================

def categories() -> dict[str, Any]:
    return CATALOG.setdefault("categories", {})


def category_get(key: str) -> Optional[dict[str, Any]]:
    value = categories().get(key)
    return value if isinstance(value, dict) else None


def brands_get(category_key: str) -> dict[str, Any]:
    category = category_get(category_key)
    if not category:
        return {}
    brands = category.get("brands")
    if not isinstance(brands, dict):
        category["brands"] = {}
    return category["brands"]


def brand_get(category_key: str, brand_key: str) -> Optional[dict[str, Any]]:
    value = brands_get(category_key).get(brand_key)
    return value if isinstance(value, dict) else None


def items_get(container: dict[str, Any]) -> list[Any]:
    items = container.get("items", [])
    return items if isinstance(items, list) else []


def currency() -> str:
    return str(CATALOG.get("currency", "EUR"))


def price_text(value: Any) -> str:
    try:
        return f"{float(value):g} {currency()}"
    except (TypeError, ValueError):
        return f"{value} {currency()}"


def is_available(product: dict[str, Any]) -> bool:
    return product.get("in_stock", True) is True


def set_available(product: dict[str, Any], value: bool) -> None:
    product["in_stock"] = value


def unique_key(prefix: str, collection: dict[str, Any]) -> str:
    n = 1
    while f"{prefix}_{n}" in collection:
        n += 1
    return f"{prefix}_{n}"


def find_product(category_key: str, brand_key: str, index: int) -> Optional[dict[str, Any]]:
    brand = brand_get(category_key, brand_key)
    if not brand:
        return None
    items = items_get(brand)
    if not 0 <= index < len(items):
        return None
    item = items[index]
    return item if isinstance(item, dict) else None


def all_products() -> list[tuple[str, str, int, dict[str, Any]]]:
    result = []
    for ck, category in categories().items():
        if not isinstance(category, dict):
            continue
        for bk, brand in brands_get(ck).items():
            if not isinstance(brand, dict):
                continue
            for i, product in enumerate(items_get(brand)):
                if isinstance(product, dict):
                    result.append((ck, bk, i, product))
    return result


# ============================================================
# UI HELPERS
# ============================================================

def lang_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(LANGS["uk"], callback_data="lang:uk")],
        [InlineKeyboardButton(LANGS["ru"], callback_data="lang:ru")],
        [InlineKeyboardButton(LANGS["de"], callback_data="lang:de")],
        [InlineKeyboardButton(LANGS["en"], callback_data="lang:en")],
    ])


def main_keyboard(user_id: Optional[int]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr(user_id, "catalog"), callback_data="catalog")],
        [InlineKeyboardButton(tr(user_id, "cart"), callback_data="cart")],
        [InlineKeyboardButton(tr(user_id, "language"), callback_data="language")],
    ])


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📁 Категорії", callback_data="adm:categories"),
            InlineKeyboardButton("🛠 Товари", callback_data="adm:products"),
        ],
        [
            InlineKeyboardButton("➕ Додати категорію", callback_data="adm:addcat"),
            InlineKeyboardButton("➕ Додати товар", callback_data="adm:addproduct"),
        ],
        [
            InlineKeyboardButton("📣 Розсилка", callback_data="adm:broadcast"),
            InlineKeyboardButton("📊 Статистика", callback_data="adm:stats"),
        ],
    ])


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
        except BadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
    if update.effective_chat:
        await update.effective_chat.send_message(text=text, reply_markup=keyboard)


async def show_photo_or_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    keyboard: InlineKeyboardMarkup,
    photo_id: Optional[str] = None,
) -> None:
    if photo_id and update.effective_chat:
        try:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=photo_id,
                caption=text,
                reply_markup=keyboard,
            )
            return
        except Exception:
            logger.exception("Cannot send stored photo")
    await show_text(update, text, keyboard)


# ============================================================
# START / LANGUAGE
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    context.user_data.clear()
    await update.effective_message.reply_text(
        tr(update.effective_user.id, "welcome"),
        reply_markup=lang_keyboard(),
    )


async def language_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    await show_text(
        update,
        tr(update.effective_user.id, "choose_language"),
        lang_keyboard(),
    )


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    query = update.callback_query
    lang = query.data.split(":", 1)[1] if query and query.data else ""
    user = update.effective_user
    if user and lang in LANGS:
        set_user_language(user.id, lang)
        register_user(update)
        await show_text(
            update,
            f"{T[lang]['language_saved']}\n\n{T[lang]['menu']}",
            main_keyboard(user.id),
        )


# ============================================================
# CUSTOMER CATALOG
# ============================================================

async def catalog_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    buttons = []
    for key, category in categories().items():
        if isinstance(category, dict):
            title = category.get("title", key)
            buttons.append([
                InlineKeyboardButton(str(title), callback_data=f"cat:{key}")
            ])

    if not buttons:
        await show_text(
            update,
            tr(update.effective_user.id, "empty_catalog"),
            main_keyboard(update.effective_user.id),
        )
        return

    buttons.append([
        InlineKeyboardButton(tr(update.effective_user.id, "home"), callback_data="main")
    ])
    await show_text(
        update,
        tr(update.effective_user.id, "choose_category"),
        InlineKeyboardMarkup(buttons),
    )


async def category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    query = update.callback_query
    category_key = query.data.split(":", 1)[1] if query and query.data else ""
    category = category_get(category_key)
    if not category:
        await show_text(update, tr(update.effective_user.id, "not_found"))
        return

    buttons = []
    for brand_key, brand in brands_get(category_key).items():
        if isinstance(brand, dict):
            buttons.append([
                InlineKeyboardButton(
                    str(brand.get("title", brand_key)),
                    callback_data=f"brand:{category_key}:{brand_key}",
                )
            ])

    if not buttons:
        await show_text(
            update,
            tr(update.effective_user.id, "no_products"),
            InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    tr(update.effective_user.id, "back"),
                    callback_data="catalog"
                )]
            ]),
        )
        return

    buttons.append([
        InlineKeyboardButton(
            tr(update.effective_user.id, "back"),
            callback_data="catalog"
        )
    ])
    photo = category.get("photo")
    text = str(category.get("title", "Category"))
    await show_photo_or_text(
        update,
        context,
        text + "\n\n" + tr(update.effective_user.id, "choose_brand"),
        InlineKeyboardMarkup(buttons),
        photo,
    )


async def brand_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    query = update.callback_query
    parts = query.data.split(":") if query and query.data else []
    if len(parts) != 3:
        return

    _, category_key, brand_key = parts
    brand = brand_get(category_key, brand_key)
    if not brand:
        await show_text(update, tr(update.effective_user.id, "not_found"))
        return

    buttons = []
    for i, product in enumerate(items_get(brand)):
        if not isinstance(product, dict):
            continue

        # Backward-compatible support for the original "parent + flavors" format.
        if "nicotine" in product and isinstance(product.get("items"), list):
            label = f"{product.get('nicotine')} — {price_text(product.get('price', ''))}"
            callback = f"variants:{category_key}:{brand_key}:{i}"
        elif "name" in product and "price" in product:
            icon = "✅" if is_available(product) else "❌"
            label = f"{product['name']} — {price_text(product['price'])} {icon}"
            callback = f"product:{category_key}:{brand_key}:{i}"
        else:
            continue

        buttons.append([InlineKeyboardButton(label, callback_data=callback)])

    buttons.append([
        InlineKeyboardButton(tr(update.effective_user.id, "cart"), callback_data="cart")
    ])
    buttons.append([
        InlineKeyboardButton(tr(update.effective_user.id, "back"), callback_data=f"cat:{category_key}")
    ])

    await show_text(
        update,
        str(brand.get("title", "Products")),
        InlineKeyboardMarkup(buttons),
    )


async def product_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    query = update.callback_query
    parts = query.data.split(":") if query and query.data else []
    if len(parts) != 4:
        return

    _, category_key, brand_key, index_text = parts
    try:
        index = int(index_text)
    except ValueError:
        return

    product = find_product(category_key, brand_key, index)
    if not product or "name" not in product or "price" not in product:
        await show_text(update, tr(update.effective_user.id, "not_found"))
        return

    status = (
        tr(update.effective_user.id, "available")
        if is_available(product)
        else tr(update.effective_user.id, "unavailable")
    )
    text = (
        f"🧾 {product['name']}\n"
        f"💶 {price_text(product['price'])}\n"
        f"{status}"
    )
    buttons = []
    if is_available(product):
        buttons.append([
            InlineKeyboardButton(
                tr(update.effective_user.id, "add_cart"),
                callback_data=f"add:direct:{category_key}:{brand_key}:{index}",
            )
        ])
    buttons.append([
        InlineKeyboardButton(
            tr(update.effective_user.id, "back"),
            callback_data=f"brand:{category_key}:{brand_key}",
        )
    ])

    await show_photo_or_text(
        update,
        context,
        text,
        InlineKeyboardMarkup(buttons),
        product.get("photo"),
    )


async def variants_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    query = update.callback_query
    parts = query.data.split(":") if query and query.data else []
    if len(parts) != 4:
        return

    _, category_key, brand_key, parent_text = parts
    try:
        parent_index = int(parent_text)
    except ValueError:
        return

    brand = brand_get(category_key, brand_key)
    products = items_get(brand) if brand else []
    if not 0 <= parent_index < len(products):
        return

    parent = products[parent_index]
    if not isinstance(parent, dict):
        return

    buttons = []
    for flavor_index, flavor in enumerate(items_get(parent)):
        name = flavor if isinstance(flavor, str) else flavor.get("name", "Variant")
        buttons.append([
            InlineKeyboardButton(
                str(name),
                callback_data=f"add:variant:{category_key}:{brand_key}:{parent_index}:{flavor_index}",
            )
        ])
    buttons.append([
        InlineKeyboardButton(
            tr(update.effective_user.id, "back"),
            callback_data=f"brand:{category_key}:{brand_key}",
        )
    ])
    await show_text(
        update,
        f"{parent.get('nicotine', 'Variants')}\n\n{tr(update.effective_user.id, 'choose_brand')}",
        InlineKeyboardMarkup(buttons),
    )


# ============================================================
# CART
# ============================================================

def cart_get(context: ContextTypes.DEFAULT_TYPE) -> list[dict[str, Any]]:
    return context.user_data.setdefault("cart", [])


def cart_total(cart: list[dict[str, Any]]) -> float:
    total = 0.0
    for item in cart:
        try:
            total += float(item["price"])
        except (TypeError, ValueError):
            pass
    return round(total, 2)


def resolve_cart_item(key: str) -> Optional[dict[str, Any]]:
    parts = key.split(":")
    try:
        if parts[0] == "direct" and len(parts) == 4:
            _, ck, bk, idx_text = parts
            product = find_product(ck, bk, int(idx_text))
            if product and is_available(product):
                return {
                    "key": key,
                    "name": str(product["name"]),
                    "price": float(product["price"]),
                }

        if parts[0] == "variant" and len(parts) == 5:
            _, ck, bk, parent_text, flavor_text = parts
            parent_index = int(parent_text)
            flavor_index = int(flavor_text)
            brand = brand_get(ck, bk)
            products = items_get(brand) if brand else []
            if not 0 <= parent_index < len(products):
                return None
            parent = products[parent_index]
            if not isinstance(parent, dict):
                return None
            flavors = items_get(parent)
            if not 0 <= flavor_index < len(flavors):
                return None
            flavor = flavors[flavor_index]
            flavor_name = flavor if isinstance(flavor, str) else flavor.get("name", "Variant")
            return {
                "key": key,
                "name": f"{brand.get('title', '')} {parent.get('nicotine', '')} — {flavor_name}",
                "price": float(parent["price"]),
            }
    except (TypeError, ValueError, KeyError, AttributeError):
        return None
    return None


async def add_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    query = update.callback_query
    key = query.data.split(":", 1)[1] if query and query.data else ""
    item = resolve_cart_item(key)
    if not item:
        await show_text(update, tr(update.effective_user.id, "not_found"))
        return

    cart_get(context).append(item)
    await show_text(
        update,
        f"{tr(update.effective_user.id, 'added')}\n\n"
        f"🧾 {item['name']}\n💶 {price_text(item['price'])}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton(
                tr(update.effective_user.id, "add_more"),
                callback_data="catalog"
            )],
            [InlineKeyboardButton(
                tr(update.effective_user.id, "go_cart"),
                callback_data="cart"
            )],
        ]),
    )


async def cart_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    cart = cart_get(context)
    if not cart:
        await show_text(
            update,
            tr(update.effective_user.id, "cart_empty"),
            main_keyboard(update.effective_user.id),
        )
        return

    lines = [
        f"{i}. {item['name']} — {price_text(item['price'])}"
        for i, item in enumerate(cart, 1)
    ]
    text = (
        f"{tr(update.effective_user.id, 'cart')}\n\n"
        + "\n".join(lines)
        + f"\n\n💰 {tr(update.effective_user.id, 'total')}: "
        f"{price_text(cart_total(cart))}"
    )
    await show_text(
        update,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton(
                tr(update.effective_user.id, "add_more"),
                callback_data="catalog"
            )],
            [InlineKeyboardButton(
                tr(update.effective_user.id, "remove_last"),
                callback_data="remove_last"
            )],
            [InlineKeyboardButton(
                tr(update.effective_user.id, "clear_cart"),
                callback_data="clear_cart"
            )],
            [InlineKeyboardButton(
                tr(update.effective_user.id, "checkout"),
                callback_data="checkout"
            )],
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
    await show_text(
        update,
        tr(update.effective_user.id, "cart_empty"),
        main_keyboard(update.effective_user.id),
    )


# ============================================================
# ORDER FLOW
# ============================================================

def valid_time(value: str) -> bool:
    value = value.strip()
    single = re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value)
    interval = re.fullmatch(
        r"([01]\d|2[0-3]):[0-5]\d\s*-\s*([01]\d|2[0-3]):[0-5]\d",
        value,
    )
    return bool(single or interval)


def order_preview(user: Any, cart: list[dict[str, Any]], data: dict[str, Any]) -> str:
    items = "\n".join(
        f"• {item['name']} — {price_text(item['price'])}"
        for item in cart
    )
    return (
        "📦 НОВЕ ЗАМОВЛЕННЯ\n\n"
        f"👤 {user.full_name}\n"
        f"🔗 @{user.username}\n" if user.username else
        f"👤 {user.full_name}\n"
    ) + (
        f"🆔 Telegram ID: {user.id}\n\n"
        f"🛍 Товари:\n{items}\n\n"
        f"💰 Разом: {price_text(cart_total(cart))}\n"
        f"📍 Місто/район: {data['city']}\n"
        f"📅 Дата отримання: {data['date']}\n"
        f"🕒 Час: {data['time']}"
    )


async def checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    cart = cart_get(context)
    if not cart:
        await show_text(update, tr(update.effective_user.id, "cart_empty"))
        return

    context.user_data["order_flow"] = {"step": "city"}
    await show_text(
        update,
        tr(update.effective_user.id, "order_start"),
        InlineKeyboardMarkup([
            [InlineKeyboardButton(
                tr(update.effective_user.id, "cancel"),
                callback_data="order:cancel"
            )]
        ]),
    )


async def order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    query = update.callback_query
    action = query.data.split(":", 1)[1] if query and query.data else ""

    if action == "cancel":
        context.user_data.pop("order_flow", None)
        await show_text(
            update,
            tr(update.effective_user.id, "order_cancelled"),
            main_keyboard(update.effective_user.id),
        )
        return

    if action == "confirm":
        flow = context.user_data.get("order_flow")
        cart = cart_get(context)
        user = update.effective_user

        if not isinstance(flow, dict) or not user or not cart:
            await show_text(update, tr(update.effective_user.id, "order_failed"))
            return

        now = datetime.now()
        order_id = f"{user.id}-{int(now.timestamp())}"
        order = {
            "order_id": order_id,
            "user_id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "language": get_user_language(user.id),
            "items": cart,
            "total": cart_total(cart),
            "delivery": {
                "city_or_district": flow["city"],
                "date": flow["date"],
                "time": flow["time"],
            },
            "created_at": now.isoformat(timespec="seconds"),
        }

        text = order_preview(user, cart, flow)
        delivered = True
        for admin_id in ORDER_ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=text)
            except Exception:
                delivered = False
                logger.exception("Cannot send order to %s", admin_id)

        if not delivered:
            await show_text(update, tr(user.id, "order_failed"))
            return

        save_order(order)
        context.user_data["cart"] = []
        context.user_data.pop("order_flow", None)

        await show_text(
            update,
            tr(user.id, "order_sent"),
            main_keyboard(user.id),
        )


# ============================================================
# ADMIN
# ============================================================

def admin_allowed(update: Update) -> bool:
    return bool(update.effective_user and update.effective_user.id == ADMIN_ID)


async def deny_admin(update: Update) -> None:
    await answer_callback(update)
    await show_text(update, tr(update.effective_user.id, "admin_denied"))


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    if not admin_allowed(update):
        await deny_admin(update)
        return
    context.user_data.pop("admin_flow", None)
    await update.effective_message.reply_text(
        "⚙️ Адмін-панель\n\nОберіть розділ:",
        reply_markup=admin_keyboard(),
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    if not admin_allowed(update):
        await deny_admin(update)
        return

    query = update.callback_query
    data = query.data if query else ""
    action = data[4:] if data.startswith("adm:") else ""

    if action == "home":
        await show_text(update, "⚙️ Адмін-панель", admin_keyboard())
        return

    if action == "categories":
        await admin_categories(update, context)
    elif action == "addcat":
        context.user_data["admin_flow"] = {"step": "add_category_name"}
        await show_text(update, "📁 Надішліть назву нової категорії.")
    elif action == "products":
        await admin_products(update, context)
    elif action == "addproduct":
        await admin_add_product_start(update, context)
    elif action == "broadcast":
        context.user_data["admin_flow"] = {"step": "broadcast_text"}
        await show_text(update, T["uk"]["admin_broadcast_text"])
    elif action.startswith("addprodcat:"):
        ck = action.split(":", 1)[1]
        category = category_get(ck)
        if not category:
            await show_text(update, "❌ Категорію не знайдено.")
            return
        brands = brands_get(ck)
        if not brands:
            bk = unique_key("brand", brands)
            brands[bk] = {"title": "Товари", "items": []}
            save_catalog()
        buttons = [
            [InlineKeyboardButton(
                str(brand.get("title", bk)),
                callback_data=f"adm:addprodbk:{ck}:{bk}",
            )]
            for bk, brand in brands.items()
            if isinstance(brand, dict)
        ]
        buttons.append([
            InlineKeyboardButton("⬅️ Назад", callback_data="adm:products")
        ])
        await show_text(update, "🏷 Виберіть розділ товарів:", InlineKeyboardMarkup(buttons))
    elif action.startswith("addprodbk:"):
        parts = action.split(":")
        if len(parts) != 3:
            return
        ck, bk = parts[1], parts[2]
        if not brand_get(ck, bk):
            await show_text(update, "❌ Розділ не знайдено.")
            return
        context.user_data["admin_flow"] = {
            "step": "add_product_name",
            "category_key": ck,
            "brand_key": bk,
        }
        await show_text(update, "➕ Надішліть назву товару.")
    elif action == "stats":
        users = read_json(USERS_PATH, {})
        orders = read_json(ORDERS_PATH, [])
        await show_text(
            update,
            f"📊 Статистика\n\n"
            f"👥 Користувачів: {len(users) if isinstance(users, dict) else 0}\n"
            f"📦 Замовлень: {len(orders) if isinstance(orders, list) else 0}\n"
            f"🛍 Товарів: {len(all_products())}\n"
            f"📁 Категорій: {len(categories())}",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Адмін-панель", callback_data="adm:home")]
            ]),
        )
    elif action.startswith("cat:"):
        await admin_category_actions(update, context, action.split(":")[1])
    elif action.startswith("renamecat:"):
        key = action.split(":", 1)[1]
        context.user_data["admin_flow"] = {"step": "rename_category", "category_key": key}
        await show_text(update, "✏️ Надішліть нову назву категорії.")
    elif action.startswith("catphoto:"):
        key = action.split(":", 1)[1]
        context.user_data["admin_flow"] = {"step": "category_photo", "category_key": key}
        await show_text(update, "🖼 Надішліть нове фото категорії.")
    elif action.startswith("delcat:"):
        key = action.split(":", 1)[1]
        categories().pop(key, None)
        save_catalog()
        await show_text(update, "✅ Категорію видалено.", admin_keyboard())
    elif action.startswith("brand:"):
        await admin_brand_products(update, context, action.split(":"))
    elif action.startswith("item:"):
        await admin_product_actions(update, context, action.split(":"))
    elif action.startswith("toggle:"):
        await admin_toggle_product(update, context, action.split(":"))
    elif action.startswith("photo:"):
        await admin_product_photo_start(update, context, action.split(":"))
    elif action.startswith("editname:"):
        parts = action.split(":")
        if len(parts) == 4:
            context.user_data["admin_flow"] = {
                "step": "edit_product_name",
                "category_key": parts[1],
                "brand_key": parts[2],
                "index": int(parts[3]),
            }
            await show_text(update, "✏️ Надішліть нову назву товару.")
    elif action.startswith("editprice:"):
        parts = action.split(":")
        if len(parts) == 4:
            context.user_data["admin_flow"] = {
                "step": "edit_product_price",
                "category_key": parts[1],
                "brand_key": parts[2],
                "index": int(parts[3]),
            }
            await show_text(update, "💶 Надішліть нову ціну, наприклад 19.99")
    elif action.startswith("delete:"):
        await admin_delete_product(update, context, action.split(":"))
    elif action.startswith("broadcast:"):
        await admin_broadcast_action(update, context, action.split(":", 1)[1])


async def admin_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    buttons = []
    for key, category in categories().items():
        if isinstance(category, dict):
            buttons.append([
                InlineKeyboardButton(
                    f"📁 {category.get('title', key)}",
                    callback_data=f"adm:cat:{key}",
                )
            ])
    buttons.append([
        InlineKeyboardButton("➕ Додати категорію", callback_data="adm:addcat")
    ])
    buttons.append([
        InlineKeyboardButton("⬅️ Адмін-панель", callback_data="adm:home")
    ])
    await show_text(
        update,
        "📁 Категорії\n\nОберіть категорію для редагування:",
        InlineKeyboardMarkup(buttons),
    )


async def admin_category_actions(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    key: str,
) -> None:
    category = category_get(key)
    if not category:
        await show_text(update, "❌ Категорію не знайдено.")
        return

    await show_text(
        update,
        f"📁 {category.get('title', key)}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Змінити назву", callback_data=f"adm:renamecat:{key}")],
            [InlineKeyboardButton("🖼 Змінити фото", callback_data=f"adm:catphoto:{key}")],
            [InlineKeyboardButton("🗑 Видалити", callback_data=f"adm:delcat:{key}")],
            [InlineKeyboardButton("⬅️ Категорії", callback_data="adm:categories")],
        ]),
    )


async def admin_products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    buttons = []
    for ck, category in categories().items():
        if isinstance(category, dict):
            buttons.append([
                InlineKeyboardButton(
                    f"📁 {category.get('title', ck)}",
                    callback_data=f"adm:brand:{ck}",
                )
            ])
    buttons.append([
        InlineKeyboardButton("➕ Додати товар", callback_data="adm:addproduct")
    ])
    buttons.append([
        InlineKeyboardButton("⬅️ Адмін-панель", callback_data="adm:home")
    ])
    await show_text(
        update,
        "🛠 Товари\n\nОберіть категорію:",
        InlineKeyboardMarkup(buttons),
    )


async def admin_brand_products(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parts: list[str],
) -> None:
    if len(parts) < 2:
        return
    ck = parts[1]
    buttons = []
    category = category_get(ck)
    if not category:
        await show_text(update, "❌ Категорію не знайдено.")
        return

    # Existing catalog uses brands. Admin can manage products under each brand.
    for bk, brand in brands_get(ck).items():
        if not isinstance(brand, dict):
            continue
        buttons.append([
            InlineKeyboardButton(
                f"🏷 {brand.get('title', bk)}",
                callback_data=f"adm:branditems:{ck}:{bk}",
            )
        ])

    # Direct fallback: if the category has no brands, create one automatically.
    if not buttons:
        bk = unique_key("brand", brands_get(ck))
        brands_get(ck)[bk] = {"title": "Товари", "items": []}
        save_catalog()
        buttons.append([
            InlineKeyboardButton(
                "🏷 Товари",
                callback_data=f"adm:branditems:{ck}:{bk}",
            )
        ])

    buttons.append([
        InlineKeyboardButton("⬅️ Товари", callback_data="adm:products")
    ])
    await show_text(update, f"📁 {category.get('title', ck)}", InlineKeyboardMarkup(buttons))


async def admin_product_actions(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parts: list[str],
) -> None:
    # item:category:brand:index
    if len(parts) != 4:
        # branditems:category:brand is also handled here by design.
        if len(parts) == 3 and parts[0] == "branditems":
            await admin_brand_items(update, context, parts[1], parts[2])
        return

    _, ck, bk, index_text = parts
    try:
        index = int(index_text)
    except ValueError:
        return

    product = find_product(ck, bk, index)
    if not product:
        await show_text(update, "❌ Товар не знайдено.")
        return

    status = "✅ В наявності" if is_available(product) else "❌ Немає в наявності"
    await show_text(
        update,
        f"🧾 {product.get('name', 'Товар')}\n"
        f"💶 {price_text(product.get('price'))}\n{status}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Змінити назву", callback_data=f"adm:editname:{ck}:{bk}:{index}")],
            [InlineKeyboardButton("💶 Змінити ціну", callback_data=f"adm:editprice:{ck}:{bk}:{index}")],
            [InlineKeyboardButton("🔄 Змінити наявність", callback_data=f"adm:toggle:{ck}:{bk}:{index}")],
            [InlineKeyboardButton("🖼 Змінити фото", callback_data=f"adm:photo:{ck}:{bk}:{index}")],
            [InlineKeyboardButton("🗑 Видалити", callback_data=f"adm:delete:{ck}:{bk}:{index}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"adm:branditems:{ck}:{bk}")],
        ]),
    )


async def admin_brand_items(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    ck: str,
    bk: str,
) -> None:
    brand = brand_get(ck, bk)
    if not brand:
        await show_text(update, "❌ Розділ не знайдено.")
        return

    buttons = []
    for i, product in enumerate(items_get(brand)):
        if isinstance(product, dict) and "name" in product and "price" in product:
            icon = "✅" if is_available(product) else "❌"
            buttons.append([
                InlineKeyboardButton(
                    f"{icon} {product['name']}",
                    callback_data=f"adm:item:{ck}:{bk}:{i}",
                )
            ])

    if not buttons:
        buttons.append([
            InlineKeyboardButton("➕ Додати товар", callback_data="adm:addproduct")
        ])

    buttons.append([
        InlineKeyboardButton("⬅️ Назад", callback_data=f"adm:brand:{ck}")
    ])
    await show_text(
        update,
        f"🏷 {brand.get('title', bk)}",
        InlineKeyboardMarkup(buttons),
    )


async def admin_add_product_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not categories():
        await show_text(
            update,
            "❌ Спочатку створіть категорію.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Додати категорію", callback_data="adm:addcat")]
            ]),
        )
        return

    buttons = []
    for ck, category in categories().items():
        if isinstance(category, dict):
            buttons.append([
                InlineKeyboardButton(
                    str(category.get("title", ck)),
                    callback_data=f"adm:addprodcat:{ck}",
                )
            ])
    buttons.append([
        InlineKeyboardButton("⬅️ Адмін-панель", callback_data="adm:home")
    ])
    await show_text(update, "➕ Виберіть категорію:", InlineKeyboardMarkup(buttons))


async def admin_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not admin_allowed(update) or not update.message or not update.message.text:
        return

    flow = context.user_data.get("admin_flow")
    if not isinstance(flow, dict):
        return

    text = update.message.text.strip()
    step = flow.get("step")

    if step == "add_category_name":
        key = unique_key("category", categories())
        categories()[key] = {"title": text, "brands": {}}
        save_catalog()
        context.user_data.pop("admin_flow", None)
        await update.message.reply_text("✅ Категорію додано.", reply_markup=admin_keyboard())

    elif step == "rename_category":
        category = category_get(flow.get("category_key", ""))
        if not category:
            await update.message.reply_text("❌ Категорію не знайдено.")
            return
        category["title"] = text
        save_catalog()
        context.user_data.pop("admin_flow", None)
        await update.message.reply_text("✅ Назву категорії змінено.", reply_markup=admin_keyboard())

    elif step == "category_photo":
        if text.lower() in {"пропустити", "skip", "überspringen", "-"}:
            context.user_data.pop("admin_flow", None)
            await update.message.reply_text("Скасовано.", reply_markup=admin_keyboard())
            return

    elif step == "edit_product_name":
        product = find_product(
            flow.get("category_key", ""),
            flow.get("brand_key", ""),
            int(flow.get("index", -1)),
        )
        if not product:
            context.user_data.pop("admin_flow", None)
            await update.message.reply_text("❌ Товар не знайдено.")
            return
        product["name"] = text
        save_catalog()
        context.user_data.pop("admin_flow", None)
        await update.message.reply_text("✅ Назву товару змінено.", reply_markup=admin_keyboard())

    elif step == "edit_product_price":
        try:
            price = float(text.replace(",", "."))
            if price < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Некоректна ціна. Наприклад: 19.99")
            return
        product = find_product(
            flow.get("category_key", ""),
            flow.get("brand_key", ""),
            int(flow.get("index", -1)),
        )
        if not product:
            context.user_data.pop("admin_flow", None)
            await update.message.reply_text("❌ Товар не знайдено.")
            return
        product["price"] = price
        save_catalog()
        context.user_data.pop("admin_flow", None)
        await update.message.reply_text("✅ Ціну товару змінено.", reply_markup=admin_keyboard())

    elif step == "add_product_name":
        flow["name"] = text
        flow["step"] = "add_product_price"
        await update.message.reply_text("💶 Надішліть ціну, наприклад 19.99")

    elif step == "add_product_price":
        try:
            price = float(text.replace(",", "."))
            if price < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Некоректна ціна. Наприклад: 19.99")
            return
        flow["price"] = price
        flow["step"] = "add_product_photo"
        await update.message.reply_text("🖼 Надішліть фото товару або напишіть «пропустити».")

    elif step == "add_product_photo":
        if text.lower() not in {"пропустити", "skip", "überspringen", "-"}:
            await update.message.reply_text("🖼 Надішліть фото або напишіть «пропустити».")
            return
        flow["step"] = "add_product_stock"
        await update.message.reply_text("Товар є в наявності? Напишіть: так/ні, да/нет, yes/no або ja/nein.")

    elif step == "add_product_stock":
        yes = {"так", "да", "yes", "ja"}
        no = {"ні", "нет", "no", "nein"}
        value = text.lower()
        if value not in yes | no:
            await update.message.reply_text("❌ Відповідь має бути так/ні, да/нет, yes/no або ja/nein.")
            return

        ck = flow.get("category_key", "")
        bk = flow.get("brand_key", "")
        brand = brand_get(ck, bk)
        if not brand:
            await update.message.reply_text("❌ Категорію/розділ не знайдено.")
            context.user_data.pop("admin_flow", None)
            return

        product = {
            "name": flow["name"],
            "price": flow["price"],
            "in_stock": value in yes,
        }
        if flow.get("photo"):
            product["photo"] = flow["photo"]

        brand.setdefault("items", []).append(product)
        save_catalog()
        context.user_data.pop("admin_flow", None)
        await update.message.reply_text("✅ Товар додано.", reply_markup=admin_keyboard())

    elif step == "broadcast_text":
        flow["text"] = text
        flow["step"] = "broadcast_confirm"
        await update.message.reply_text(
            f"📣 ПРЕВ'Ю\n\n{text}\n\n"
            "Надіслати всім користувачам?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Надіслати", callback_data="adm:broadcast:send")],
                [InlineKeyboardButton("❌ Скасувати", callback_data="adm:broadcast:cancel")],
            ]),
        )


async def admin_photo_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not admin_allowed(update) or not update.message or not update.message.photo:
        return

    flow = context.user_data.get("admin_flow")
    if not isinstance(flow, dict):
        return

    photo_id = update.message.photo[-1].file_id
    step = flow.get("step")

    if step == "add_product_photo":
        flow["photo"] = photo_id
        flow["step"] = "add_product_stock"
        await update.message.reply_text(
            "Товар є в наявності? Напишіть: так/ні, да/нет, yes/no або ja/nein."
        )

    elif step == "category_photo":
        category = category_get(flow.get("category_key", ""))
        if category:
            category["photo"] = photo_id
            save_catalog()
        context.user_data.pop("admin_flow", None)
        await update.message.reply_text("✅ Фото категорії оновлено.", reply_markup=admin_keyboard())

    elif step == "product_photo":
        try:
            ck = flow["category_key"]
            bk = flow["brand_key"]
            index = int(flow["index"])
            product = find_product(ck, bk, index)
            if product:
                product["photo"] = photo_id
                save_catalog()
                await update.message.reply_text("✅ Фото товару оновлено.", reply_markup=admin_keyboard())
            else:
                await update.message.reply_text("❌ Товар не знайдено.")
        finally:
            context.user_data.pop("admin_flow", None)


async def admin_broadcast_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str,
) -> None:
    flow = context.user_data.get("admin_flow")
    if action == "cancel":
        context.user_data.pop("admin_flow", None)
        await show_text(update, "❌ Розсилку скасовано.", admin_keyboard())
        return

    if action != "send" or not isinstance(flow, dict) or not flow.get("text"):
        return

    users = read_json(USERS_PATH, {})
    if not isinstance(users, dict):
        users = {}

    sent = 0
    blocked = 0
    for user_id_text in list(users.keys()):
        try:
            await context.bot.send_message(
                chat_id=int(user_id_text),
                text=flow["text"],
            )
            sent += 1
        except Forbidden:
            blocked += 1
        except Exception:
            blocked += 1
            logger.exception("Broadcast failed for %s", user_id_text)

    context.user_data.pop("admin_flow", None)
    await show_text(
        update,
        f"📣 Розсилку завершено.\n\n"
        f"✅ Надіслано: {sent}\n"
        f"⚠️ Не доставлено: {blocked}",
        admin_keyboard(),
    )


async def admin_toggle_product(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parts: list[str],
) -> None:
    if len(parts) != 4:
        return
    _, ck, bk, index_text = parts
    try:
        index = int(index_text)
    except ValueError:
        return
    product = find_product(ck, bk, index)
    if not product:
        return
    set_available(product, not is_available(product))
    save_catalog()
    await admin_product_actions(update, context, ["item", ck, bk, str(index)])


async def admin_product_photo_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parts: list[str],
) -> None:
    if len(parts) != 4:
        return
    _, ck, bk, index_text = parts
    try:
        index = int(index_text)
    except ValueError:
        return
    if not find_product(ck, bk, index):
        await show_text(update, "❌ Товар не знайдено.")
        return
    context.user_data["admin_flow"] = {
        "step": "product_photo",
        "category_key": ck,
        "brand_key": bk,
        "index": index,
    }
    await show_text(update, "🖼 Надішліть нове фото товару.")


async def admin_delete_product(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parts: list[str],
) -> None:
    if len(parts) != 4:
        return
    _, ck, bk, index_text = parts
    try:
        index = int(index_text)
    except ValueError:
        return
    brand = brand_get(ck, bk)
    if not brand:
        return
    items = items_get(brand)
    if 0 <= index < len(items):
        items.pop(index)
        save_catalog()
    await admin_brand_items(update, context, ck, bk)


# ============================================================
# ADMIN ADD-PRODUCT CALLBACK ROUTING
# ============================================================

async def admin_extra_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    if not admin_allowed(update):
        await deny_admin(update)
        return

    query = update.callback_query
    data = query.data if query else ""

    if data.startswith("adm:addprodcat:"):
        ck = data.split(":", 2)[2]
        category = category_get(ck)
        if not category:
            await show_text(update, "❌ Категорію не знайдено.")
            return

        brands = brands_get(ck)
        if not brands:
            bk = unique_key("brand", brands)
            brands[bk] = {"title": "Товари", "items": []}
            save_catalog()
        buttons = [
            [
                InlineKeyboardButton(
                    str(brand.get("title", bk)),
                    callback_data=f"adm:addprodbk:{ck}:{bk}",
                )
            ]
            for bk, brand in brands.items()
            if isinstance(brand, dict)
        ]
        await show_text(update, "🏷 Виберіть розділ товарів:", InlineKeyboardMarkup(buttons))

    elif data.startswith("adm:addprodbk:"):
        parts = data.split(":")
        if len(parts) != 4:
            return
        ck, bk = parts[2], parts[3]
        if not brand_get(ck, bk):
            return
        context.user_data["admin_flow"] = {
            "step": "add_product_name",
            "category_key": ck,
            "brand_key": bk,
        }
        await show_text(update, "➕ Надішліть назву товару.")


# ============================================================
# GENERIC TEXT ROUTER FOR ORDER FLOW
# ============================================================

async def customer_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    register_user(update)

    # Admin text flows have priority.
    if admin_allowed(update) and context.user_data.get("admin_flow"):
        await admin_text_router(update, context)
        return

    flow = context.user_data.get("order_flow")
    if not isinstance(flow, dict):
        return

    text = update.message.text.strip()
    step = flow.get("step")
    user_id = update.effective_user.id

    if step == "city":
        if len(text) < 2:
            await update.message.reply_text(tr(user_id, "city_too_short"))
            return
        flow["city"] = text
        flow["step"] = "date"
        await update.message.reply_text(tr(user_id, "order_date"))

    elif step == "date":
        try:
            parsed = datetime.strptime(text, "%d.%m.%Y").date()
            if parsed < date.today():
                raise ValueError
        except ValueError:
            await update.message.reply_text(tr(user_id, "bad_date"))
            return
        flow["date"] = text
        flow["step"] = "time"
        await update.message.reply_text(tr(user_id, "order_time"))

    elif step == "time":
        if not valid_time(text):
            await update.message.reply_text(tr(user_id, "bad_time"))
            return
        flow["time"] = text
        flow["step"] = "confirm"

        cart = cart_get(context)
        preview = (
            f"{tr(user_id, 'order_confirm')}\n\n"
            f"📍 {flow['city']}\n"
            f"📅 {flow['date']}\n"
            f"🕒 {flow['time']}\n\n"
            + "\n".join(
                f"• {item['name']} — {price_text(item['price'])}"
                for item in cart
            )
            + f"\n\n💰 {tr(user_id, 'total')}: {price_text(cart_total(cart))}"
        )

        await update.message.reply_text(
            preview,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    tr(user_id, "confirm"),
                    callback_data="order:confirm"
                )],
                [InlineKeyboardButton(
                    tr(user_id, "cancel"),
                    callback_data="order:cancel"
                )],
            ]),
        )


# ============================================================
# MAIN MENU / FALLBACK
# ============================================================

async def main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    register_user(update)
    await show_text(
        update,
        tr(update.effective_user.id, "menu"),
        main_keyboard(update.effective_user.id),
    )


async def unknown_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    await show_text(
        update,
        tr(update.effective_user.id, "menu"),
        main_keyboard(update.effective_user.id),
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception: %s", context.error)


# ============================================================
# APPLICATION
# ============================================================

async def post_init(application: Application) -> None:
    # Polling and webhook mode must not run simultaneously.
    await application.bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook cleared; polling is ready")


def build_application() -> Application:
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(False)
        .post_init(post_init)
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))

    # Language / main
    app.add_handler(CallbackQueryHandler(language_callback, pattern=r"^lang:"))
    app.add_handler(CallbackQueryHandler(language_handler, pattern=r"^language$"))
    app.add_handler(CallbackQueryHandler(main_handler, pattern=r"^main$"))

    # Customer catalog
    app.add_handler(CallbackQueryHandler(catalog_handler, pattern=r"^catalog$"))
    app.add_handler(CallbackQueryHandler(category_handler, pattern=r"^cat:"))
    app.add_handler(CallbackQueryHandler(brand_handler, pattern=r"^brand:"))
    app.add_handler(CallbackQueryHandler(product_handler, pattern=r"^product:"))
    app.add_handler(CallbackQueryHandler(variants_handler, pattern=r"^variants:"))
    app.add_handler(CallbackQueryHandler(add_handler, pattern=r"^add:"))

    # Cart / order
    app.add_handler(CallbackQueryHandler(cart_handler, pattern=r"^cart$"))
    app.add_handler(CallbackQueryHandler(remove_last_handler, pattern=r"^remove_last$"))
    app.add_handler(CallbackQueryHandler(clear_cart_handler, pattern=r"^clear_cart$"))
    app.add_handler(CallbackQueryHandler(checkout_handler, pattern=r"^checkout$"))
    app.add_handler(CallbackQueryHandler(order_callback, pattern=r"^order:"))

    # Admin main callbacks
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^adm:"))

    # Photos first, then text.
    app.add_handler(MessageHandler(filters.PHOTO, admin_photo_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, customer_text_router))

    app.add_handler(CallbackQueryHandler(unknown_callback_handler))
    app.add_error_handler(error_handler)
    return app


def main() -> None:
    logger.info("Bot started")
    build_application().run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
