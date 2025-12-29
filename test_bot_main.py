# test_bot_main.py 29.12 16:12
import os
import sys
import time
import logging
import importlib.util
import sqlite3
from pathlib import Path
import telebot
from telebot import types
from threading import Lock, Thread
from datetime import datetime, timedelta
import signal
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

API_TOKEN = os.environ.get("API_TOKEN")
if not API_TOKEN:
    raise ValueError("API_TOKEN environment variable is required")

bot = telebot.TeleBot(API_TOKEN)
db_lock = Lock()
user_states = {}
spam_protection = {}
MODULES_DIR = Path("modules")
DB_PATH = "test_bot.db"

def init_db():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                fio TEXT,
                position TEXT,
                department TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS test_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                module_name TEXT,
                level TEXT,
                score INTEGER,
                total_questions INTEGER,
                percentage REAL,
                test_time TEXT,
                passed INTEGER DEFAULT 0,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        conn.commit()
        conn.close()

def rate_limit_check(user_id):
    now = time.time()
    if user_id in spam_protection:
        if now - spam_protection[user_id] < 1:
            return False
    spam_protection[user_id] = now
    return True

def load_module(module_name):
    module_path = MODULES_DIR / f"{module_name}.py"
    if not module_path.exists():
        return None
    
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def safe_edit_message(bot_instance, chat_id, message_id, text, reply_markup=None):
    try:
        bot_instance.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup
        )
    except telebot.apihelper.ApiTelegramException:
        pass

def safe_delete_message(bot_instance, chat_id, message_id):
    try:
        bot_instance.delete_message(chat_id=chat_id, message_id=message_id)
    except telebot.apihelper.ApiTelegramException:
        pass

@bot.message_handler(commands=['start'])
def start_command(message):
    if not rate_limit_check(message.from_user.id):
        return
    
    user_id = message.from_user.id
    user_states[user_id] = {'state': 'welcome'}
    
    markup = types.InlineKeyboardMarkup()
    btn_modules = types.InlineKeyboardButton("🚀 Тесты", callback_data="select_module")
    btn_stats = types.InlineKeyboardButton("📊 Моя статистика", callback_data="show_stats")
    markup.add(btn_modules, btn_stats)
    
    bot.send_message(
        message.chat.id,
        "🎓 Добро пожаловать в систему тестирования!\n\n"
        "Выберите действие:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if not rate_limit_check(call.from_user.id):
        bot.answer_callback_query(call.id, "Слишком быстро! Подождите секунду.")
        return
    
    user_id = call.from_user.id
    data = call.data
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    if data == "select_module":
        modules = [m.name for m in MODULES_DIR.glob("*.py") if m.name != "__init__.py"]
        if not modules:
            safe_edit_message(bot, chat_id, message_id, "❌ Модули тестов не найдены.")
            return
        
        markup = types.InlineKeyboardMarkup()
        for module in modules:
            btn = types.InlineKeyboardButton(
                module.replace("_", " ").title(), 
                callback_data=f"module_{module}"
            )
            markup.add(btn)
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_main"))
        safe_edit_message(bot, chat_id, message_id, "📚 Выберите тест:", reply_markup=markup)
        user_states[user_id] = {'state': 'select_module'}
    
    elif data.startswith("module_"):
        module_name = data.replace("module_", "")
        module = load_module(module_name)
        if module and hasattr(module, 'register_user'):
            user_states[user_id] = {
                'state': 'register_user',
                'module_name': module_name,
                'module': module
            }
            module.register_user(bot, user_id, chat_id, message_id)
        else:
            safe_edit_message(bot, chat_id, message_id, f"❌ Модуль {module_name} недоступен.")
    
    elif data == "show_stats":
        show_user_stats(user_id, chat_id, message_id)
    
    elif data == "back_main":
        markup = types.InlineKeyboardMarkup()
        btn_modules = types.InlineKeyboardButton("🚀 Тесты", callback_data="select_module")
        btn_stats = types.InlineKeyboardButton("📊 Моя статистика", callback_data="show_stats")
        markup.add(btn_modules, btn_stats)
        safe_edit_message(bot, chat_id, message_id, "🎓 Главное меню:", reply_markup=markup)
        user_states[user_id] = {'state': 'welcome'}

def show_user_stats(user_id, chat_id, message_id):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM test_stats WHERE user_id=? AND passed=1", (user_id,))
        passed = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM test_stats WHERE user_id=?", (user_id,))
        total = cursor.fetchone()[0]
        conn.close()
    
    stats_text = f"📊 Ваша статистика:\n\n✅ Успешных тестов: {passed}\n📝 Всего попыток: {total}"
    if total > 0:
        success_rate = (passed / total) * 100
        stats_text += f"\n📈 Успешность: {success_rate:.1f}%"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_main"))
    safe_edit_message(bot, chat_id, message_id, stats_text, reply_markup=markup)

def signal_handler(sig, frame):
    logger.info("Shutting down bot...")
    bot.stop_polling()
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    init_db()
    logger.info("Starting test bot...")
    bot.infinity_polling()
