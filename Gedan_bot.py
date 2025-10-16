import os
import asyncio
import datetime
import time
import json
import requests
from io import BytesIO
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import FSInputFile
import supabase
from supabase import create_client
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройки из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
# Список админов (5 человек)
ADMIN_IDS = [
    1880252075,  # Вы (основной админ)
    1099113770,  # Админ 2 (Михаил Гапонов)
    843508960,   # Админ 3 (Миллер Екатерина)
    1121472787,  # Админ 4 (Снапков Дмитрий)
    888999000    # Админ 5 (замените на реальный ID)
]

# Реквизиты для перевода
SBER_ACCOUNT = "4276380208397583"
BANK_DETAILS = f"""
🏦 <b>РЕКВИЗИТЫ ДЛЯ ПЕРЕВОДА</b>

<b>Банк:</b> Сбербанк
<b>Номер счета:</b> 
<code>{SBER_ACCOUNT}</code>

💡 <b>Совет:</b> Скопируйте номер счета выше и вставьте в приложении банка
"""

# Путь к картинке мероприятия - УБЕДИТЕСЬ ЧТО ФАЙЛ СУЩЕСТВУЕТ!
EVENT_IMAGE_PATH = "event_image.jpg"

# Настройки файлов
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB максимальный размер файла
SUPPORTED_DOCUMENT_TYPES = ['.pdf', '.jpg', '.jpeg', '.png']

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Инициализация Supabase
try:
    supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Supabase подключен успешно")
except Exception as e:
    print(f"❌ Ошибка подключения к Supabase: {e}")
    supabase_client = None

# ФУНКЦИИ ДЛЯ РАБОТЫ С SUPABASE STORAGE
async def upload_receipt_to_supabase(bot: Bot, file_id: str, file_type: str, order_id: int, user_data: dict):
    """Загружает чек в Supabase Storage и возвращает URL"""
    try:
        print(f"📤 Начинаем загрузку чека в Supabase Storage для заказа #{order_id}...")
        
        # Получаем файл от Telegram
        file = await bot.get_file(file_id)
        file_path = file.file_path
        
        # Скачиваем файл
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        response = requests.get(file_url)
        
        if response.status_code == 200:
            # Определяем расширение и MIME тип
            if file_type == 'document':
                file_extension = ".pdf"
                mime_type = "application/pdf"
            else:  # photo
                file_extension = ".jpg" 
                mime_type = "image/jpeg"
            
            # Создаем уникальное имя файла
            file_name = f"receipt_order_{order_id}_{user_data['user_id']}{file_extension}"
            
            print(f"📁 Загружаем файл: {file_name}")
            print(f"📏 Размер файла: {len(response.content)} байт")
            
            try:
                # Загружаем в Supabase Storage
                result = supabase_client.storage.from_("receipts").upload(
                    file_name,
                    response.content,
                    {"content-type": mime_type}
                )
                
                if result:
                    print(f"✅ Файл успешно загружен в Supabase Storage: {file_name}")
                    
                    # Получаем публичный URL
                    public_url = supabase_client.storage.from_("receipts").get_public_url(file_name)
                    
                    # ОБНОВЛЯЕМ ЗАПИСЬ В SUPABASE С ССЫЛКОЙ НА ФАЙЛ
                    supabase_client.table("orders")\
                        .update({
                            "receipt_file_name": file_name,
                            "receipt_file_url": public_url
                        })\
                        .eq("id", order_id)\
                        .execute()
                    
                    return {
                        "file_name": file_name,
                        "public_url": public_url,
                        "file_size": len(response.content)
                    }
                else:
                    print("❌ Ошибка загрузки в Supabase Storage - результат пустой")
                    return None
                    
            except Exception as upload_error:
                print(f"❌ Ошибка при загрузке в Supabase Storage: {upload_error}")
                return None
                
        else:
            print(f"❌ Ошибка скачивания файла из Telegram: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"❌ Критическая ошибка загрузки в Supabase: {e}")
        return None

def create_receipts_bucket():
    """Создает bucket для чеков в Supabase Storage"""
    try:
        # Пытаемся создать bucket если не существует
        buckets = supabase_client.storage.list_buckets()
        bucket_names = [bucket.name for bucket in buckets]
        
        if "receipts" not in bucket_names:
            result = supabase_client.storage.create_bucket("receipts", {
                "public": True,  # Делаем файлы публичными для просмотра
                "file_size_limit": 20971520  # 20MB
            })
            print("✅ Bucket 'receipts' создан в Supabase Storage")
        else:
            print("✅ Bucket 'receipts' уже существует")
            
        return True
    except Exception as e:
        print(f"❌ Ошибка создания bucket: {e}")
        return False

async def get_supabase_file_info(order_id: int):
    """Получает информацию о файле в Supabase Storage по ID заказа"""
    try:
        # Получаем информацию о заказе из Supabase
        order = db.get_order_by_id(order_id)
        if not order:
            print(f"❌ Заказ #{order_id} не найден в Supabase")
            return None
            
        print(f"🔍 Поиск файлов для заказа #{order_id}...")
        
        # Ищем файлы в Storage по паттерну имени
        files = supabase_client.storage.from_("receipts").list()
        
        target_pattern = f"receipt_order_{order_id}_"
        found_files = []
        
        for file in files:
            print(f"📁 Проверка файла: {file['name']}")
            if target_pattern in file['name']:
                found_files.append(file)
        
        if found_files:
            # Берем первый найденный файл
            file = found_files[0]
            public_url = supabase_client.storage.from_("receipts").get_public_url(file['name'])
            
            print(f"✅ Найден файл: {file['name']}")
            print(f"🔗 Публичный URL: {public_url}")
            
            return {
                'file_name': file['name'],
                'public_url': public_url,
                'size': file.get('metadata', {}).get('size', 0),
                'mime_type': file.get('metadata', {}).get('mimetype', 'unknown')
            }
        else:
            print(f"❌ Файлы для заказа #{order_id} не найдены")
            return None
            
    except Exception as e:
        print(f"❌ Ошибка поиска файла в Supabase: {e}")
        return None

# Функции для логирования (только в файл, без SQLite)
def log_event(user_id, username, action, details=""):
    """АВТОМАТИЧЕСКОЕ ЛОГИРОВАНИЕ ВСЕХ ДЕЙСТВИЙ (только файл)"""
    moscow_time = datetime.datetime.now()
    timestamp = moscow_time.strftime("%d.%m.%Y %H:%M:%S MSK")
    log_message = f"[{timestamp}] 👤 User {user_id} ({username}) - {action}"
    if details:
        log_message += f" - {details}"
    print("🔹 " + log_message)
    
    # Сохраняем в файл
    with open("bot_log.txt", "a", encoding="utf-8") as f:
        f.write(log_message + "\n")

def log_tariff_selection(user_id, username, tariff_name, tariff_data):
    """АВТОМАТИЧЕСКОЕ ЛОГИРОВАНИЕ ВЫБОРА ТАРИФА"""
    price_info = f"{tariff_data['price']}₽" 
    if 'total' in tariff_data:
        price_info += f" (всего {tariff_data['total']}₽)"
    
    log_event(user_id, username, "🎫 ВЫБРАЛ(-а) ТАРИФ", 
              f"'{tariff_name}' - {price_info} - {tariff_data['min_people']} чел.")

def log_payment_start(user_id, username, tariff_name, participants, total_price):
    """АВТОМАТИЧЕСКОЕ ЛОГИРОВАНИЕ НАЧАЛА ОПЛАТЫ"""
    log_event(user_id, username, "💳 НАЧАЛ(-а) ОПЛАТУ",
              f"Тариф: {tariff_name}, Участники: {len(participants)}, Сумма: {total_price}₽")

def log_admin_action(user_id, username, action, details=""):
    """ЛОГИРОВАНИЕ ДЕЙСТВИЙ АДМИНА (только файл)"""
    moscow_time = datetime.datetime.now()
    timestamp = moscow_time.strftime("%d.%m.%Y %H:%M:%S MSK")
    log_message = f"[{timestamp}] 👨‍💼 ADMIN {user_id} ({username}) - {action}"
    if details:
        log_message += f" - {details}"
    print("🔸 " + log_message)
    
    # Сохраняем в файл
    with open("admin_log.txt", "a", encoding="utf-8") as f:
        f.write(log_message + "\n")

# Состояния для FSM
class OrderStates(StatesGroup):
    waiting_for_event = State()
    waiting_for_tariff = State()
    waiting_for_participants = State()
    waiting_for_payment = State()
    waiting_for_receipt = State()

# Тарифы
TARIFFS = {
    "Единоличный": {
        "price": 2000,
        "gender": "male",
        "description": "Вы - сильный мужчина одиночка или просто не супер социальный, или если же мужская энергия вас не держит на этой земле, то это ваш шанс показать кто здесь лев 🦁, но с уважением",
        "max_people": 1,
        "min_people": 1,
        "emoji": "👤",
        "includes": "Все включено в лофте"
    },
    "ЛД": {
        "price": 1750,
        "gender": "male", 
        "description": "Два друга, пришли показать всем, что крепкую мужскую дружбу ничего не заменит",
        "max_people": 2,
        "min_people": 2,
        "total": 3500,
        "emoji": "👥",
        "includes": "Все включено в лофте"
    },
    "Компания друзей": {
        "price": 1625,
        "gender": "male",
        "description": "Их было четверо…",
        "max_people": 4,
        "min_people": 4,
        "total": 6500,
        "emoji": "👥👥",
        "includes": "Все включено в лофте"
    },
    "Сильная и независимая": {
        "price": 1500,
        "gender": "female",
        "description": "Вы - селфмейд вумен",
        "max_people": 1,
        "min_people": 1,
        "emoji": "🧍‍♀️",
        "includes": "Все включено в лофте."
    },
    "ЛП": {
        "price": 1250,
        "gender": "female",
        "description": "Вас держит вместе желание завоевать весь свет своей красотой ну и естественно ещё и сэкономить",
        "max_people": 2,
        "min_people": 2,
        "total": 2500,
        "emoji": "👭",
        "includes": "Все включено в лофте."
    },
    "Серпентарий": {
        "price": 1125,
        "gender": "female", 
        "description": "Вы наконец-то выползли из своих норок и приехали раздать сваги и пообсуждать все на свете",
        "max_people": 4,
        "min_people": 4,
        "total": 4500,
        "emoji": "👭👭",
        "includes": "Все включено в лофте."
    },
    "Инь-янь": {
        "price": 1500,
        "gender": "couple",
        "description": "Вы пара 💞, пришли… показывать миру вашу любовь",
        "max_people": 2,
        "min_people": 2,
        "total": 3000,
        "emoji": "👩‍❤️‍👨",
        "includes": "Все включено в лофте."
    }
}

class Database:
    def __init__(self):
        self.supabase = supabase_client
        self.auto_create_table()
    
    def auto_create_table(self):
        """АВТОМАТИЧЕСКОЕ СОЗДАНИЕ ТАБЛИЦЫ ПРИ ПЕРВОМ ЗАПУСКЕ"""
        try:
            result = self.supabase.table("orders").select("id").limit(1).execute()
            print("✅ Таблица orders существует")
            return True
        except Exception as e:
            print("🔄 Таблица orders не найдена, создаем автоматически...")
            return self.create_orders_table()
    
    def create_orders_table(self):
        """АВТОМАТИЧЕСКОЕ СОЗДАНИЕ ТАБЛИЦЫ ЧЕРЕЗ SQL"""
        try:
            # Создаем простую таблицу через вставку тестовых данных
            test_data = {
                "user_id": 1,
                "username": "test",
                "tariff": "test",
                "participants": [{"full_name": "test", "telegram": "@test", "phone": "79990000000"}],
                "total_price": 1000,
                "status": "test"
            }
            
            result = self.supabase.table("orders").insert(test_data).execute()
            print("✅ Таблица orders создана автоматически")
            
            # Удаляем тестовые данные
            if result.data:
                self.supabase.table("orders").delete().eq("id", result.data[0]['id']).execute()
            
            return True
        except Exception as e:
            print(f"❌ Не удалось создать таблицу автоматически: {e}")
            print("💡 Создайте таблицу вручную в Supabase Dashboard")
            return False
    
    def add_order(self, user_id, username, tariff, participants, total_price):
        """СОХРАНЕНИЕ ЗАКАЗА В SUPABASE"""
        try:
            data = {
                "user_id": user_id,
                "username": username or "unknown",
                "tariff": tariff,
                "participants": participants,
                "total_price": total_price,
                "status": "pending",
                "receipt_verified": False
            }
            
            print(f"💾 СОХРАНЕНИЕ заказа в Supabase...")
            
            result = self.supabase.table("orders").insert(data).execute()
            
            if result.data:
                order_id = result.data[0]['id']
                print(f"✅ Заказ #{order_id} сохранен в Supabase")
                log_event(user_id, username, "💾 СОХРАНЕНИЕ В БД", f"ID: {order_id}")
                return result.data[0]
            else:
                print("❌ Ошибка: данные не вернулись от Supabase")
                return None
                
        except Exception as e:
            print(f"❌ Критическая ошибка сохранения заказа: {e}")
            log_event(user_id, username, "❌ ОШИБКА СОХРАНЕНИЯ", str(e))
            return None
    
    def update_order_status(self, order_id, status, receipt_verified=False):
        """ОБНОВЛЕНИЕ СТАТУСА ЗАКАЗА В SUPABASE"""
        try:
            update_data = {"status": status}
            if receipt_verified:
                update_data["receipt_verified"] = True
                
            result = self.supabase.table("orders")\
                .update(update_data)\
                .eq("id", order_id)\
                .execute()
            
            if result.data:
                print(f"✅ Статус заказа {order_id} обновлен на '{status}'")
                return result.data[0]
            return None
        except Exception as e:
            print(f"❌ Ошибка обновления статуса: {e}")
            return None
    
    def get_order_by_id(self, order_id):
        """ПОЛУЧЕНИЕ ЗАКАЗА ИЗ SUPABASE"""
        try:
            result = self.supabase.table("orders")\
                .select("*")\
                .eq("id", order_id)\
                .execute()
            
            if result.data:
                return result.data[0]
            return None
        except Exception as e:
            print(f"❌ Ошибка получения заказа: {e}")
            return None
    
    def get_all_orders(self, limit=100):
        """ПОЛУЧЕНИЕ ВСЕХ ЗАКАЗОВ ИЗ SUPABASE"""
        try:
            result = self.supabase.table("orders")\
                .select("*")\
                .order("created_at", desc=True)\
                .limit(limit)\
                .execute()
            
            return result.data or []
        except Exception as e:
            print(f"❌ Ошибка получения заказов: {e}")
            return []
    
    def get_pending_orders(self):
        """ПОЛУЧЕНИЕ ОЖИДАЮЩИХ ЗАКАЗОВ ИЗ SUPABASE"""
        try:
            result = self.supabase.table("orders")\
                .select("*")\
                .eq("status", "pending")\
                .order("created_at", desc=True)\
                .execute()
            
            return result.data or []
        except Exception as e:
            print(f"❌ Ошибка получения pending заказов: {e}")
            return []
    
    def get_paid_orders(self):
        """ПОЛУЧЕНИЕ ОПЛАЧЕННЫХ ЗАКАЗОВ ИЗ SUPABASE"""
        try:
            result = self.supabase.table("orders")\
                .select("*")\
                .eq("status", "paid")\
                .order("created_at", desc=True)\
                .execute()
            
            return result.data or []
        except Exception as e:
            print(f"❌ Ошибка получения paid заказов: {e}")
            return []
    
    def get_statistics(self):
        """ПОЛУЧЕНИЕ СТАТИСТИКИ ИЗ SUPABASE"""
        try:
            # Общее количество заказов
            result_total = self.supabase.table("orders").select("id", count="exact").execute()
            total_orders = result_total.count or 0
            
            # Оплаченные заказы
            result_paid = self.supabase.table("orders").select("id", count="exact").eq("status", "paid").execute()
            paid_orders = result_paid.count or 0
            
            # Ожидающие заказы
            result_pending = self.supabase.table("orders").select("id", count="exact").eq("status", "pending").execute()
            pending_orders = result_pending.count or 0
            
            # Общая выручка
            result_revenue = self.supabase.table("orders").select("total_price").eq("status", "paid").execute()
            total_revenue = sum(order['total_price'] for order in result_revenue.data) if result_revenue.data else 0
            
            # Уникальные пользователи
            result_users = self.supabase.table("orders").select("user_id").execute()
            unique_users = len(set(order['user_id'] for order in result_users.data)) if result_users.data else 0
            
            # Заказы за сегодня
            today = datetime.datetime.now().strftime('%Y-%m-%d')
            result_today = self.supabase.table("orders").select("id", count="exact").gte("created_at", f"{today}T00:00:00").lt("created_at", f"{today}T23:59:59").execute()
            today_orders = result_today.count or 0
            
            # Выручка за сегодня
            result_today_revenue = self.supabase.table("orders").select("total_price").eq("status", "paid").gte("created_at", f"{today}T00:00:00").lt("created_at", f"{today}T23:59:59").execute()
            today_revenue = sum(order['total_price'] for order in result_today_revenue.data) if result_today_revenue.data else 0
            
            return {
                'total_orders': total_orders,
                'paid_orders': paid_orders,
                'pending_orders': pending_orders,
                'total_revenue': total_revenue,
                'unique_users': unique_users,
                'today_orders': today_orders,
                'today_revenue': today_revenue
            }
            
        except Exception as e:
            print(f"❌ Ошибка получения статистики из Supabase: {e}")
            return {}

# СОЗДАЕМ ЭКЗЕМПЛЯР БАЗЫ ДАННЫХ
db = Database()

# Функция проверки прав админа
def is_admin(user_id):
    """Проверяет, является ли пользователь админом"""
    return user_id in ADMIN_IDS

# КОМАНДА /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await show_main_menu(message)

# КОМАНДА /reset
@dp.message(Command("reset"))
async def cmd_reset(message: types.Message, state: FSMContext):
    """Сброс состояния FSM"""
    await state.clear()
    await message.answer("✅ Состояние сброшено. Начните заново с /start")
    log_event(message.from_user.id, message.from_user.username, "🔄 СБРОС СОСТОЯНИЯ FSM")

# КОМАНДА ДЛЯ ПЕРЕСОЗДАНИЯ БАЗЫ ДАННЫХ
@dp.message(Command("recreate_db"))
async def cmd_recreate_db(message: types.Message):
    """Пересоздание базы данных (только для админов)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа")
        return
    
    log_admin_action(message.from_user.id, message.from_user.username, "🔄 ПЕРЕСОЗДАНИЕ БАЗЫ ДАННЫХ")
    
    try:
        # Удаляем все заказы из Supabase
        result = supabase_client.table("orders").delete().neq("id", 0).execute()
        await message.answer("✅ База данных успешно очищена!")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка пересоздания базы: {e}")

# КОМАНДА ДЛЯ ПРОВЕРКИ SUPABASE STORAGE
@dp.message(Command("check_storage"))
async def cmd_check_storage(message: types.Message):
    """Проверка состояния Supabase Storage"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа")
        return
    
    log_admin_action(message.from_user.id, message.from_user.username, "🔍 ПРОВЕРКА SUPABASE STORAGE")
    
    try:
        # Проверяем подключение к Supabase
        if not supabase_client:
            await message.answer("❌ Supabase клиент не инициализирован")
            return
        
        # Проверяем bucket receipts
        buckets = supabase_client.storage.list_buckets()
        bucket_names = [bucket.name for bucket in buckets]
        
        storage_info = "<b>🔍 ИНФОРМАЦИЯ О SUPABASE STORAGE</b>\n\n"
        
        if "receipts" in bucket_names:
            storage_info += "✅ Bucket 'receipts' существует\n"
            
            # Получаем список файлов
            files = supabase_client.storage.from_("receipts").list()
            storage_info += f"📁 Файлов в хранилище: {len(files)}\n\n"
            
            # Показываем последние 5 файлов
            if files:
                storage_info += "<b>Последние 5 файлов:</b>\n"
                for file in files[:5]:
                    file_size = file.get('metadata', {}).get('size', 0)
                    file_size_mb = f"{file_size / (1024*1024):.2f}MB" if file_size > 0 else "unknown"
                    storage_info += f"• {file['name']} ({file_size_mb})\n"
            else:
                storage_info += "📭 Файлов нет\n"
                
        else:
            storage_info += "❌ Bucket 'receipts' не найден\n"
        
        # Проверяем политики доступа
        storage_info += f"\n<b>Политики доступа:</b>\n"
        storage_info += "• Убедитесь что bucket 'receipts' публичный\n"
        storage_info += "• Проверьте политики в Supabase Dashboard\n"
        
        await message.answer(storage_info, parse_mode="HTML")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка проверки storage: {e}")

# КОМАНДА ДЛЯ ПЕРЕСОЗДАНИЯ BUCKET
@dp.message(Command("recreate_bucket"))
async def cmd_recreate_bucket(message: types.Message):
    """Пересоздание bucket в Supabase Storage"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа")
        return
    
    log_admin_action(message.from_user.id, message.from_user.username, "🔄 ПЕРЕСОЗДАНИЕ BUCKET")
    
    try:
        # Удаляем старый bucket если существует
        try:
            supabase_client.storage.delete_bucket("receipts")
            await message.answer("✅ Старый bucket удален")
        except:
            await message.answer("ℹ️ Старого bucket не существовало")
        
        # Создаем новый bucket
        result = supabase_client.storage.create_bucket("receipts", {
            "public": True,
            "file_size_limit": 20971520  # 20MB
        })
        
        if result:
            await message.answer("✅ Новый bucket 'receipts' создан!\n\n"
                               "📋 <b>Теперь настройте политики доступа:</b>\n"
                               "1. Зайдите в Supabase Dashboard → Storage\n"
                               "2. Выберите bucket 'receipts'\n"
                               "3. Перейдите в Policies\n"
                               "4. Добавьте политики:\n"
                               "   • SELECT: 'Allow public read access'\n"
                               "   • INSERT: 'Allow authenticated insert'", 
                               parse_mode="HTML")
        else:
            await message.answer("❌ Не удалось создать bucket")
            
    except Exception as e:
        await message.answer(f"❌ Ошибка пересоздания bucket: {e}")

# КОМАНДА ДЛЯ ОТЛАДКИ ЗАКАЗА
@dp.message(Command("debug_order"))
async def cmd_debug_order(message: types.Message):
    """Отладочная информация о заказе"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа")
        return
    
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer("❌ Использование: /debug_order <order_id>")
            return
        
        order_id = args[1]
        
        if not order_id.isdigit():
            await message.answer("❌ Order ID должен быть числом")
            return
        
        order = db.get_order_by_id(int(order_id))
        if not order:
            await message.answer(f"❌ Заказ #{order_id} не найден в Supabase")
            return
        
        debug_text = f"""
<b>🔧 ОТЛАДОЧНАЯ ИНФОРМАЦИЯ ДЛЯ ЗАКАЗА #{order_id}</b>

📊 <b>Supabase данные:</b>
• ID: {order['id']}
• User ID: {order['user_id']}
• Username: @{order['username']}
• Тариф: {order['tariff']}
• Сумма: {order['total_price']}₽
• Статус: {order['status']}
• Файл: {order.get('receipt_file_name', '❌ НЕТ')}
• URL: {order.get('receipt_file_url', '❌ НЕТ')}

🔍 <b>Поиск в Supabase Storage:</b>
"""
        
        # Проверяем наличие файла в Supabase
        supabase_file_info = await get_supabase_file_info(int(order_id))
        if supabase_file_info:
            debug_text += f"✅ Файл найден: {supabase_file_info['file_name']}\n"
            debug_text += f"🔗 URL: {supabase_file_info['public_url']}\n"
            debug_text += f"📏 Размер: {supabase_file_info['size']} байт\n"
        else:
            debug_text += "❌ Файл не найден в Supabase Storage\n"
        
        await message.answer(debug_text, parse_mode="HTML", disable_web_page_preview=True)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка отладки: {e}")

# ГЛАВНОЕ МЕНЮ
async def show_main_menu(message: types.Message):
    """Показывает главное меню с кнопками"""
    log_event(message.from_user.id, message.from_user.username, "🚀 ЗАПУСТИЛ(-а) БОТА")
    
    keyboard = [
        [types.KeyboardButton(text="🚀 Старт")],
        [types.KeyboardButton(text="📅 Информация о мероприятии")],
        [types.KeyboardButton(text="🎫 Посмотреть тарифы"), types.KeyboardButton(text="💬 Помощь")]
    ]
    
    # Если пользователь админ - добавляем кнопку админ-панели
    if is_admin(message.from_user.id):
        keyboard.append([types.KeyboardButton(text="👨‍💼 Консоль Админа")])
    
    markup = types.ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    
    welcome_text = """
<b>🎫 ОФИЦИАЛЬНЫЙ БОТ ДЛЯ ПОКУПКИ БИЛЕТОВ ОТ GEDAN</b>

Привет! Я помогу тебе приобрести билеты на наши мероприятия.
Выбери нужный раздел ниже 👇
    """
    
    await message.answer(welcome_text, reply_markup=markup, parse_mode="HTML")

# КНОПКА СТАРТ
@dp.message(F.text == "🚀 Старт")
async def button_start(message: types.Message, state: FSMContext):
    """Обработка кнопки Старт"""
    log_event(message.from_user.id, message.from_user.username, "🔄 НАЖАЛ(-а) 'СТАРТ'")
    
    await state.clear()
    
    welcome_text = """
<b>🎫 ДОБРО ПОЖАЛОВАТЬ В ОФИЦИАЛЬНЫЙ БОТ GEDAN!</b>

Я - твой помощник в мире незабываемых мероприятий! 🎭

✨ <b>Что я умею:</b>
• Продавать билеты на лучшие вечеринки GEDAN
• Помогать выбрать подходящий тариф
• Обеспечивать быструю и безопасную оплату
• Предоставлять всю информацию о мероприятиях

🎯 <b>Ближайшее событие:</b>
<b>HALLOWEEN GEDAN PARTY</b> 🎃👻
02.11.2025 | 19:00 | Слободской переулок 6

Готовы окунуться в атмосферу хэллоуинской магии? Выбирай раздел ниже! 👇
    """
    
    keyboard = [
        [types.KeyboardButton(text="📅 Информация о мероприятии")],
        [types.KeyboardButton(text="🎫 Посмотреть тарифы"), types.KeyboardButton(text="💬 Помощь")]
    ]
    
    # Если пользователь админ - добавляем кнопку админ-панели
    if is_admin(message.from_user.id):
        keyboard.append([types.KeyboardButton(text="👨‍💼 Консоль Админа")])
    
    markup = types.ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    
    await message.answer(welcome_text, reply_markup=markup, parse_mode="HTML")

# ИСПРАВЛЕННАЯ ИНФОРМАЦИЯ О МЕРОПРИЯТИИ - ФОТО И ОПИСАНИЕ В ОДНОМ СООБЩЕНИИ
@dp.message(F.text == "📅 Информация о мероприятии")
async def button_event_info(message: types.Message):
    log_event(message.from_user.id, message.from_user.username, "📅 ЗАПРОСИЛ(-а) ИНФО О МЕРОПРИЯТИИ")
    
    event_text = """
<b>HALLOWEEN GEDAN PARTY 🎃👻</b>

🗓 <b>Когда:</b> 02.11.2025
🌙 <b>Время:</b> 19:00  
📍 <b>Место:</b> Слободской переулок 6, стр 3

✨ <b>Что ждёт внутри:</b>
• SPOOKY DJ SET - пугающе-качающие треки
• AUTHOR COCTAILS - страшно завораживающие коктейли
• HORRIFYING COSTUMES - битва костюмов с призами 🏆
• DEADLY GAMES - специально подготовленные тематические игры
• Swag and spooky vibes ☠️🍀

🎯 <b>Битва костюмов:</b>
• Лучший костюм получает приз от организации
• Креативность и хоррор-эстетика приветствуются
• Жюри из организаторов и гостей вечеринки

⚡ <i>Дамы и господа! Представляем вашему вниманию первую тематическую вечеринку!</i>

Готовы стать частью самого живого страха? Выбирай тариф ниже!
    """
    
    keyboard = [
        [types.InlineKeyboardButton(text="🎫 ВЫБРАТЬ ТАРИФ", callback_data="show_tariffs")],
        [types.InlineKeyboardButton(text="⬅️ НАЗАД", callback_data="back_to_main")]
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    # Пытаемся отправить фото мероприятия С ОПИСАНИЕМ В ОДНОМ СООБЩЕНИИ
    try:
        if os.path.exists(EVENT_IMAGE_PATH):
            photo = FSInputFile(EVENT_IMAGE_PATH)
            await message.answer_photo(
                photo,
                caption=event_text,
                reply_markup=markup,
                parse_mode="HTML"
            )
        else:
            print(f"⚠️ Файл {EVENT_IMAGE_PATH} не найден, отправляем только текст")
            await message.answer(event_text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        print(f"❌ Ошибка отправки фото: {e}")
        # Если фото не отправилось, отправляем только текст
        await message.answer(event_text, reply_markup=markup, parse_mode="HTML")

# ПОКАЗ ТАРИФОВ
@dp.message(F.text == "🎫 Посмотреть тарифы")
async def cmd_tariffs(message: types.Message, state: FSMContext):
    log_event(message.from_user.id, message.from_user.username, "🎫 ЗАПРОСИЛ(-а) ТАРИФЫ")
    await show_tariffs_menu(message, state)

async def show_tariffs_menu(message: types.Message, state: FSMContext):
    """Показывает меню тарифов"""
    male_keyboard = [
        [types.InlineKeyboardButton(text="👤 Единоличный", callback_data="tariff_Единоличный")],
        [types.InlineKeyboardButton(text="👥 ЛД", callback_data="tariff_ЛД")],
        [types.InlineKeyboardButton(text="👥👥 Компания друзей", callback_data="tariff_Компания друзей")]
    ]
    
    female_keyboard = [
        [types.InlineKeyboardButton(text="🧍‍♀️ Сильная и независимая", callback_data="tariff_Сильная и независимая")],
        [types.InlineKeyboardButton(text="👭 ЛП", callback_data="tariff_ЛП")],
        [types.InlineKeyboardButton(text="👭👭 Серпентарий", callback_data="tariff_Серпентарий")]
    ]
    
    mixed_keyboard = [
        [types.InlineKeyboardButton(text="👩‍❤️‍👨 Инь-янь", callback_data="tariff_Инь-янь")]
    ]
    
    back_button = [[types.InlineKeyboardButton(text="⬅️ НАЗАД", callback_data="back_to_main")]]
    
    tariffs_intro = """
<b>ВЫБЕРИ СВОЙ ПУТЬ НА HALLOWEEN GEDAN PARTY 💰</b>

Каждый тариф — это не просто билет, это твой уникальный опыт и комьюнити!
    """
    
    await message.answer(tariffs_intro, parse_mode="HTML")
    
    await message.answer("<b>🦁 ДЛЯ ПАРНЕЙ</b>", parse_mode="HTML")
    markup = types.InlineKeyboardMarkup(inline_keyboard=male_keyboard)
    await message.answer("Выбери свой стиль:", reply_markup=markup)
    
    await message.answer("<b>🌸 ДЛЯ ДЕВОЧЕК</b>", parse_mode="HTML")
    markup = types.InlineKeyboardMarkup(inline_keyboard=female_keyboard)
    await message.answer("Твой вариант:", reply_markup=markup)
    
    await message.answer("<b>💞 ДЛЯ ПАР</b>", parse_mode="HTML")
    markup = types.InlineKeyboardMarkup(inline_keyboard=mixed_keyboard)
    await message.answer("Для влюбленных:", reply_markup=markup)
    
    markup_back = types.InlineKeyboardMarkup(inline_keyboard=back_button)
    await message.answer("Вернуться в главное меню:", reply_markup=markup_back)
    
    await state.set_state(OrderStates.waiting_for_tariff)

# ОБРАБОТКА ВЫБОРА ТАРИФА
@dp.callback_query(F.data.startswith("tariff_"))
async def process_tariff_selection(callback: types.CallbackQuery, state: FSMContext):
    try:
        tariff_name = callback.data.replace("tariff_", "")
        log_tariff_selection(callback.from_user.id, callback.from_user.username, tariff_name, TARIFFS[tariff_name])
        
        if tariff_name not in TARIFFS:
            await callback.answer(f"❌ Тариф '{tariff_name}' не найден", show_alert=True)
            return
        
        tariff = TARIFFS[tariff_name]
        await state.update_data(selected_tariff=tariff_name)
        
        description = f"{tariff['emoji']} <b>«{tariff_name}»</b>\n"
        
        if 'total' in tariff:
            description += f"💵 <b>{tariff['price']}₽ с человека</b>\n"
            description += f"💳 <b>Всего: {tariff['total']}₽</b>\n"
        else:
            description += f"💵 <b>Стоимость: {tariff['price']}₽</b>\n"
        
        description += f"\n📖 {tariff['description']}\n"
        description += f"\n✅ <b>Включено:</b>\n"
        description += f"• {tariff['includes']}\n"
        description += f"• Полный доступ на Halloween Gedan Party\n"
        description += f"• Участие в битве костюмов\n"
        description += f"• SPOOKY DJ SET и тематические игры\n"
        description += f"• Авторские коктейли и закуски\n"

        if tariff['min_people'] == 1:
            message_text = f"{description}\n\n📝 <b>Теперь введите свои данные в формате:</b>\n<code>ФИО, телеграмм, номер телефона</code>\n\n<b>Пример:</b>\n<code>Иванов Иван Иванович, @ivanov, 79991234567</code>"
        else:
            message_text = f"{description}\n\n📝 <b>Теперь введите данные всех {tariff['min_people']} участников в формате:</b>\nКаждый участник с новой строки:\n<code>ФИО, телеграмм, номер телефона</code>\n\n<b>Пример для {tariff['min_people']} человек:</b>\n<code>Иванов Иван Иванович, @ivanov, 79991234567</code>\n<code>Петрова Анна Сергеевна, @petrova, 79997654321</code>"
        
        keyboard = [[types.InlineKeyboardButton(text="⬅️ ВЫБРАТЬ ДРУГОЙ ТАРИФ", callback_data="back_to_tariffs")]]
        markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        await callback.message.edit_text(message_text, reply_markup=markup, parse_mode="HTML")
        await state.set_state(OrderStates.waiting_for_participants)
        await callback.answer(f"✅ Выбран: {tariff_name}")
        
    except Exception as e:
        error_msg = f"Ошибка при выборе тарифа: {e}"
        print(f"🔴 {error_msg}")
        log_event(callback.from_user.id, callback.from_user.username, "❌ ОШИБКА ВЫБОРА ТАРИФА", str(e))
        await callback.answer("❌ Ошибка, попробуй снова", show_alert=True)

# ОБРАБОТКА ВВОДА ДАННЫХ УЧАСТНИКОВ - ДОБАВЛЯЕМ СОХРАНЕНИЕ tariff_name
@dp.message(OrderStates.waiting_for_participants)
async def process_participants_input(message: types.Message, state: FSMContext):
    try:
        user_data = await state.get_data()
        tariff_name = user_data['selected_tariff']
        tariff = TARIFFS[tariff_name]
        
        log_event(message.from_user.id, message.from_user.username, "📝 ВВЕЛ(-а) ДАННЫЕ УЧАСТНИКОВ", f"Тариф: {tariff_name}")
        
        # Парсим введенные данные
        lines = [line.strip() for line in message.text.strip().split('\n') if line.strip()]
        
        if len(lines) != tariff['min_people']:
            error_msg = f"Неправильное количество участников: {len(lines)} вместо {tariff['min_people']}"
            log_event(message.from_user.id, message.from_user.username, "❌ ОШИБКА ВВОДА", error_msg)
            await message.answer(
                f"❌ Для тарифа '{tariff_name}' нужно указать ровно {tariff['min_people']} участника.\n"
                f"Ты указал(-а) {len(lines)}. Попробуй еще раз (каждый участник с новой строки):\n\n"
                f"<b>Формат для каждого участника:</b>\nФИО, телеграмм, номер телефона\n\n"
                f"<b>Пример для {tariff['min_people']} человек:</b>\n"
                f"Иванов Иван Иванович, @ivanov, 79991234567\n"
                f"Петрова Анна Сергеевна, @petrova, 79997654321"
            )
            return
        
        participants = []
        errors = []
        
        for i, line in enumerate(lines, 1):
            parts = [part.strip() for part in line.split(',')]
            if len(parts) != 3:
                errors.append(f"❌ Участник {i}: неправильный формат. Нужно: ФИО, телеграмм, телефон")
                continue
            
            full_name, telegram, phone = parts
            
            # Валидация данных
            if len(full_name) < 2:
                errors.append(f"❌ Участник {i}: ФИО слишком короткое")
                continue
                
            if not telegram.startswith('@'):
                errors.append(f"❌ Участник {i}: телеграмм должен начинаться с @")
                continue
                
            if not phone.replace('+', '').isdigit() or len(phone) < 10:
                errors.append(f"❌ Участник {i}: неверный формат телефона")
                continue
            
            participants.append({
                "full_name": full_name,
                "telegram": telegram,
                "phone": phone
            })
        
        # Если есть ошибки - показываем их
        if errors:
            error_text = "<b>❌ Ошибки в данных:</b>\n" + "\n".join(errors)
            error_text += f"\n\n<b>Попробуйте еще раз. Формат для каждого участника:</b>\nФИО, телеграмм, телефон\n\n<b>Пример:</b>\nИванов Иван, @ivanov, 79991234567"
            await message.answer(error_text, parse_mode="HTML")
            return
        
        # СОХРАНЯЕМ ВСЕ ДАННЫЕ В СОСТОЯНИЕ
        total_price = tariff.get('total', tariff['price'])
        await state.update_data(
            participants=participants,
            tariff_name=tariff_name,  # ДОБАВЛЯЕМ ЭТО!
            total_price=total_price   # ДОБАВЛЯЕМ ЭТО!
        )
        
        keyboard = [
            [types.InlineKeyboardButton(text="💳 ПЕРЕЙТИ К ОПЛАТЕ", callback_data="proceed_to_payment")],
            [types.InlineKeyboardButton(text="⬅️ ВЫБРАТЬ ДРУГОЙ ТАРИФ", callback_data="back_to_tariffs")]
        ]
        markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        participants_text = ""
        for i, participant in enumerate(participants, 1):
            participants_text += f"👤 <b>Участник {i}:</b>\n"
            participants_text += f"   • ФИО: {participant['full_name']}\n"
            participants_text += f"   • Telegram: {participant['telegram']}\n"
            participants_text += f"   • Телефон: {participant['phone']}\n\n"
        
        summary_text = f"""
<b>✅ ВАШ ЗАКАЗ ПОДТВЕРЖДЁН! 🎫</b>

{participants_text}
📋 <b>Тариф:</b> {tariff['emoji']} {tariff_name}
💎 <b>Сумма:</b> {total_price}₽

🎭 <b>Система браслетов:</b>
🟢 Зеленый - открыт к общению
🔴 Красный - в своем пространстве

<i>Цвет можно изменить в любой момент у организатора</i>

Нажмите ниже для завершения бронирования ⬇️
        """
        
        await message.answer(summary_text, reply_markup=markup, parse_mode="HTML")
        await state.set_state(OrderStates.waiting_for_payment)
        
    except Exception as e:
        error_msg = f"Ошибка при вводе данных участников: {e}"
        print(f"🔴 {error_msg}")
        log_event(message.from_user.id, message.from_user.username, "❌ ОШИБКА ВВОДА ДАННЫХ", str(e))
        await message.answer("❌ Ошибка, начните снова с /start")

# ОБРАБОТКА ОПЛАТЫ - УПРОЩАЕМ ЛОГИКУ
@dp.callback_query(F.data == "proceed_to_payment")
async def process_payment(callback: types.CallbackQuery, state: FSMContext):
    try:
        # ПОЛУЧАЕМ ВСЕ ДАННЫЕ ИЗ СОСТОЯНИЯ
        user_data = await state.get_data()
        
        # ПРОВЕРЯЕМ ЧТО ВСЕ НЕОБХОДИМЫЕ ДАННЫЕ ЕСТЬ
        required_fields = ['selected_tariff', 'participants', 'total_price']
        missing_fields = [field for field in required_fields if field not in user_data]
        
        if missing_fields:
            error_msg = f"Отсутствуют данные: {missing_fields}"
            print(f"🔴 {error_msg}")
            log_event(callback.from_user.id, callback.from_user.username, "❌ ОШИБКА ДАННЫХ", error_msg)
            await callback.answer("❌ Ошибка данных, начните заново", show_alert=True)
            await state.clear()
            return
        
        tariff_name = user_data['selected_tariff']
        participants = user_data['participants']
        total_price = user_data['total_price']
        tariff = TARIFFS[tariff_name]
        
        log_payment_start(callback.from_user.id, callback.from_user.username, tariff_name, participants, total_price)
        
        # УБИРАЕМ ЛИШНЕЕ ОБНОВЛЕНИЕ СОСТОЯНИЯ - ДАННЫЕ УЖЕ ЕСТЬ
        payment_text = f"""
<b>ФИНАЛЬНЫЙ ШАГ - ОПЛАТА 💳</b>

🎯 <b>Тариф:</b> {tariff_name}
💎 <b>Сумма к оплате:</b> {total_price}₽

📋 <b>Инструкция по оплате:</b>
1. Переведите {total_price}₽ на указанный ниже счет
2. Сохраните чек об оплате в виде PDF
3. Вернитесь в этот чат и отправьте чек

⚠️ <b>Важно:</b>

• Бронирование подтверждается только после проверки чека
• Чек должен содержать сумму и дату перевода
• Проверка занимает до 24 часов
• <b>Поддерживаемые форматы:</b> PDF(макс. 20MB)
• ДРУГИЕ ФОРМАТЫ НЕ ПРИНИМАЮТСЯ!
        """
        
        keyboard = [
            [types.InlineKeyboardButton(text="✅ Я ОПЛАТИЛ И ПРИШЛЮ ЧЕК", callback_data="send_receipt")],
            [types.InlineKeyboardButton(text="⬅️ НАЗАД К ТАРИФАМ", callback_data="back_to_tariffs")]
        ]
        markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        await callback.message.edit_text(payment_text, reply_markup=markup, parse_mode="HTML")
        
        # Отправляем реквизиты
        await callback.message.answer(BANK_DETAILS, parse_mode="HTML")
        
        # Отправляем номер счета для копирования
        account_only = f"<code>{SBER_ACCOUNT}</code>"
        await callback.message.answer(account_only, parse_mode="HTML")
        
        await state.set_state(OrderStates.waiting_for_receipt)
        await callback.answer()
        
    except Exception as e:
        error_msg = f"Ошибка при переходе к оплате: {e}"
        print(f"🔴 {error_msg}")
        log_event(callback.from_user.id, callback.from_user.username, "❌ ОШИБКА ПРИ ОПЛАТЕ", str(e))
        await callback.answer("❌ Ошибка при создании заказа", show_alert=True)

# НАВИГАЦИЯ
@dp.callback_query(F.data == "back_to_tariffs")
async def back_to_tariffs(callback: types.CallbackQuery, state: FSMContext):
    log_event(callback.from_user.id, callback.from_user.username, "⬅️ ВЕРНУЛСЯ К ВЫБОРУ ТАРИФОВ")
    await show_tariffs_menu(callback.message, state)
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    log_event(callback.from_user.id, callback.from_user.username, "⬅️ ВЕРНУЛСЯ В ГЛАВНОЕ МЕНЮ")
    await state.clear()
    await show_main_menu(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "show_tariffs")
async def show_tariffs(callback: types.CallbackQuery, state: FSMContext):
    log_event(callback.from_user.id, callback.from_user.username, "🎫 НАЖАЛ 'ВЫБРАТЬ ТАРИФ'")
    await show_tariffs_menu(callback.message, state)
    await callback.answer()

# ОБРАБОТКА ОТПРАВКИ ЧЕКА
@dp.callback_query(F.data == "send_receipt")
async def send_receipt_request(callback: types.CallbackQuery, state: FSMContext):
    log_event(callback.from_user.id, callback.from_user.username, "📎 ЗАПРОСИЛ ОТПРАВКУ ЧЕКА")
    
    await callback.message.answer(
        "📎 <b>Пришлите чек об оплате</b>\n\n"
        "Пожалуйста, отправьте PDF-файл с чеком перевода.\n"
        "Чек должен содержать:\n"
        "• Сумму перевода\n" 
        "• Дату и время\n"
        "• Номер счета получателя\n\n"
        "<b>Ограничения:</b>\n"
        "• Максимальный размер: 20MB\n"
        "• Файл должен быть читаемым\n\n"
        "<b>После отправки чека ваш заказ будет сохранен в систему.</b>",
        parse_mode="HTML"
    )
    await callback.answer()

# ОБНОВЛЕННАЯ ОБРАБОТКА ЧЕКОВ (только Supabase)
@dp.message(OrderStates.waiting_for_receipt, F.document | F.photo)
async def process_receipt(message: types.Message, state: FSMContext):
    try:
        user_data = await state.get_data()
        tariff_name = user_data['tariff_name']
        participants = user_data['participants']
        total_price = user_data['total_price']
        
        log_event(message.from_user.id, message.from_user.username, "📎 ОТПРАВИЛ ЧЕК", f"Тариф: {tariff_name}")
        
        # ПРОВЕРКА РАЗМЕРА ФАЙЛА ДЛЯ ДОКУМЕНТОВ
        if message.document:
            if message.document.file_size > MAX_FILE_SIZE:
                await message.answer(
                    f"❌ Файл слишком большой! Максимальный размер: {MAX_FILE_SIZE // (1024*1024)}MB\n"
                    f"Ваш файл: {message.document.file_size // (1024*1024)}MB\n"
                    "Пожалуйста, отправьте файл меньшего размера или сделайте скриншот."
                )
                return
            
            # ПРОВЕРКА ТИПА ФАЙЛА
            file_name = message.document.file_name or "document"
            file_ext = os.path.splitext(file_name.lower())[1]
            
            if file_ext not in SUPPORTED_DOCUMENT_TYPES:
                await message.answer(
                    f"❌ Неподдерживаемый формат файла: {file_ext}\n"
                    f"Поддерживаемые форматы: PDF\n"
                    "Пожалуйста, отправьте чек в одном из этих форматов."
                )
                return
        
        print(f"💾 Начинаем сохранение заказа в базу после получения чека...")
        
        # Сохраняем заказ в Supabase
        order = db.add_order(
            user_id=message.from_user.id,
            username=message.from_user.username,
            tariff=tariff_name,
            participants=participants,
            total_price=total_price
        )
        
        if not order:
            await message.answer("❌ Ошибка при сохранении заказа. Попробуйте еще раз или свяжитесь с поддержкой.")
            await state.clear()
            return
        
        supabase_order_id = order['id']
        print(f"✅ Заказ #{supabase_order_id} сохранен в Supabase")
        
        # СОХРАНЯЕМ ИНФОРМАЦИЮ О ФАЙЛЕ
        file_info = None
        receipt_data = None
        
        if message.document:
            file_info = {
                'file_id': message.document.file_id,
                'file_type': 'document',
                'filename': message.document.file_name or f"receipt_{supabase_order_id}.pdf",
                'file_unique_id': message.document.file_unique_id,
                'file_size': message.document.file_size
            }
            print(f"📎 Сохраняем документ-чек для заказа #{supabase_order_id}: {file_info['filename']} ({file_info['file_size']} bytes)")
            
        elif message.photo:
            # Для фото берем самое качественное (последнее в массиве)
            file_info = {
                'file_id': message.photo[-1].file_id,
                'file_type': 'photo', 
                'filename': f"receipt_photo_{supabase_order_id}.jpg",
                'file_unique_id': message.photo[-1].file_unique_id,
                'file_size': "unknown"
            }
            print(f"📎 Сохраняем фото-чек для заказа #{supabase_order_id}")
        
        # ЗАГРУЖАЕМ ФАЙЛ В SUPABASE STORAGE
        if file_info:
            user_info = {
                'user_id': message.from_user.id,
                'username': message.from_user.username or 'unknown'
            }
            
            receipt_data = await upload_receipt_to_supabase(
                bot, 
                file_info['file_id'], 
                file_info['file_type'], 
                supabase_order_id,
                user_info
            )
            
            if receipt_data:
                print(f"✅ Чек загружен в Supabase Storage: {receipt_data['file_name']}")
                log_event(message.from_user.id, message.from_user.username, 
                         "☁️ ЧЕК ЗАГРУЖЕН В SUPABASE", 
                         f"Файл: {receipt_data['file_name']}, URL: {receipt_data['public_url']}")
            else:
                print(f"❌ Не удалось загрузить чек в Supabase Storage для заказа #{supabase_order_id}")
        
        print(f"✅ Заказ #{supabase_order_id} успешно сохранен в базу после отправки чека")
        
        success_text = f"""
<b>✅ ЧЕК ПОЛУЧЕН И ЗАКАЗ СОХРАНЕН!</b>

📦 <b>Заказ:</b> #{supabase_order_id}
🎯 <b>Тариф:</b> {tariff_name}
💎 <b>Сумма:</b> {total_price}₽

✅ <b>Статус:</b> Заказ сохранен в систему
⏳ <b>Ожидайте:</b> Подтверждение в течение 24 часов

{'☁️ <b>Чек загружен в облачное хранилище</b>' if receipt_data else '📎 Файл чека сохранен'}

💬 <b>По вопросам:</b> @m5frls
        """
        
        await message.answer(success_text, parse_mode="HTML")
        await state.clear()
        
    except Exception as e:
        error_msg = f"Ошибка при обработке чека: {e}"
        print(f"🔴 {error_msg}")
        log_event(message.from_user.id, message.from_user.username, "❌ ОШИБКА ОБРАБОТКИ ЧЕКА", str(e))
        await message.answer("❌ Ошибка при обработке чека. Попробуйте еще раз или свяжитесь с поддержкой.")

# Консоль Админа
@dp.message(F.text == "👨‍💼 Консоль Админа")
async def button_admin_panel(message: types.Message):
    """Обработка кнопки Консоль Админа"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к консоли админа")
        return
    
    log_admin_action(message.from_user.id, message.from_user.username, "👨‍💼 ОТКРЫЛ(-а)КОНСОЛЬ АДМИНА")
    
    admin_text = """
<b>👨‍💼 КОНСОЛЬ АДМИНА</b>

📊 <b>Статистика:</b>
/stats - статистика из Supabase
/orders - все заказы

🔧 <b>Supabase Storage:</b>
/check_storage - проверить хранилище
/recreate_bucket - пересоздать bucket
/recreate_db - пересоздать базу данных
/debug_order [id] - отладочная информация

👤 <b>Управление заказами:</b>
/pending - ожидающие оплаты (с реальными чеками)
/paid - оплаченные
/receipt [id] - получить чек для заказа

🔄 <b>Управление статусами:</b>
/approve [id] - подтвердить оплату
/cancel [id] - отменить заказ

🛠️ <b>Утилиты:</b>
/reset - сброс состояния FSM

💡 <b>Быстрые команды:</b>
Просто введите команду выше
    """
    
    await message.answer(admin_text, parse_mode="HTML")

# КОМАНДА ДЛЯ ТЕСТИРОВАНИЯ PDF
@dp.message(Command("test_pdf"))
async def cmd_test_pdf(message: types.Message):
    """Тестовая команда для проверки работы с PDF"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа")
        return
    
    test_text = """
<b>🧪 ТЕСТ РАБОТЫ С PDF</b>

Для тестирования отправки PDF:
1. Перейдите в состояние ожидания чека командой /start
2. Выберите тариф и введите данные
3. На этапе оплаты нажмите "Я ОПЛАТИЛ И ПРИСЛАЛ ЧЕК"
4. Отправьте PDF файл с чеком

<b>Техническая информация:</b>
• Максимальный размер файла: 20MB
• Поддерживаемые форматы: PDF
• Файлы хранятся в Supabase Storage
• Доступ через команду /pending

<b>Если PDF не работает:</b>
1. Проверьте размер файла
2. Убедитесь что это действительно PDF
3. Попробуйте отправить как фото
4. Используйте /reset для сброса состояния
    """
    
    await message.answer(test_text, parse_mode="HTML")

# НОВЫЕ КОМАНДЫ ДЛЯ УПРАВЛЕНИЯ СТАТУСАМИ
@dp.message(Command("approve"))
async def cmd_approve(message: types.Message):
    """Подтверждение оплаты заказа"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа")
        return
    
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer("❌ Использование: /approve <order_id>\nПример: /approve 15")
            return
        
        order_id = args[1]
        
        if not order_id.isdigit():
            await message.answer("❌ Order ID должен быть числом")
            return
        
        log_admin_action(message.from_user.id, message.from_user.username, "✅ ПОДТВЕРДИЛ(-а) ОПЛАТУ", f"Order ID: {order_id}")
        
        # Обновляем статус в Supabase
        success = db.update_order_status(int(order_id), "paid", True)
        
        if success:
            await message.answer(f"✅ Заказ #{order_id} подтвержден и перемещен в оплаченные!")
            
            # Получаем информацию о заказе для уведомления пользователя
            order = db.get_order_by_id(int(order_id))
            if order and order['user_id']:
                try:
                    await bot.send_message(
                        order['user_id'],
                        f"🎉 <b>ВАШ ЗАКАЗ ПОДТВЕРЖДЕН!</b>\n\n"
                        f"Заказ #{order_id} успешно подтвержден администратором.\n"
                        f"Ждем вас на мероприятии!\n\n"
                        f"📅 <b>HALLOWEEN GEDAN PARTY</b>\n"
                        f"🗓 02.11.2025 | 19:00\n"
                        f"📍 Слободской переулок 6",
                        parse_mode="HTML"
                    )
                except Exception as e:
                    print(f"❌ Не удалось уведомить пользователя: {e}")
        else:
            await message.answer(f"❌ Не удалось подтвердить заказ #{order_id}")
            
    except Exception as e:
        await message.answer(f"❌ Ошибка подтверждения заказа: {e}")

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message):
    """Отмена заказа"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа")
        return
    
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer("❌ Использование: /cancel <order_id>\nПример: /cancel 15")
            return
        
        order_id = args[1]
        
        if not order_id.isdigit():
            await message.answer("❌ Order ID должен быть числом")
            return
        
        log_admin_action(message.from_user.id, message.from_user.username, "❌ ОТМЕНИЛ ЗАКАЗ", f"Order ID: {order_id}")
        
        # Обновляем статус в Supabase
        success = db.update_order_status(int(order_id), "canceled")
        
        if success:
            await message.answer(f"❌ Заказ #{order_id} отменен!")
        else:
            await message.answer(f"❌ Не удалось отменить заказ #{order_id}")
            
    except Exception as e:
        await message.answer(f"❌ Ошибка отмены заказа: {e}")

# КОНСОЛЬ АДМИНА - ОБНОВЛЕННЫЕ КОМАНДЫ
@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    """Статистика из Supabase"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа")
        return
    
    log_admin_action(message.from_user.id, message.from_user.username, "📊 ЗАПРОСИЛ СТАТИСТИКУ")
    
    try:
        stats = db.get_statistics()
        
        stats_text = f"""
<b>📊 СТАТИСТИКА ИЗ SUPABASE</b>

🎫 <b>ОБЩАЯ СТАТИСТИКА:</b>
• Всего заказов: {stats['total_orders']}
• ✅ Оплаченных: {stats['paid_orders']}
• ⏳ Ожидают оплаты: {stats['pending_orders']}
• 👥 Уникальных пользователей: {stats['unique_users']}
• 💰 Общая выручка: {stats['total_revenue']}₽

📅 <b>ЗА СЕГОДНЯ:</b>
• Новых заказов: {stats['today_orders']}
• 💰 Выручка сегодня: {stats['today_revenue']}₽

💾 <b>База данных:</b> Supabase
🕐 <b>Последнее обновление:</b> {datetime.datetime.now().strftime('%H:%M:%S')}
        """
        
        await message.answer(stats_text, parse_mode="HTML")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка получения статистики: {e}")

@dp.message(Command("orders"))
async def cmd_orders(message: types.Message):
    """Все заказы из Supabase"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа")
        return
    
    log_admin_action(message.from_user.id, message.from_user.username, "📋 ЗАПРОСИЛ ВСЕ ЗАКАЗЫ")
    
    try:
        orders = db.get_all_orders(limit=15)
        
        if not orders:
            await message.answer("📭 В базе нет заказов")
            return
        
        response = "<b>📋 ПОСЛЕДНИЕ 15 ЗАКАЗОВ:</b>\n\n"
        
        for order in orders:
            status_emoji = "✅" if order['status'] == 'paid' else "⏳"
            if order['status'] == 'canceled':
                status_emoji = "❌"
                
            response += f"{status_emoji} <b>Заказ #{order['id']}</b>\n"
            response += f"👤 @{order['username']} (ID: {order['user_id']})\n"
            response += f"🎫 Тариф: {order['tariff']}\n"
            response += f"💰 Сумма: {order['total_price']}₽\n"
            response += f"👥 Участников: {len(order['participants'])}\n"
            response += f"📅 Дата: {order['created_at'][:16]}\n"
            response += f"📊 Статус: {order['status']}\n\n"
        
        await message.answer(response, parse_mode="HTML")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка получения заказов: {e}")

# ОБНОВЛЕННАЯ КОМАНДА /pending - ТЕПЕРЬ ТОЛЬКО С SUPABASE
@dp.message(Command("pending"))
async def cmd_pending(message: types.Message):
    """Заказы ожидающие оплаты С ФАЙЛАМИ ИЗ SUPABASE STORAGE"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа")
        return
    
    log_admin_action(message.from_user.id, message.from_user.username, "⏳ ЗАПРОСИЛ PENDING ЗАКАЗЫ С SUPABASE ЧЕКАМИ")
    
    try:
        orders = db.get_pending_orders()
        
        if not orders:
            await message.answer("✅ Нет заказов ожидающих оплаты")
            return
        
        response = "<b>⏳ ЗАКАЗЫ ОЖИДАЮЩИЕ ОПЛАТЫ:</b>\n\n"
        
        for order in orders:
            # Проверяем наличие файла в Supabase Storage
            supabase_file_info = await get_supabase_file_info(order['id'])
            
            if supabase_file_info:
                file_emoji = "📄" if supabase_file_info['file_name'].endswith('.pdf') else "📸"
                file_info = f"{file_emoji} Supabase: {supabase_file_info['file_name']}"
                file_url = supabase_file_info['public_url']
            elif order.get('receipt_file_name'):
                file_emoji = "📄" if order['receipt_file_name'].endswith('.pdf') else "📸"
                file_info = f"{file_emoji} Supabase DB: {order['receipt_file_name']}"
                file_url = order.get('receipt_file_url')
            else:
                file_info = "❌ Нет чека"
                file_url = None
                
            response += f"🆔 <b>Заказ #{order['id']}</b>\n"
            response += f"👤 @{order['username']} (ID: {order['user_id']})\n"
            response += f"🎫 Тариф: {order['tariff']}\n"
            response += f"💰 Сумма: {order['total_price']}₽\n"
            response += f"👥 Участников: {len(order['participants'])}\n"
            response += f"📅 Создан: {order['created_at'][:16]}\n"
            response += f"📎 Чек: {file_info}\n\n"
            
            if file_url:
                response += f"🔗 <a href='{file_url}'>Ссылка на чек</a>\n\n"
        
        response += f"📊 Всего: {len(orders)} заказов на сумму {sum(o['total_price'] for o in orders)}₽\n\n"
        response += "📎 <b>Отправляю чеки из Supabase Storage...</b>"
        
        await message.answer(response, parse_mode="HTML", disable_web_page_preview=True)
        
        # Отправляем реальные файлы чеков для каждого заказа
        supabase_count = 0
        
        for order in orders:
            try:
                # Пытаемся получить файл из Supabase Storage
                supabase_file_info = await get_supabase_file_info(order['id'])
                
                if supabase_file_info:
                    # Скачиваем файл из Supabase Storage
                    file_data = supabase_client.storage.from_("receipts").download(supabase_file_info['file_name'])
                    
                    if file_data:
                        # Сохраняем временно и отправляем
                        temp_file = f"temp_{supabase_file_info['file_name']}"
                        with open(temp_file, 'wb') as f:
                            f.write(file_data)
                        
                        document = FSInputFile(temp_file)
                        
                        if supabase_file_info['file_name'].endswith('.pdf'):
                            await bot.send_document(
                                message.chat.id,
                                document,
                                caption=f"📋 <b>Чек из Supabase для заказа #{order['id']}</b>\n\n"
                                       f"👤 @{order['username']}\n"
                                       f"🎫 Тариф: {order['tariff']}\n"
                                       f"💰 Сумма: {order['total_price']}₽\n"
                                       f"👥 Участников: {len(order['participants'])}\n"
                                       f"📅 Дата: {order['created_at'][:16]}\n"
                                       f"☁️ <b>Хранилище: Supabase Storage</b>\n"
                                       f"🔗 <a href='{supabase_file_info['public_url']}'>Прямая ссылка</a>",
                                parse_mode="HTML"
                            )
                        else:
                            await bot.send_photo(
                                message.chat.id,
                                document,
                                caption=f"📋 <b>Чек из Supabase для заказа #{order['id']}</b>\n\n"
                                       f"👤 @{order['username']}\n"
                                       f"🎫 Тариф: {order['tariff']}\n"
                                       f"💰 Сумма: {order['total_price']}₽\n"
                                       f"👥 Участников: {len(order['participants'])}\n"
                                       f"📅 Дата: {order['created_at'][:16]}\n"
                                       f"☁️ <b>Хранилище: Supabase Storage</b>\n"
                                       f"🔗 <a href='{supabase_file_info['public_url']}'>Прямая ссылка</a>",
                                parse_mode="HTML"
                            )
                        
                        # Удаляем временный файл
                        os.remove(temp_file)
                        supabase_count += 1
                    else:
                        await message.answer(f"❌ Не удалось скачать файл для заказа #{order['id']}")
                else:
                    await message.answer(f"❌ Для заказа #{order['id']} нет прикрепленного чека")
                    
            except Exception as e:
                await message.answer(f"❌ Ошибка при отправке чека для заказа #{order['id']}: {e}")
                continue
        
        # Статистика отправленных файлов
        stats_text = f"✅ Все чеки отправлены!\n\n"
        stats_text += f"📊 Статистика:\n"
        stats_text += f"• ☁️ Supabase Storage: {supabase_count}\n"
        stats_text += f"• 📋 Всего заказов: {len(orders)}"
        
        await message.answer(stats_text)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка получения pending заказов: {e}")

@dp.message(Command("paid"))
async def cmd_paid(message: types.Message):
    """Оплаченные заказы"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа")
        return
    
    log_admin_action(message.from_user.id, message.from_user.username, "✅ ЗАПРОСИЛ(-а) PAID ЗАКАЗЫ")
    
    try:
        orders = db.get_paid_orders()
        
        if not orders:
            await message.answer("💰 Нет оплаченных заказов")
            return
        
        response = "<b>✅ ОПЛАЧЕННЫЕ ЗАКАЗЫ:</b>\n\n"
        
        for order in orders[:10]:
            response += f"🎫 <b>Заказ #{order['id']}</b>\n"
            response += f"👤 @{order['username']} (ID: {order['user_id']})\n"
            response += f"📋 Тариф: {order['tariff']}\n"
            response += f"💰 Сумма: {order['total_price']}₽\n"
            response += f"👥 Участников: {len(order['participants'])}\n"
            response += f"📅 Дата: {order['created_at'][:16]}\n\n"
        
        if len(orders) > 10:
            response += f"📎 ... и еще {len(orders) - 10} заказов\n"
        
        total_revenue = sum(o['total_price'] for o in orders)
        response += f"💰 <b>Общая выручка:</b> {total_revenue}₽"
        
        await message.answer(response, parse_mode="HTML")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка получения paid заказов: {e}")

# КОМАНДА ДЛЯ ПОЛУЧЕНИЯ КОНКРЕТНОГО ЧЕКА
@dp.message(Command("receipt"))
async def cmd_receipt(message: types.Message):
    """Получить чек для конкретного заказа"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа")
        return
    
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer("❌ Использование: /receipt <order_id>\nПример: /receipt 15")
            return
        
        order_id = args[1]
        
        if not order_id.isdigit():
            await message.answer("❌ Order ID должен быть числом")
            return
        
        log_admin_action(message.from_user.id, message.from_user.username, "📄 ЗАПРОСИЛ ЧЕК", f"Order ID: {order_id}")
        
        order = db.get_order_by_id(int(order_id))
        if not order:
            await message.answer(f"❌ Заказ #{order_id} не найден")
            return
        
        # Пробуем получить файл из Supabase Storage
        supabase_file_info = await get_supabase_file_info(int(order_id))
        
        if supabase_file_info:
            # Скачиваем файл из Supabase Storage
            file_data = supabase_client.storage.from_("receipts").download(supabase_file_info['file_name'])
            
            if file_data:
                # Сохраняем временно и отправляем
                temp_file = f"temp_{supabase_file_info['file_name']}"
                with open(temp_file, 'wb') as f:
                    f.write(file_data)
                
                document = FSInputFile(temp_file)
                
                if supabase_file_info['file_name'].endswith('.pdf'):
                    await bot.send_document(
                        message.chat.id,
                        document,
                        caption=f"📋 <b>Чек из Supabase для заказа #{order_id}</b>\n\n"
                               f"👤 @{order['username']}\n"
                               f"🎫 Тариф: {order['tariff']}\n"
                               f"💰 Сумма: {order['total_price']}₽\n"
                               f"👥 Участников: {len(order['participants'])}\n"
                               f"📅 Дата: {order['created_at'][:16]}\n"
                               f"📊 Статус: {order['status']}\n"
                               f"☁️ <b>Хранилище: Supabase Storage</b>\n"
                               f"🔗 <a href='{supabase_file_info['public_url']}'>Прямая ссылка</a>",
                        parse_mode="HTML"
                    )
                else:
                    await bot.send_photo(
                        message.chat.id,
                        document,
                        caption=f"📋 <b>Чек из Supabase для заказа #{order_id}</b>\n\n"
                               f"👤 @{order['username']}\n"
                               f"🎫 Тариф: {order['tariff']}\n"
                               f"💰 Сумма: {order['total_price']}₽\n"
                               f"👥 Участников: {len(order['participants'])}\n"
                               f"📅 Дата: {order['created_at'][:16]}\n"
                               f"📊 Статус: {order['status']}\n"
                               f"☁️ <b>Хранилище: Supabase Storage</b>\n"
                               f"🔗 <a href='{supabase_file_info['public_url']}'>Прямая ссылка</a>",
                        parse_mode="HTML"
                    )
                
                # Удаляем временный файл
                os.remove(temp_file)
                await message.answer(f"✅ Чек для заказа #{order_id} отправлен из Supabase Storage!")
                return
        
        await message.answer(f"❌ Для заказа #{order_id} нет прикрепленного чека")
            
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки чека: {e}")

# ПОМОЩЬ
@dp.message(F.text == "💬 Помощь")
async def cmd_help(message: types.Message):
    log_event(message.from_user.id, message.from_user.username, "💬 ЗАПРОСИЛ(-а) ПОМОЩЬ")
    
    help_text = """
<b>ПОМОЩЬ И ПОДДЕРЖКА 🆘</b>

📋 <b>Команды бота:</b>
• Старт - начать работу
• Информация о мероприятии - детали вечеринки
• Посмотреть тарифы - выбрать билет
• Помощь - эта информация

📞 <b>Техподдержка:</b>
• По вопросам оплаты: @m5frls
• По мероприятию: @m5frls
• Чат: t.me/gedanvecherinky

💡 <b>Частые вопросы:</b>
• Оплата: перевод на карту Сбербанка
• Возвраты: за 48 часов до события
• Дресс-код: хэллоуин-костюмы приветствуются!
• Чеки: принимаем только <b>PDF</b> (макс. 20MB)
    """
    
    keyboard = [
        [types.InlineKeyboardButton(text="⬅️ НАЗАД", callback_data="back_to_main")]
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    await message.answer(help_text, reply_markup=markup, parse_mode="HTML")

# ОБРАБОТКА ДРУГИХ СООБЩЕНИЙ
@dp.message()
async def handle_other_messages(message: types.Message):
    log_event(message.from_user.id, message.from_user.username, "💬 ОТПРАВИЛ(-а) СООБЩЕНИЕ", f"Текст: {message.text}")
    await show_main_menu(message)

# ОСНОВНАЯ ФУНКЦИЯ ЗАПУСКА
async def main():
    print("=" * 70)
    print("🤖 ЗАПУСК БОТА - ТОЛЬКО SUPABASE")
    print("=" * 70)
    
    # Создаем bucket для чеков
    create_receipts_bucket()
    
    # Проверка подключений
    print("🔍 ПРОВЕРКА СИСТЕМЫ...")
    print(f"📊 Supabase: {'✅' if supabase_client else '❌'}")
    print(f"☁️ Supabase Storage: ✅ Bucket 'receipts' создан")
    print(f"📎 Хранение чеков: ✅ Облачное хранилище готово")
    print(f"📄 Поддержка PDF: ✅ Макс. размер {MAX_FILE_SIZE // (1024*1024)}MB")
    print(f"💳 Сбербанк: ✅ {SBER_ACCOUNT}")
    print(f"🎫 Тарифы: {len(TARIFFS)} шт.")
    print(f"🖼️ Картинка мероприятия: {'✅' if os.path.exists(EVENT_IMAGE_PATH) else '❌'}")
    print(f"👨‍💼 Админы: {len(ADMIN_IDS)} человек")
    
    # Показываем статистику Supabase
    stats = db.get_statistics()
    print(f"📈 Supabase статистика: {stats['total_orders']} заказов, {stats['total_revenue']}₽ выручки")
    
    print("\n🎯 ОСНОВНЫЕ ФУНКЦИИ:")
    print("   • 🎫 Выбор мероприятия и тарифа")
    print("   • 👥 Ввод данных участников") 
    print("   • 💳 Оплата переводом на карту")
    print("   • 📎 Сохранение реальных чеков (PDF, фото)")
    print("   • ☁️ 100% ОБЛАЧНОЕ ХРАНИЛИЩЕ: Supabase для данных и файлов")
    print("   • 👨‍💼 Просмотр реальных чеков в админке (/pending)")
    print("   • ✅ Подтверждение оплаты (/approve)")
    print("   • 🛠️ Сброс состояний (/reset)")
    print("=" * 70)
    
    try:
        print("🟢 Бот начал работу...")
        await dp.start_polling(bot)
    except Exception as e:
        print(f"🔴 КРИТИЧЕСКАЯ ОШИБКА: {e}")
    finally:
        print("🟡 Бот остановлен")

if __name__ == "__main__":
    asyncio.run(main())