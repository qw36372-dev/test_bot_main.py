# 29.12 15:44 test_bot_main.py
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

# ✅ ВАШИ 11 специализаций + Помощь = 12 кнопок
SPECIALIZATIONS = {
    "ООУПДС": "OUPDS_test_bot.py",
    "Исполнители": "Ispolniteli_test_bot.py", 
    "Дознание": "Doznanie_test_bot.py",
    "Алименты": "Aliment_test_bot.py",
    "Розыск": "Rozisk_test_bot.py",
    "ОПП": "Prof_test_bot.py",
    "ОКО": "OKO_test_bot.py",
    "Информатизация": "Informatizaciya_test_bot.py",
    "Кадры": "Kadri_test_bot.py",
    "ОСБ": "Bezopasnost_test_bot.py",
    "Управление": "Starshie_test_bot.py"
}

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
    logger.info(f"Scanning directory: {modules_dir}")
    
    for module_file in modules_dir.glob("*.py"):
        logger.info(f"Found file: {module_file.name}")
        if module_file.name in ["test_bot_main.py", "__init__.py"]:
            continue
        module_name = module_file.stem
        logger.info(f"Attempting to load module: {module_name}")
        
        try:
            spec = importlib.util.spec_from_file_location(module_name, module_file)
            if spec:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                if hasattr(module, 'get_questions'):
                    modules[module_name] = module
                    logger.info(f"✅ SUCCESS: Loaded module {module_name}")
                else:
                    logger.error(f"❌ FAIL: {module_name} missing get_questions()")
            else:
                logger.error(f"❌ FAIL: No spec for {module_name}")
        except Exception as e:
            logger.error(f"❌ CRASH loading {module_name}: {e}")
    
    logger.info(f"Total modules loaded: {len(modules)}")
    logger.info(f"Loaded modules: {list(modules.keys())}")

def clean_chat(user_id, message_id):
    try:
        bot.delete_message(user_id, message_id)
    except:
        pass

def create_modules_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    # ✅ 11 кнопок по вашему списку
    for spec_name in SPECIALIZATIONS.keys():
        markup.add(types.KeyboardButton(spec_name))
    
    markup.row(types.KeyboardButton("🆘 Помощь"))
    return markup

def get_module_name(display_name):
    """Маппинг кнопки → имя файла модуля"""
    if display_name in SPECIALIZATIONS:
        filename = SPECIALIZATIONS[display_name]
        return Path(filename).stem  # Убираем .py
    return None

@bot.message_handler(commands=['start'])
@bot.message_handler(func=lambda message: message.text == "🆘 Помощь")
def start_handler(message):
    user_id = message.from_user.id
    if message.message_id:
        clean_chat(user_id, message.message_id)
    
    if message.text == "🆘 Помощь":
        bot.send_message(user_id, 
            "Инструкция:\n1. Выберите тест из кнопок ниже\n2. Введите ФИО, должность, отдел\n3. Выберите сложность\n4. Отвечайте на вопросы\n5. Получите результат + сертификат",
            reply_markup=create_modules_keyboard())
        return
    
    bot.send_message(user_id, "🎓 Выберите специализацию:", reply_markup=create_modules_keyboard())

@bot.message_handler(func=lambda message: message.text in SPECIALIZATIONS)
def handle_module_selection(message):
    user_id = message.from_user.id
    clean_chat(user_id, message.message_id)
    
    module_name = get_module_name(message.text)
    
    if not module_name or module_name not in modules:
        bot.send_message(user_id, f"❌ Модуль '{message.text}' не загружен", reply_markup=create_modules_keyboard())
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
    
    clean_chat(user_id, message.message_id)
    state = user_states[user_id]
    
    position = message.text.strip()
    user_states[user_id]['position'] = position
    
    bot.send_message(user_id, "🏢 Введите отдел:")
    user_states[user_id]['state'] = 'waiting_department'
    bot.register_next_step_handler(message, process_department)

def process_department(message):
    user_id = message.from_user.id
    if user_id not in user_states:
        return
    
    clean_chat(user_id, message.message_id)
    state = user_states[user_id]
    
    department = message.text.strip()
    module_name = state['module']
    
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET position = ?, department = ? WHERE user_id = ?',
                     (state['position'], department, user_id))
        conn.commit()
        conn.close()
    
    del user_states[user_id]
    start_quiz(user_id, module_name, None)

def start_quiz(user_id, module_name, message_id):
    if module_name not in modules:
        bot.send_message(user_id, "Модуль не загружен", reply_markup=create_modules_keyboard())
        return
    
    module = modules[module_name]
    
    try:
        start_time = time.time()
        empty_answers = json.dumps({})
        empty_questions = json.dumps([])
        
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO user_progress 
                (user_id, module_name, current_question, start_time, answers, difficulty, questions)
                VALUES (?, ?, 0, ?, ?, ?, ?)
            ''', (user_id, module_name, start_time, empty_answers, '', empty_questions))
            conn.commit()
            conn.close()
        
        active_tests[user_id] = {
            'module': module_name,
            'message_id': None,
            'start_time': start_time
        }
        
        show_question(user_id, 0)
        
    except Exception as e:
        logger.error(f"Error starting quiz {module_name}: {e}")
        bot.send_message(user_id, "Ошибка запуска теста", reply_markup=create_modules_keyboard())

# ... остальные функции без изменений (show_question, finish_test, callback_handler)

def show_question(user_id, question_index):
    if user_id not in active_tests:
        return
    
    test_data = active_tests[user_id]
    module_name = test_data['module']
    module = modules[module_name]
    
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT answers, difficulty, questions FROM user_progress 
                WHERE user_id = ? AND module_name = ?
            ''', (user_id, module_name))
            result = cursor.fetchone()
            conn.close()
        
        if not result:
            bot.send_message(user_id, "Ошибка загрузки прогресса")
            return
        
        answers = json.loads(result[0])
        difficulty = result[1] or ''
        stored_questions = json.loads(result[2])
        
        if not stored_questions or difficulty == '':
            module_data = module.get_questions()
            if isinstance(module_data, dict) and module_data.get('type') == 'difficulty_menu':
                text = module_data['text']
                markup = module_data['markup']
                
                if test_data['message_id']:
                    try:
                        bot.edit_message_text(text, user_id, test_data['message_id'], reply_markup=markup)
                    except:
                        msg = bot.send_message(user_id, text, reply_markup=markup)
                        test_data['message_id'] = msg.message_id
                else:
                    msg = bot.send_message(user_id, text, reply_markup=markup)
                    test_data['message_id'] = msg.message_id
                return
        
        questions = stored_questions
        if question_index >= len(questions):
            finish_test(user_id)
            return
        
        question = questions[question_index]
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        current_answers = answers.get(question_index, [])
        for i, option in enumerate
