# 29.12 15:08 test_bot_main.py
import os
import sys
import time
import logging
import importlib.util
import sqlite3
from pathlib import Path
import telebot
from telebot import types
from threading import Lock
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

API_TOKEN = os.environ.get("API_TOKEN")
if not API_TOKEN:
    logger.error("API_TOKEN not set")
    sys.exit(1)

bot = telebot.TeleBot(API_TOKEN)
db_lock = Lock()
modules = {}
user_states = {}
active_tests = {}

DB_PATH = "test_bot.db"

def init_db():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                position TEXT,
                department TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS test_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                module_name TEXT,
                score INTEGER,
                total_questions INTEGER,
                time_spent REAL,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_progress (
                user_id INTEGER PRIMARY KEY,
                module_name TEXT,
                current_question INTEGER DEFAULT 0,
                start_time REAL,
                answers TEXT DEFAULT '{}',
                difficulty TEXT DEFAULT '',
                questions TEXT DEFAULT '[]',
                UNIQUE(user_id, module_name)
            )
        ''')
        conn.commit()
        conn.close()

def load_modules():
    global modules
    modules_dir = Path(".")
    for module_file in modules_dir.glob("*.py"):
        if module_file.name in ["test_bot_main.py", "__init__.py"]:
            continue
        module_name = module_file.stem
        try:
            spec = importlib.util.spec_from_file_location(module_name, module_file)
            if spec:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                if hasattr(module, 'get_questions'):
                    modules[module_name] = module
                    logger.info(f"Loaded module: {module_name}")
        except Exception as e:
            logger.error(f"Failed to load module {module_name}: {e}")

def clean_chat(user_id, message_id):
    try:
        bot.delete_message(user_id, message_id)
    except:
        pass

def create_modules_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    module_buttons = []
    
    for module_name in modules:
        module_buttons.append(types.KeyboardButton(
            f"Тест: {module_name.replace('_', ' ').title()[:20]}"
        ))
    
    for i in range(0, len(module_buttons), 2):
        if i + 1 < len(module_buttons):
            markup.row(module_buttons[i], module_buttons[i+1])
        else:
            markup.row(module_buttons[i])
    
    markup.row(types.KeyboardButton("🆘 Помощь"))
    return markup

@bot.message_handler(commands=['start'])
@bot.message_handler(func=lambda message: message.text == "🆘 Помощь")
def start_handler(message):
    user_id = message.from_user.id
    if message.message_id:
        clean_chat(user_id, message.message_id)
    
    if message.text == "🆘 Помощь":
        bot.send_message(user_id, 
            "Инструкция:\n1. Выберите тест из кнопок ниже\n2. Введите данные\n3. Выберите сложность\n4. Отвечайте\n5. Получите результат",
            reply_markup=create_modules_keyboard())
        return
    
    bot.send_message(user_id, "🎓 Выберите тест:", reply_markup=create_modules_keyboard())

@bot.message_handler(func=lambda message: message.text and message.text.startswith("Тест:"))
def handle_module_selection(message):
    user_id = message.from_user.id
    clean_chat(user_id, message.message_id)
    
    module_name = message.text.replace("Тест: ", "").replace(" ", "_").lower()
    
    if module_name not in modules:
        bot.send_message(user_id, "Модуль не найден", reply_markup=create_modules_keyboard())
        return
    
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT full_name FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
    
    if not result:
        bot.send_message(user_id, "👤 Введите ФИО:", reply_markup=types.ReplyKeyboardRemove())
        user_states[user_id] = {'state': 'waiting_name', 'module': module_name}
        bot.register_next_step_handler(message, process_name)
    else:
        start_quiz(user_id, module_name, None)

def process_name(message):
    user_id = message.from_user.id
    if user_id not in user_states:
        return
    
    clean_chat(user_id, message.message_id)
    state = user_states[user_id]
    
    full_name = message.text.strip()
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO users (user_id, full_name) VALUES (?, ?)", 
                     (user_id, full_name))
        conn.commit()
        conn.close()
    
    bot.send_message(user_id, "💼 Введите должность:")
    user_states[user_id]['full_name'] = full_name
    user_states[user_id]['state'] = 'waiting_position'
    bot.register_next_step_handler(message, process_position)

def process_position(message):
    user_id = message.from_user.id
    if user_id not in user_states:
        return
    
    clean_chat(user_id, message
