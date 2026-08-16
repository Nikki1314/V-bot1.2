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
# 1. CONFIGURATION
# ============================================================
# Усі критичні параметри читаються ЛИШЕ зі змінних середовища.
# Токен та ID адміністраторів ніколи не зашиваються в код напряму.

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_dir() -> Path:
    """Визначає директорію для постійного зберігання даних.

    Порядок пріоритету:
      1. DATA_DIR (явно вказана директорія)
      2. RAILWAY_VOLUME_MOUNT_PATH (змонтований persistent volume Railway)
      3. локальна папка ./data (для розробки на своїй машині)

    Директорія створюється автоматично, якщо її ще не існує.
    """
    candidate = os.getenv("DATA_DIR") or os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    path = Path(candidate) if candidate else (BASE_DIR / "data")
    path.mkdir(parents=True, exist_ok=True)
    return path


DATA_DIR = resolve_data_dir()

SEED_CATALOG_PATH = BASE_DIR / "catalog.json"
CATALOG_PATH = DATA_DIR / "catalog.json"
ORDERS_PATH = DATA_DIR / "orders.json"
USERS_PATH = DATA_DIR / "users.json"
REVIEWS_PATH = DATA_DIR / "reviews.json"

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")


def parse_admin_ids() -> set[int]:
    """Читає список ID адміністраторів зі змінної середовища ADMIN_IDS.

    Формат: список ID через кому, напр. "7212962967,5522897576".
    Якщо змінна не задана — використовується резервний список,
    що зберігає сумісність із попередньою версією бота.
    """
    raw = os.getenv("ADMIN_IDS", "")
    ids = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            ids.add(int(chunk))
    if not ids:
        # Резервні значення — ті самі адміни, що були в попередній версії бота.
        ids = {7212962967, 5522897576}
    return ids


ADMIN_IDS = parse_admin_ids()
# Всі адміністратори отримують сповіщення про нові замовлення й відгуки.
ORDER_ADMIN_IDS = tuple(ADMIN_IDS)

# Статуси замовлень та порядок їх відображення в адмін-панелі.
ORDER_STATUSES = ["new", "processing", "shipped", "completed", "cancelled"]

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============================================================
# 2. LOCALIZATION
# ============================================================
# Централізована система перекладів. Нові рядки додаються сюди,
# а не хардкодяться безпосередньо в обробниках.

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
        "payment_question": "💳 Як бажаєте оплатити замовлення?",
        "payment_card": "💳 Карта",
        "payment_cash": "💵 Готівка",
        "feedback": "⭐ Залишити відгук",
        "feedback_prompt": "⭐ Напишіть ваш відгук одним повідомленням. Дякуємо!",
        "feedback_sent": "✅ Дякуємо за ваш відгук! Ми отримали його.",
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
        "order_status_new": "🆕 Нове",
        "order_status_processing": "⚙️ В обробці",
        "order_status_shipped": "🚚 Відправлено",
        "order_status_completed": "✅ Виконано",
        "order_status_cancelled": "❌ Скасовано",
        "order_status_changed": "📦 Статус вашого замовлення #{order_id} змінено на: {status}",
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
        "payment_question": "💳 Как вы хотите оплатить заказ?",
        "payment_card": "💳 Карта",
        "payment_cash": "💵 Наличные",
        "feedback": "⭐ Оставить отзыв",
        "feedback_prompt": "⭐ Напишите ваш отзыв одним сообщением. Спасибо!",
        "feedback_sent": "✅ Спасибо за ваш отзыв! Мы его получили.",
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
        "order_status_new": "🆕 Новый",
        "order_status_processing": "⚙️ В обработке",
        "order_status_shipped": "🚚 Отправлен",
        "order_status_completed": "✅ Выполнен",
        "order_status_cancelled": "❌ Отменён",
        "order_status_changed": "📦 Статус вашего заказа #{order_id} изменён на: {status}",
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
        "payment_question": "💳 Wie möchten Sie bezahlen?",
        "payment_card": "💳 Karte",
        "payment_cash": "💵 Barzahlung",
        "feedback": "⭐ Bewertung abgeben",
        "feedback_prompt": "⭐ Schreiben Sie Ihre Bewertung in einer Nachricht. Vielen Dank!",
        "feedback_sent": "✅ Vielen Dank für Ihre Bewertung! Wir haben sie erhalten.",
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
        "order_status_new": "🆕 Neu",
        "order_status_processing": "⚙️ In Bearbeitung",
        "order_status_shipped": "🚚 Versandt",
        "order_status_completed": "✅ Abgeschlossen",
        "order_status_cancelled": "❌ Storniert",
        "order_status_changed": "📦 Der Status Ihrer Bestellung #{order_id} wurde geändert zu: {status}",
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
        "payment_question": "💳 How would you like to pay?",
        "payment_card": "💳 Card",
        "payment_cash": "💵 Cash",
        "feedback": "⭐ Leave a review",
        "feedback_prompt": "⭐ Please write your review in one message. Thank you!",
        "feedback_sent": "✅ Thank you for your review! We received it.",
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
        "order_status_new": "🆕 New",
        "order_status_processing": "⚙️ Processing",
        "order_status_shipped": "🚚 Shipped",
        "order_status_completed": "✅ Completed",
        "order_status_cancelled": "❌ Cancelled",
        "order_status_changed": "📦 Your order #{order_id} status changed to: {status}",
    },
}


def tr(user_id: Optional[int], key: str) -> str:
    lang = get_user_language(user_id)
    return T.get(lang, T["uk"]).get(key, T["uk"].get(key, key))


def status_label(lang: str, status: str) -> str:
    """Повертає локалізовану назву статусу замовлення."""
    return T.get(lang, T["uk"]).get(f"order_status_{status}", status)


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
# 3. JSON PERSISTENCE (атомарний запис)
# ============================================================

def read_json(path: Path, default: Any) -> Any:
    """Безпечне читання JSON. Якщо файл відсутній або пошкоджений —
    повертає default і не зупиняє роботу бота."""
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Cannot read %s", path)
        return default


def write_json(path: Path, data: Any) -> bool:
    """Атомарний запис JSON: спочатку у тимчасовий файл, потім
    заміна оригіналу (os.replace є атомарною операцією на диску).
    Це захищає файл від пошкодження при аварійному завершенні процесу."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with open(tmp, "r+", encoding="utf-8") as fh:
            fh.flush()
            os.fsync(fh.fileno())
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
    """Завантажує catalog.json з persistent-директорії. Якщо його там
    ще немає, але поруч зі скриптом лежить початковий (seed) каталог —
    копіює його один раз, щоб не втратити наявні дані при першому
    деплої на Railway з підключеним volume."""
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
    catalog = normalize_catalog(catalog)
    return catalog


def normalize_catalog(raw: Any) -> dict[str, Any]:
    """Шар сумісності зі старими структурами catalog.json.

    Підтримує:
      - новий формат {"categories": {key: {"title","brands":{...}}}}
      - старий формат, де замість "brands" використовувалося "products"
      - старий формат, де категорії лежали під ключем "items" на
        верхньому рівні (без вкладеності brands)

    Мета — ніколи не зламати завантаження існуючого каталогу, а
    привести його до єдиної внутрішньої структури:
        {"currency": ..., "categories": {ck: {"title", "photo", "brands": {bk: {"title","photo","items":[...]}}}}}
    """
    if not isinstance(raw, dict):
        return {"currency": "EUR", "categories": {}}

    normalized: dict[str, Any] = {
        "currency": raw.get("currency", "EUR"),
        "categories": {},
    }

    raw_categories = raw.get("categories")
    if not isinstance(raw_categories, dict):
        raw_categories = {}

    for ck, category in raw_categories.items():
        if not isinstance(category, dict):
            continue
        norm_cat = {
            "title": category.get("title", ck),
            "brands": {},
        }
        if category.get("photo"):
            norm_cat["photo"] = category["photo"]

        # Старі каталоги іноді називали розділ товарів "products"
        # замість "brands". Підтримуємо обидва варіанти.
        raw_brands = category.get("brands")
        if not isinstance(raw_brands, dict):
            raw_brands = category.get("products")
        if not isinstance(raw_brands, dict):
            raw_brands = {}

        for bk, brand in raw_brands.items():
            if not isinstance(brand, dict):
                continue
            items = brand.get("items")
            if not isinstance(items, list):
                items = []
            norm_cat["brands"][bk] = {
                "title": brand.get("title", bk),
                "items": items,
            }
            if brand.get("photo"):
                norm_cat["brands"][bk]["photo"] = brand["photo"]

        # Якщо у старій категорії товари лежали напряму в "items"
        # (без розділів-брендів), створюємо для них один розділ за замовчуванням.
        if not norm_cat["brands"] and isinstance(category.get("items"), list):
            norm_cat["brands"]["default"] = {
                "title": "Товари",
                "items": category["items"],
            }

        normalized["categories"][ck] = norm_cat

    return normalized


CATALOG = load_catalog()


def save_catalog() -> bool:
    return write_json(CATALOG_PATH, CATALOG)


def save_order(order: dict[str, Any]) -> bool:
    """Зберігає нове замовлення. Замовлення НІКОЛИ не втрачається:
    спочатку відбувається запис у файл, і лише потім (окремо, у
    викликаючому коді) — спроба сповістити адміністраторів."""
    orders = read_json(ORDERS_PATH, [])
    if not isinstance(orders, list):
        orders = []
    orders.append(order)
    return write_json(ORDERS_PATH, orders)


def load_orders() -> list[dict[str, Any]]:
    orders = read_json(ORDERS_PATH, [])
    return orders if isinstance(orders, list) else []


def update_order(order_id: str, **fields: Any) -> Optional[dict[str, Any]]:
    """Оновлює поля замовлення за його ID та атомарно зберігає файл.
    Зміна статусу замовлення НІКОЛИ не відкатується через помилку
    сповіщення користувача — спочатку зберігаємо, потім сповіщаємо."""
    orders = load_orders()
    for order in orders:
        if order.get("order_id") == order_id:
            order.update(fields)
            write_json(ORDERS_PATH, orders)
            return order
    return None


def find_order(order_id: str) -> Optional[dict[str, Any]]:
    for order in load_orders():
        if order.get("order_id") == order_id:
            return order
    return None


def save_review(review: dict[str, Any]) -> bool:
    reviews = read_json(REVIEWS_PATH, [])
    if not isinstance(reviews, list):
        reviews = []
    reviews.append(review)
    return write_json(REVIEWS_PATH, reviews)


def load_reviews() -> list[dict[str, Any]]:
    reviews = read_json(REVIEWS_PATH, [])
    return reviews if isinstance(reviews, list) else []


def update_review(review_id: str, **fields: Any) -> Optional[dict[str, Any]]:
    reviews = load_reviews()
    for review in reviews:
        if review.get("review_id") == review_id:
            review.update(fields)
            write_json(REVIEWS_PATH, reviews)
            return review
    return None


def delete_review(review_id: str) -> bool:
    reviews = load_reviews()
    filtered = [r for r in reviews if r.get("review_id") != review_id]
    if len(filtered) == len(reviews):
        return False
    return write_json(REVIEWS_PATH, filtered)


# ============================================================
# 4. CATALOG COMPATIBILITY HELPERS
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


def category_has_products(category_key: str) -> bool:
    """Перевіряє, чи має категорія хоч один товар — використовується
    для безпечного видалення категорій (щоб не втратити товари випадково)."""
    for brand in brands_get(category_key).values():
        if isinstance(brand, dict) and items_get(brand):
            return True
    return False


# ============================================================
# 5. UI HELPERS
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
        [InlineKeyboardButton(tr(user_id, "feedback"), callback_data="feedback")],
        [InlineKeyboardButton(tr(user_id, "language"), callback_data="language")],
    ])


def admin_keyboard() -> InlineKeyboardMarkup:
    """Головне меню адмін-панелі — структура відповідає ТЗ:
    Замовлення / Товари / Категорії / Відгуки / Статистика / Розсилка."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📦 Замовлення", callback_data="adm:orders"),
            InlineKeyboardButton("🛠 Товари", callback_data="adm:products"),
        ],
        [
            InlineKeyboardButton("📁 Категорії", callback_data="adm:categories"),
            InlineKeyboardButton("⭐ Відгуки", callback_data="adm:reviews"),
        ],
        [
            InlineKeyboardButton("📊 Статистика", callback_data="adm:stats"),
            InlineKeyboardButton("📣 Розсилка", callback_data="adm:broadcast"),
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
# 6. START / LANGUAGE
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
# 7. CUSTOMER CATALOG
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
    description = product.get("description")
    text = f"🧾 {product['name']}\n"
    if description:
        text += f"{description}\n"
    text += f"💶 {price_text(product['price'])}\n{status}"

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
# 8. CART
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
# 9. CHECKOUT / ORDERS
# ============================================================

def valid_time(value: str) -> bool:
    value = value.strip()
    single = re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value)
    interval = re.fullmatch(
        r"([01]\d|2[0-3]):[0-5]\d\s*-\s*([01]\d|2[0-3]):[0-5]\d",
        value,
    )
    return bool(single or interval)


def order_preview(user: Any, cart: list[dict[str, Any]], data: dict[str, Any], order_id: str) -> str:
    """Формує повний текст сповіщення для адміністраторів про нове замовлення."""
    items = "\n".join(
        f"• {item['name']} — {price_text(item['price'])}"
        for item in cart
    )
    username_line = f"🔗 @{user.username}\n" if user.username else ""
    return (
        "📦 НОВЕ ЗАМОВЛЕННЯ\n\n"
        f"🆔 Замовлення: #{order_id}\n\n"
        f"👤 {user.full_name}\n"
        f"{username_line}"
        f"🆔 Telegram ID: {user.id}\n\n"
        f"🛍 Товари:\n{items}\n\n"
        f"💰 Разом: {price_text(cart_total(cart))}\n"
        f"📍 Місто/район: {data['city']}\n"
        f"📅 Дата отримання: {data['date']}\n"
        f"🕒 Час: {data['time']}\n"
        f"💳 Оплата: {data.get('payment', 'не вказано')}\n"
        f"📌 Статус: {status_label('uk', 'new')}"
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


async def payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    query = update.callback_query
    method = query.data.split(":", 1)[1] if query and query.data else ""
    flow = context.user_data.get("order_flow")
    user = update.effective_user
    if not isinstance(flow, dict) or flow.get("step") != "payment" or not user:
        return

    labels = {"card": tr(user.id, "payment_card"), "cash": tr(user.id, "payment_cash")}
    if method not in labels:
        return

    flow["payment"] = labels[method]
    flow["step"] = "confirm"
    cart = cart_get(context)
    preview = (
        f"{tr(user.id, 'order_confirm')}\n\n"
        f"📍 {flow['city']}\n"
        f"📅 {flow['date']}\n"
        f"🕒 {flow['time']}\n"
        f"💳 {labels[method]}\n\n"
        + "\n".join(f"• {item['name']} — {price_text(item['price'])}" for item in cart)
        + f"\n\n💰 {tr(user.id, 'total')}: {price_text(cart_total(cart))}"
    )
    await show_text(update, preview, InlineKeyboardMarkup([
        [InlineKeyboardButton(tr(user.id, "confirm"), callback_data="order:confirm")],
        [InlineKeyboardButton(tr(user.id, "cancel"), callback_data="order:cancel")],
    ]))


async def feedback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    user = update.effective_user
    if not user:
        return
    context.user_data["feedback_flow"] = True
    await show_text(update, tr(user.id, "feedback_prompt"), InlineKeyboardMarkup([
        [InlineKeyboardButton(tr(user.id, "cancel"), callback_data="feedback:cancel")]
    ]))


async def feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    query = update.callback_query
    action = query.data.split(":", 1)[1] if query and query.data else ""
    if action == "cancel":
        context.user_data.pop("feedback_flow", None)
        await show_text(update, tr(update.effective_user.id, "menu"), main_keyboard(update.effective_user.id))


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

        if not isinstance(flow, dict) or not user or not cart or not flow.get("payment"):
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
            "payment": flow["payment"],
            "delivery": {
                "city_or_district": flow["city"],
                "date": flow["date"],
                "time": flow["time"],
            },
            "created_at": now.isoformat(timespec="seconds"),
            "status": "new",
        }

        # КРИТИЧНО: замовлення спершу зберігається у постійне сховище,
        # і лише потім бот намагається сповістити адміністраторів.
        if not save_order(order):
            logger.error("Cannot save order %s", order_id)
            await show_text(update, tr(user.id, "order_failed"))
            return

        text = order_preview(user, cart, flow, order_id)
        delivered_count = 0
        for admin_id in ORDER_ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=text)
                delivered_count += 1
            except Exception:
                # Помилка сповіщення НЕ впливає на вже збережене замовлення.
                logger.exception("Cannot send order %s to admin %s", order_id, admin_id)

        if delivered_count == 0:
            logger.error("Order %s was saved but no admin notification was delivered", order_id)

        context.user_data["cart"] = []
        context.user_data.pop("order_flow", None)

        await show_text(
            update,
            tr(user.id, "order_sent"),
            main_keyboard(user.id),
        )


# ============================================================
# 10. ADMIN — ДОСТУП
# ============================================================

def admin_allowed(update: Update) -> bool:
    """Перевіряє ID користувача проти списку ADMIN_IDS.
    Викликається в КОЖНОМУ адмін-обробнику (а не лише при показі кнопки),
    щоб неавторизований користувач не міг виконати адмін-дію напряму
    через підроблений callback_data."""
    return bool(update.effective_user and update.effective_user.id in ADMIN_IDS)


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


# ============================================================
# 11. ADMIN — ГОЛОВНИЙ РОУТЕР CALLBACK'ІВ
# ============================================================

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    if not admin_allowed(update):
        await deny_admin(update)
        return

    query = update.callback_query
    data = query.data if query else ""
    action = data[4:] if data.startswith("adm:") else ""

    # --- Головне меню / категорії --------------------------------------
    if action == "home":
        await show_text(update, "⚙️ Адмін-панель", admin_keyboard())
    elif action == "categories":
        await admin_categories(update, context)
    elif action == "addcat":
        context.user_data["admin_flow"] = {"step": "add_category_name"}
        await show_text(update, "📁 Надішліть назву нової категорії.")
    elif action.startswith("cat:"):
        await admin_category_actions(update, context, action.split(":", 1)[1])
    elif action.startswith("renamecat:"):
        key = action.split(":", 1)[1]
        context.user_data["admin_flow"] = {"step": "rename_category", "category_key": key}
        await show_text(update, "✏️ Надішліть нову назву категорії.")
    elif action.startswith("catdesc:"):
        key = action.split(":", 1)[1]
        context.user_data["admin_flow"] = {"step": "category_description", "category_key": key}
        await show_text(update, "📝 Надішліть новий опис категорії (або «пропустити»).")
    elif action.startswith("catphoto:"):
        key = action.split(":", 1)[1]
        context.user_data["admin_flow"] = {"step": "category_photo", "category_key": key}
        await show_text(update, "🖼 Надішліть нове фото категорії.")
    elif action.startswith("delcat:"):
        key = action.split(":", 1)[1]
        if category_has_products(key):
            # Категорія має товари — видалення потребує явного підтвердження,
            # щоб адміністратор не втратив товари випадково.
            await show_text(
                update,
                "⚠️ У цій категорії є товари. Видалити категорію РАЗОМ із товарами?",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑 Так, видалити все", callback_data=f"adm:delcatforce:{key}")],
                    [InlineKeyboardButton("⬅️ Скасувати", callback_data=f"adm:cat:{key}")],
                ]),
            )
        else:
            categories().pop(key, None)
            save_catalog()
            await show_text(update, "✅ Категорію видалено.", admin_keyboard())
    elif action.startswith("delcatforce:"):
        key = action.split(":", 1)[1]
        categories().pop(key, None)
        save_catalog()
        await show_text(update, "✅ Категорію та її товари видалено.", admin_keyboard())

    # --- Товари ----------------------------------------------------------
    elif action == "products":
        await admin_products(update, context)
    elif action == "addproduct":
        await admin_add_product_start(update, context)
    elif action.startswith("addprodcat:"):
        await admin_add_product_choose_brand(update, context, action.split(":", 1)[1])
    elif action.startswith("addprodbk:"):
        parts = action.split(":")
        if len(parts) == 3:
            ck, bk = parts[1], parts[2]
            if not brand_get(ck, bk):
                await show_text(update, "❌ Розділ не знайдено.")
            else:
                context.user_data["admin_flow"] = {
                    "step": "add_product_name",
                    "category_key": ck,
                    "brand_key": bk,
                }
                await show_text(update, "➕ Надішліть назву товару.")
    elif action.startswith("brand:"):
        await admin_brand_products(update, context, action.split(":"))
    elif action.startswith("branditems:"):
        parts = action.split(":")
        if len(parts) == 3:
            await admin_brand_items(update, context, parts[1], parts[2])
    elif action.startswith("item:"):
        await admin_product_actions(update, context, action.split(":"))
    elif action.startswith("toggle:"):
        await admin_toggle_product(update, context, action.split(":"))
    elif action.startswith("photo:"):
        await admin_product_photo_start(update, context, action.split(":"))
    elif action.startswith("editname:"):
        await admin_product_edit_start(update, context, action.split(":"), "edit_product_name", "✏️ Надішліть нову назву товару.")
    elif action.startswith("editdesc:"):
        await admin_product_edit_start(update, context, action.split(":"), "edit_product_description", "📝 Надішліть новий опис товару (або «пропустити»).")
    elif action.startswith("editprice:"):
        await admin_product_edit_start(update, context, action.split(":"), "edit_product_price", "💶 Надішліть нову ціну, наприклад 19.99")
    elif action.startswith("delete:"):
        await admin_delete_product(update, context, action.split(":"))

    # --- Замовлення --------------------------------------------------------
    elif action == "orders":
        await admin_orders_list(update, context)
    elif action.startswith("order:"):
        await admin_order_detail(update, context, action.split(":", 1)[1])
    elif action.startswith("orderstatus:"):
        parts = action.split(":")
        if len(parts) == 3:
            await admin_order_set_status(update, context, order_id=parts[1], new_status=parts[2])

    # --- Відгуки -----------------------------------------------------------
    elif action == "reviews":
        await admin_reviews_list(update, context)
    elif action.startswith("review:"):
        await admin_review_detail(update, context, action.split(":", 1)[1])
    elif action.startswith("reviewtoggle:"):
        await admin_review_toggle(update, context, action.split(":", 1)[1])
    elif action.startswith("reviewdelete:"):
        await admin_review_delete(update, context, action.split(":", 1)[1])

    # --- Статистика / розсилка ---------------------------------------------
    elif action == "stats":
        await admin_stats(update, context)
    elif action == "broadcast":
        context.user_data["admin_flow"] = {"step": "broadcast_text"}
        await show_text(update, T["uk"]["admin_broadcast_text"])
    elif action.startswith("broadcast:"):
        await admin_broadcast_action(update, context, action.split(":", 1)[1])


# ============================================================
# 12. ADMIN — КАТЕГОРІЇ
# ============================================================

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
    if not buttons:
        buttons.append([InlineKeyboardButton("Категорій ще немає", callback_data="adm:categories")])
    buttons.append([InlineKeyboardButton("➕ Додати категорію", callback_data="adm:addcat")])
    buttons.append([InlineKeyboardButton("⬅️ Адмін-панель", callback_data="adm:home")])
    await show_text(update, "📁 Категорії\n\nОберіть категорію для редагування:", InlineKeyboardMarkup(buttons))


async def admin_category_actions(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str) -> None:
    category = category_get(key)
    if not category:
        await show_text(update, "❌ Категорію не знайдено.", admin_keyboard())
        return

    description = category.get("description", "—")
    await show_text(
        update,
        f"📁 {category.get('title', key)}\n📝 {description}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Змінити назву", callback_data=f"adm:renamecat:{key}")],
            [InlineKeyboardButton("📝 Змінити опис", callback_data=f"adm:catdesc:{key}")],
            [InlineKeyboardButton("🖼 Змінити фото", callback_data=f"adm:catphoto:{key}")],
            [InlineKeyboardButton("🗑 Видалити", callback_data=f"adm:delcat:{key}")],
            [InlineKeyboardButton("⬅️ Категорії", callback_data="adm:categories")],
        ]),
    )


# ============================================================
# 13. ADMIN — ТОВАРИ
# ============================================================

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
    buttons.append([InlineKeyboardButton("➕ Додати товар", callback_data="adm:addproduct")])
    buttons.append([InlineKeyboardButton("⬅️ Адмін-панель", callback_data="adm:home")])
    await show_text(update, "🛠 Товари\n\nОберіть категорію:", InlineKeyboardMarkup(buttons))


async def admin_brand_products(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> None:
    if len(parts) < 2:
        return
    ck = parts[1]
    category = category_get(ck)
    if not category:
        await show_text(update, "❌ Категорію не знайдено.")
        return

    buttons = []
    for bk, brand in brands_get(ck).items():
        if isinstance(brand, dict):
            buttons.append([
                InlineKeyboardButton(
                    f"🏷 {brand.get('title', bk)}",
                    callback_data=f"adm:branditems:{ck}:{bk}",
                )
            ])

    if not buttons:
        bk = unique_key("brand", brands_get(ck))
        brands_get(ck)[bk] = {"title": "Товари", "items": []}
        save_catalog()
        buttons.append([InlineKeyboardButton("🏷 Товари", callback_data=f"adm:branditems:{ck}:{bk}")])

    buttons.append([InlineKeyboardButton("⬅️ Товари", callback_data="adm:products")])
    await show_text(update, f"📁 {category.get('title', ck)}", InlineKeyboardMarkup(buttons))


async def admin_brand_items(update: Update, context: ContextTypes.DEFAULT_TYPE, ck: str, bk: str) -> None:
    brand = brand_get(ck, bk)
    if not brand:
        await show_text(update, "❌ Розділ не знайдено.")
        return

    buttons = []
    for i, product in enumerate(items_get(brand)):
        if isinstance(product, dict) and "name" in product and "price" in product:
            icon = "✅" if is_available(product) else "❌"
            buttons.append([
                InlineKeyboardButton(f"{icon} {product['name']}", callback_data=f"adm:item:{ck}:{bk}:{i}")
            ])

    if not buttons:
        buttons.append([InlineKeyboardButton("➕ Додати товар", callback_data="adm:addproduct")])

    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"adm:brand:{ck}")])
    await show_text(update, f"🏷 {brand.get('title', bk)}", InlineKeyboardMarkup(buttons))


async def admin_product_actions(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> None:
    if len(parts) != 4:
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
    description = product.get("description", "—")
    await show_text(
        update,
        f"🧾 {product.get('name', 'Товар')}\n📝 {description}\n💶 {price_text(product.get('price'))}\n{status}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Змінити назву", callback_data=f"adm:editname:{ck}:{bk}:{index}")],
            [InlineKeyboardButton("📝 Змінити опис", callback_data=f"adm:editdesc:{ck}:{bk}:{index}")],
            [InlineKeyboardButton("💶 Змінити ціну", callback_data=f"adm:editprice:{ck}:{bk}:{index}")],
            [InlineKeyboardButton("🔄 Змінити наявність", callback_data=f"adm:toggle:{ck}:{bk}:{index}")],
            [InlineKeyboardButton("🖼 Змінити фото", callback_data=f"adm:photo:{ck}:{bk}:{index}")],
            [InlineKeyboardButton("🗑 Видалити", callback_data=f"adm:delete:{ck}:{bk}:{index}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"adm:branditems:{ck}:{bk}")],
        ]),
    )


async def admin_add_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not categories():
        await show_text(
            update,
            "❌ Спочатку створіть категорію.",
            InlineKeyboardMarkup([[InlineKeyboardButton("➕ Додати категорію", callback_data="adm:addcat")]]),
        )
        return

    buttons = []
    for ck, category in categories().items():
        if isinstance(category, dict):
            buttons.append([
                InlineKeyboardButton(str(category.get("title", ck)), callback_data=f"adm:addprodcat:{ck}")
            ])
    buttons.append([InlineKeyboardButton("⬅️ Адмін-панель", callback_data="adm:home")])
    await show_text(update, "➕ Виберіть категорію:", InlineKeyboardMarkup(buttons))


async def admin_add_product_choose_brand(update: Update, context: ContextTypes.DEFAULT_TYPE, ck: str) -> None:
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
        [InlineKeyboardButton(str(brand.get("title", bk)), callback_data=f"adm:addprodbk:{ck}:{bk}")]
        for bk, brand in brands.items()
        if isinstance(brand, dict)
    ]
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="adm:products")])
    await show_text(update, "🏷 Виберіть розділ товарів:", InlineKeyboardMarkup(buttons))


async def admin_product_edit_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parts: list[str],
    step: str,
    prompt: str,
) -> None:
    if len(parts) != 4:
        return
    context.user_data["admin_flow"] = {
        "step": step,
        "category_key": parts[1],
        "brand_key": parts[2],
        "index": int(parts[3]),
    }
    await show_text(update, prompt)


async def admin_toggle_product(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> None:
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


async def admin_product_photo_start(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> None:
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


async def admin_delete_product(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> None:
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
# 14. ADMIN — ЗАМОВЛЕННЯ
# ============================================================

ORDERS_PAGE_SIZE = 15


async def admin_orders_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показує останні замовлення (найновіші зверху)."""
    orders = list(reversed(load_orders()))[:ORDERS_PAGE_SIZE]
    if not orders:
        await show_text(
            update,
            "📦 Замовлень ще немає.",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Адмін-панель", callback_data="adm:home")]]),
        )
        return

    buttons = []
    for order in orders:
        icon = {
            "new": "🆕", "processing": "⚙️", "shipped": "🚚",
            "completed": "✅", "cancelled": "❌",
        }.get(order.get("status", "new"), "🆕")
        label = f"{icon} #{order.get('order_id')} — {price_text(order.get('total', 0))}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"adm:order:{order.get('order_id')}")])

    buttons.append([InlineKeyboardButton("⬅️ Адмін-панель", callback_data="adm:home")])
    await show_text(update, f"📦 Останні замовлення ({len(orders)}):", InlineKeyboardMarkup(buttons))


async def admin_order_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str) -> None:
    order = find_order(order_id)
    if not order:
        await show_text(update, "❌ Замовлення не знайдено.", admin_keyboard())
        return

    items_text = "\n".join(
        f"• {item.get('name')} — {price_text(item.get('price'))}"
        for item in order.get("items", [])
    )
    delivery = order.get("delivery", {})
    username_line = f"🔗 @{order['username']}\n" if order.get("username") else ""
    text = (
        f"📦 Замовлення #{order_id}\n\n"
        f"👤 {order.get('full_name', '—')}\n"
        f"{username_line}"
        f"🆔 Telegram ID: {order.get('user_id')}\n\n"
        f"🛍 Товари:\n{items_text}\n\n"
        f"💰 Разом: {price_text(order.get('total', 0))}\n"
        f"📍 {delivery.get('city_or_district', '—')}\n"
        f"📅 {delivery.get('date', '—')} {delivery.get('time', '—')}\n"
        f"💳 {order.get('payment', '—')}\n"
        f"🕒 Створено: {order.get('created_at', '—')}\n"
        f"📌 Статус: {status_label('uk', order.get('status', 'new'))}"
    )

    status_buttons = []
    for status in ORDER_STATUSES:
        if status != order.get("status"):
            status_buttons.append(
                InlineKeyboardButton(
                    status_label("uk", status),
                    callback_data=f"adm:orderstatus:{order_id}:{status}",
                )
            )
    # По два статуси в ряд для компактності.
    rows = [status_buttons[i:i + 2] for i in range(0, len(status_buttons), 2)]
    rows.append([InlineKeyboardButton("⬅️ Замовлення", callback_data="adm:orders")])
    await show_text(update, text, InlineKeyboardMarkup(rows))


async def admin_order_set_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    order_id: str,
    new_status: str,
) -> None:
    """Змінює статус замовлення. Збереження статусу НЕ залежить від
    результату сповіщення користувача: спочатку зберігаємо, потім
    намагаємось сповістити (best-effort, з ловом усіх помилок)."""
    if new_status not in ORDER_STATUSES:
        return

    order = update_order(order_id, status=new_status)
    if not order:
        await show_text(update, "❌ Замовлення не знайдено.", admin_keyboard())
        return

    user_id = order.get("user_id")
    lang = order.get("language", "uk")
    if user_id:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=T.get(lang, T["uk"])["order_status_changed"].format(
                    order_id=order_id,
                    status=status_label(lang, new_status),
                ),
            )
        except Forbidden:
            logger.info("User %s blocked the bot; status notification skipped", user_id)
        except Exception:
            logger.exception("Cannot notify user %s about order %s status change", user_id, order_id)

    await admin_order_detail(update, context, order_id)


# ============================================================
# 15. ADMIN — ВІДГУКИ
# ============================================================

async def admin_reviews_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reviews = list(reversed(load_reviews()))[:ORDERS_PAGE_SIZE]
    if not reviews:
        await show_text(
            update,
            "⭐ Відгуків ще немає.",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Адмін-панель", callback_data="adm:home")]]),
        )
        return

    buttons = []
    for review in reviews:
        icon = "👁" if review.get("visible", True) else "🙈"
        preview = str(review.get("text", ""))[:30]
        buttons.append([
            InlineKeyboardButton(f"{icon} {preview}", callback_data=f"adm:review:{review.get('review_id')}")
        ])
    buttons.append([InlineKeyboardButton("⬅️ Адмін-панель", callback_data="adm:home")])
    await show_text(update, f"⭐ Останні відгуки ({len(reviews)}):", InlineKeyboardMarkup(buttons))


async def admin_review_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, review_id: str) -> None:
    reviews = load_reviews()
    review = next((r for r in reviews if r.get("review_id") == review_id), None)
    if not review:
        await show_text(update, "❌ Відгук не знайдено.", admin_keyboard())
        return

    visible = review.get("visible", True)
    username_line = f"🔗 @{review['username']}\n" if review.get("username") else ""
    text = (
        f"⭐ Відгук\n\n"
        f"👤 {review.get('full_name', '—')}\n"
        f"{username_line}"
        f"🆔 Telegram ID: {review.get('user_id')}\n"
        f"🕒 {review.get('created_at', '—')}\n"
        f"👁 Видимість: {'показано' if visible else 'приховано'}\n\n"
        f"💬 {review.get('text', '')}"
    )
    toggle_label = "🙈 Приховати" if visible else "👁 Показати"
    await show_text(
        update,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton(toggle_label, callback_data=f"adm:reviewtoggle:{review_id}")],
            [InlineKeyboardButton("🗑 Видалити", callback_data=f"adm:reviewdelete:{review_id}")],
            [InlineKeyboardButton("⬅️ Відгуки", callback_data="adm:reviews")],
        ]),
    )


async def admin_review_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, review_id: str) -> None:
    reviews = load_reviews()
    review = next((r for r in reviews if r.get("review_id") == review_id), None)
    if review:
        update_review(review_id, visible=not review.get("visible", True))
    await admin_review_detail(update, context, review_id)


async def admin_review_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, review_id: str) -> None:
    delete_review(review_id)
    await admin_reviews_list(update, context)


# ============================================================
# 16. ADMIN — СТАТИСТИКА
# ============================================================

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Рахує статистику. КРИТИЧНО: дохід і популярні товари рахуються
    ЛИШЕ по замовленнях зі статусом "completed"."""
    orders = load_orders()
    users = read_json(USERS_PATH, {})

    total_orders = len(orders)
    completed = [o for o in orders if o.get("status") == "completed"]
    cancelled = [o for o in orders if o.get("status") == "cancelled"]

    revenue = round(sum(float(o.get("total", 0) or 0) for o in completed), 2)

    popularity: dict[str, int] = {}
    for order in completed:
        for item in order.get("items", []):
            name = str(item.get("name", "—"))
            popularity[name] = popularity.get(name, 0) + 1
    top_products = sorted(popularity.items(), key=lambda kv: kv[1], reverse=True)[:5]

    top_text = "\n".join(
        f"{i}. {name} — {count} прод."
        for i, (name, count) in enumerate(top_products, 1)
    ) or "—"

    text = (
        "📊 Статистика\n\n"
        f"👥 Користувачів: {len(users) if isinstance(users, dict) else 0}\n"
        f"📁 Категорій: {len(categories())}\n"
        f"🛍 Товарів: {len(all_products())}\n\n"
        f"📦 Всього замовлень: {total_orders}\n"
        f"✅ Виконано: {len(completed)}\n"
        f"❌ Скасовано: {len(cancelled)}\n\n"
        f"💰 Дохід (лише виконані): {price_text(revenue)}\n\n"
        f"🏆 Популярні товари:\n{top_text}"
    )
    await show_text(
        update,
        text,
        InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Адмін-панель", callback_data="adm:home")]]),
    )


# ============================================================
# 17. ADMIN — РОЗСИЛКА
# ============================================================

async def admin_broadcast_action(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
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
            await context.bot.send_message(chat_id=int(user_id_text), text=flow["text"])
            sent += 1
        except Forbidden:
            # Користувач заблокував бота — пропускаємо, не зупиняючи розсилку.
            blocked += 1
        except Exception:
            blocked += 1
            logger.exception("Broadcast failed for %s", user_id_text)

    context.user_data.pop("admin_flow", None)
    await show_text(
        update,
        f"📣 Розсилку завершено.\n\n✅ Надіслано: {sent}\n⚠️ Не доставлено: {blocked}",
        admin_keyboard(),
    )


# ============================================================
# 18. ADMIN — ТЕКСТОВИЙ РОУТЕР (покроковий ввід)
# ============================================================

SKIP_WORDS = {"пропустити", "пропустить", "skip", "überspringen", "-"}


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

    elif step == "category_description":
        category = category_get(flow.get("category_key", ""))
        if not category:
            await update.message.reply_text("❌ Категорію не знайдено.")
            return
        if text.lower() not in SKIP_WORDS:
            category["description"] = text
            save_catalog()
        context.user_data.pop("admin_flow", None)
        await update.message.reply_text("✅ Опис категорії оновлено.", reply_markup=admin_keyboard())

    elif step == "category_photo":
        if text.lower() in SKIP_WORDS:
            context.user_data.pop("admin_flow", None)
            await update.message.reply_text("Скасовано.", reply_markup=admin_keyboard())
            return

    elif step == "edit_product_name":
        product = find_product(flow.get("category_key", ""), flow.get("brand_key", ""), int(flow.get("index", -1)))
        if not product:
            context.user_data.pop("admin_flow", None)
            await update.message.reply_text("❌ Товар не знайдено.")
            return
        product["name"] = text
        save_catalog()
        context.user_data.pop("admin_flow", None)
        await update.message.reply_text("✅ Назву товару змінено.", reply_markup=admin_keyboard())

    elif step == "edit_product_description":
        product = find_product(flow.get("category_key", ""), flow.get("brand_key", ""), int(flow.get("index", -1)))
        if not product:
            context.user_data.pop("admin_flow", None)
            await update.message.reply_text("❌ Товар не знайдено.")
            return
        if text.lower() not in SKIP_WORDS:
            product["description"] = text
            save_catalog()
        context.user_data.pop("admin_flow", None)
        await update.message.reply_text("✅ Опис товару оновлено.", reply_markup=admin_keyboard())

    elif step == "edit_product_price":
        try:
            price = float(text.replace(",", "."))
            if price < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Некоректна ціна. Наприклад: 19.99")
            return
        product = find_product(flow.get("category_key", ""), flow.get("brand_key", ""), int(flow.get("index", -1)))
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
        flow["step"] = "add_product_description"
        await update.message.reply_text("📝 Надішліть опис товару (або «пропустити»).")

    elif step == "add_product_description":
        if text.lower() not in SKIP_WORDS:
            flow["description"] = text
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
        if text.lower() not in SKIP_WORDS:
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
        if flow.get("description"):
            product["description"] = flow["description"]
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
            f"📣 ПРЕВ'Ю\n\n{text}\n\nНадіслати всім користувачам?",
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
        await update.message.reply_text("Товар є в наявності? Напишіть: так/ні, да/нет, yes/no або ja/nein.")

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


# ============================================================
# 19. КЛІЄНТСЬКИЙ ТЕКСТОВИЙ РОУТЕР (кошик/оформлення/відгуки)
# ============================================================

async def customer_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    register_user(update)

    # Адмін-флоу мають пріоритет над клієнтськими.
    if admin_allowed(update) and context.user_data.get("admin_flow"):
        await admin_text_router(update, context)
        return

    if context.user_data.get("feedback_flow"):
        user = update.effective_user
        feedback_text = update.message.text.strip()
        if not feedback_text:
            return

        now = datetime.now()
        review_id = f"{user.id}-{int(now.timestamp())}"
        review = {
            "review_id": review_id,
            "user_id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "text": feedback_text,
            "created_at": now.isoformat(timespec="seconds"),
            "visible": True,
        }
        # Відгук спершу зберігається у reviews.json, і лише потім
        # відправляється сповіщення адміністраторам.
        save_review(review)

        delivered = 0
        username_line = f"🔗 @{user.username}\n" if user.username else ""
        notify_text = (
            "⭐ НОВИЙ ВІДГУК\n\n"
            f"👤 {user.full_name}\n"
            f"{username_line}"
            f"🆔 Telegram ID: {user.id}\n\n"
            f"💬 {feedback_text}"
        )
        for admin_id in ORDER_ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=notify_text)
                delivered += 1
            except Exception:
                logger.exception("Cannot send feedback to %s", admin_id)

        context.user_data.pop("feedback_flow", None)
        await update.message.reply_text(tr(user.id, "feedback_sent"), reply_markup=main_keyboard(user.id))
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
        flow["step"] = "payment"
        await update.message.reply_text(
            tr(user_id, "payment_question"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(tr(user_id, "payment_card"), callback_data="payment:card")],
                [InlineKeyboardButton(tr(user_id, "payment_cash"), callback_data="payment:cash")],
                [InlineKeyboardButton(tr(user_id, "cancel"), callback_data="order:cancel")],
            ]),
        )


# ============================================================
# 20. ГОЛОВНЕ МЕНЮ / FALLBACK / ПОМИЛКИ
# ============================================================

async def main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    register_user(update)
    await show_text(update, tr(update.effective_user.id, "menu"), main_keyboard(update.effective_user.id))


async def unknown_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ловить будь-які callback_data без відповідного обробника, щоб
    користувач ніколи не бачив "мертву" кнопку без реакції."""
    await answer_callback(update)
    await show_text(update, tr(update.effective_user.id, "menu"), main_keyboard(update.effective_user.id))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Глобальний обробник помилок: жодна необроблена помилка не має
    призводити до падіння всього бота."""
    logger.exception("Unhandled exception: %s", context.error)


# ============================================================
# 21. ЗАПУСК ДОДАТКУ
# ============================================================

async def post_init(application: Application) -> None:
    # Webhook та polling не можуть працювати одночасно.
    await application.bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook cleared; polling is ready. Data dir: %s", DATA_DIR)


def build_application() -> Application:
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(False)
        .post_init(post_init)
        .build()
    )

    # Команди
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))

    # Мова / головне меню
    app.add_handler(CallbackQueryHandler(language_callback, pattern=r"^lang:"))
    app.add_handler(CallbackQueryHandler(language_handler, pattern=r"^language$"))
    app.add_handler(CallbackQueryHandler(main_handler, pattern=r"^main$"))

    # Каталог клієнта
    app.add_handler(CallbackQueryHandler(catalog_handler, pattern=r"^catalog$"))
    app.add_handler(CallbackQueryHandler(category_handler, pattern=r"^cat:"))
    app.add_handler(CallbackQueryHandler(brand_handler, pattern=r"^brand:"))
    app.add_handler(CallbackQueryHandler(product_handler, pattern=r"^product:"))
    app.add_handler(CallbackQueryHandler(variants_handler, pattern=r"^variants:"))
    app.add_handler(CallbackQueryHandler(add_handler, pattern=r"^add:"))

    # Кошик / замовлення
    app.add_handler(CallbackQueryHandler(cart_handler, pattern=r"^cart$"))
    app.add_handler(CallbackQueryHandler(remove_last_handler, pattern=r"^remove_last$"))
    app.add_handler(CallbackQueryHandler(clear_cart_handler, pattern=r"^clear_cart$"))
    app.add_handler(CallbackQueryHandler(checkout_handler, pattern=r"^checkout$"))
    app.add_handler(CallbackQueryHandler(order_callback, pattern=r"^order:"))
    app.add_handler(CallbackQueryHandler(payment_callback, pattern=r"^payment:"))
    app.add_handler(CallbackQueryHandler(feedback_handler, pattern=r"^feedback$"))
    app.add_handler(CallbackQueryHandler(feedback_callback, pattern=r"^feedback:"))

    # Всі адмін-callback'и (категорії, товари, замовлення, відгуки, статистика, розсилка)
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^adm:"))

    # Спочатку фото, потім текст.
    app.add_handler(MessageHandler(filters.PHOTO, admin_photo_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, customer_text_router))

    app.add_handler(CallbackQueryHandler(unknown_callback_handler))
    app.add_error_handler(error_handler)
    return app


def main() -> None:
    logger.info("Bot started. Admins: %s", ADMIN_IDS)
    build_application().run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
