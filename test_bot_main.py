# 29.12 15:10 test_bot_main.py
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
        for i, option in enumerate(question['options']):
            status = "X" if i in current_answers else str(i+1)
            callback_data = f"toggle_answer:{module_name}:{question_index}:{i}"
            markup.add(types.InlineKeyboardButton(f"{status} {option}", callback_data))
        
        next_btn_text = "Завершить тест" if question_index == len(questions) - 1 else "Далее"
        markup.add(types.InlineKeyboardButton(next_btn_text, 
                                            callback_data=f"next_question:{module_name}:{question_index}"))
        markup.row(types.InlineKeyboardButton("⏰ Завершить тест", 
                                            callback_data=f"finish:{module_name}"))
        
        text = f"Вопрос {question_index + 1}/{len(questions)}\n\n{question.get('question', question.get('text', 'Вопрос'))}\nВыбрано: {len(current_answers)}"
        
        if test_data['message_id']:
            try:
                bot.edit_message_text(text, user_id, test_data['message_id'], reply_markup=markup)
            except:
                msg = bot.send_message(user_id, text, reply_markup=markup)
                test_data['message_id'] = msg.message_id
        else:
            msg = bot.send_message(user_id, text, reply_markup=markup)
            test_data['message_id'] = msg.message_id
            
    except Exception as e:
        logger.error(f"Error showing question {question_index}: {e}")
        bot.send_message(user_id, "Ошибка показа вопроса")

def finish_test(user_id):
    if user_id not in active_tests:
        return
    
    test_data = active_tests[user_id]
    module_name = test_data['module']
    
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT answers, start_time, questions FROM user_progress 
                WHERE user_id = ? AND module_name =

                SELECT answers, start_time, questions FROM user_progress 
                WHERE user_id = ? AND module_name = ?
            ''', (user_id, module_name))
            result = cursor.fetchone()
            conn.close()
        
        if result:
            answers = json.loads(result[0]) if result[0] else {}
            start_time = result[1]
            stored_questions = json.loads(result[2]) if result[2] else []
            time_spent = time.time() - start_time
            
            module = modules[module_name]
            questions = stored_questions if stored_questions else []
            score = module.calculate_score(questions, answers)
            total_questions = len(questions)
            
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=10)
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO test_results (user_id, module_name, score, total_questions, time_spent)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, module_name, score, total_questions, time_spent))
                cursor.execute('DELETE FROM user_progress WHERE user_id = ? AND module_name = ?', 
                             (user_id, module_name))
                conn.commit()
                conn.close()
            
            if test_data['message_id']:
                clean_chat(user_id, test_data['message_id'])
            
            percentage = (score / total_questions) * 100 if total_questions > 0 else 0
            result_text = f"""✅ Тест завершен!

Результаты:
Правильных: {score}/{total_questions}
Процент: {percentage:.1f}%
Время: {time_spent:.0f}с

Модуль: {module_name.replace('_', ' ').title()}"""
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔄 Новый тест", callback_data="new_test"))
            
            bot.send_message(user_id, result_text, reply_markup=markup)
            
            if hasattr(module, 'generate_certificate'):
                try:
                    certificate_path = module.generate_certificate(user_id, score, total_questions, time_spent)
                    if certificate_path and Path(certificate_path).exists():
                        with open(certificate_path, 'rb') as cert:
                            bot.send_document(user_id, cert, caption="📜 Сертификат")
                        os.remove(certificate_path)
                except Exception as cert_e:
                    logger.error(f"Certificate error: {cert_e}")
        
        del active_tests[user_id]
        
    except Exception as e:
        logger.error(f"Error finishing test: {e}")
        bot.send_message(user_id, "Ошибка завершения теста", reply_markup=create_modules_keyboard())

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    data = call.data
    
    try:
        if data in ["start", "new_test"]:
            bot.send_message(user_id, "Выберите тест:", reply_markup=create_modules_keyboard())
            bot.answer_callback_query(call.id)
            return
        
        if data.startswith("difficulty:"):
            difficulty = data.split(":", 1)[1]
            test_data = active_tests.get(user_id)
            if test_data:
                module_name = test_data['module']
                module = modules[module_name]
                info = getattr(module, 'DIFFICULTIES', {}).get(difficulty, {})
                
                if hasattr(module, 'ql') and module.ql:
                    questions = module.ql.get_random_questions(info['questions'])
                else:
                    questions = []
                
                with db_lock:
                    conn = sqlite3.connect(DB_PATH, timeout=10)
                    cursor = conn.cursor()
                    cursor.execute('''
                        UPDATE user_progress SET difficulty = ?, questions = ? 
                        WHERE user_id = ? AND module_name = ?
                    ''', (difficulty, json.dumps(questions), user_id, module_name))
                    conn.commit()
                    conn.close()
                
                bot.answer_callback_query(call.id, f"Сложность: {info['name']}")
                show_question(user_id, 0)
            return
        
        if data.startswith("toggle_answer:"):
            parts = data.split(":")
            _, module_name, question_idx, answer_idx = parts
            question_idx = int(question_idx)
            answer_idx = int(answer_idx)
            
            if user_id in active_tests and active_tests[user_id]['module'] == module_name:
                with db_lock:
                    conn = sqlite3.connect(DB_PATH, timeout=10)
                    cursor = conn.cursor()
                    cursor.execute('SELECT answers FROM user_progress WHERE user_id = ? AND module_name = ?',
                                 (user_id, module_name))
                    result = cursor.fetchone()
                    answers = json.loads(result[0]) if result and result[0] else {}
                    
                    if question_idx not in answers:
                        answers[question_idx] = []
                    
                    answer_id = int(answer_idx)
                    if answer_id in answers[question_idx]:
                        answers[question_idx].remove(answer_id)
                    else:
                        answers[question_idx].append(answer_id)
                    
                    cursor.execute('UPDATE user_progress SET answers = ? WHERE user_id = ? AND module_name = ?',
                                 (json.dumps(answers), user_id, module_name))
                    conn.commit()
                    conn.close()
                
                bot.answer_callback_query(call.id, "Ответ обновлен")
                show_question(user_id, question_idx)
            return
        
        if data.startswith("next_question:"):
            parts = data.split(":")
            _, module_name, question_idx = parts
            question_idx = int(question_idx)
            if user_id in active_tests and active_tests[user_id]['module'] == module_name:
                bot.answer_callback_query(call.id, "Следующий вопрос")
                show_question(user_id, question_idx + 1)
            return
        
        if data.startswith("finish:"):
            bot.answer_callback_query(call.id, "Завершение теста...")
            finish_test(user_id)
        
    except Exception as e:
        logger.error(f"Callback error: {e}")
        bot.answer_callback_query(call.id, "Ошибка обработки")

if __name__ == "__main__":
    init_db()
    load_modules()
    logger.info("Bot started")
    while True:
        try:
            bot.infinity_polling(none_stop=True, interval=1, timeout=30)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(10)
