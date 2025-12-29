# test_bot_main.py
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
        spec = importlib.util.spec_from_file_location(module_name, module_file)
        if spec:
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            if hasattr(module, 'get_questions'):
                modules[module_name] = module
                logger.info(f"Loaded module: {module_name}")

@bot.message_handler(commands=['start'])
def start_handler(message):
    user_id = message.from_user.id
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for module_name in modules:
        markup.add(types.InlineKeyboardButton(
            f"Тест: {module_name.replace('_', ' ').title()}", 
            callback_data=f"start_test:{module_name}"
        ))
    
    markup.add(types.InlineKeyboardButton("Помощь", callback_data="help"))
    bot.send_message(user_id, "Выберите тест:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('start_test:'))
def start_test(call):
    _, module_name = call.data.split(':', 1)
    user_id = call.from_user.id
    
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT full_name FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
    
    if not result:
        msg = bot.send_message(user_id, "Введите ФИО:")
        user_states[user_id] = {'state': 'waiting_name', 'module': module_name}
        bot.register_next_step_handler(msg, process_name)
    else:
        start_quiz(user_id, module_name, call.message.message_id)

def process_name(message):
    user_id = message.from_user.id
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    if state['state'] == 'waiting_name':
        full_name = message.text.strip()
        with db_lock:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO users (user_id, full_name) VALUES (?, ?)", 
                         (user_id, full_name))
            conn.commit()
            conn.close()
        
        msg = bot.send_message(user_id, "Введите должность:")
        user_states[user_id]['full_name'] = full_name
        user_states[user_id]['state'] = 'waiting_position'
        bot.register_next_step_handler(msg, process_position)

def process_position(message):
    user_id = message.from_user.id
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    position = message.text.strip()
    user_states[user_id]['position'] = position
    
    msg = bot.send_message(user_id, "Введите отдел:")
    user_states[user_id]['state'] = 'waiting_department'
    bot.register_next_step_handler(msg, process_department)

def process_department(message):
    user_id = message.from_user.id
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    department = message.text.strip()
    module_name = state['module']
    
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users SET position = ?, department = ? 
            WHERE user_id = ?
        ''', (state['position'], department, user_id))
        conn.commit()
        conn.close()
    
    start_quiz(user_id, module_name, None)

def start_quiz(user_id, module_name, message_id):
    if module_name not in modules:
        bot.send_message(user_id, "Модуль не загружен")
        return
    
    module = modules[module_name]
    
    if message_id:
        try:
            bot.delete_message(user_id, message_id)
        except:
            pass
    
    try:
        start_time = time.time()
        with db_lock:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO user_progress 
                (user_id, module_name, current_question, start_time, answers, difficulty)
                VALUES (?, ?, 0, ?, '{}', '')
            ''', (user_id, module_name, start_time))
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
        bot.send_message(user_id, "Ошибка запуска теста")

def show_question(user_id, question_index):
    if user_id not in active_tests:
        return
    
    test_data = active_tests[user_id]
    module_name = test_data['module']
    module = modules[module_name]
    
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT answers, difficulty, questions FROM user_progress 
                WHERE user_id = ? AND module_name = ?
            ''', (user_id, module_name))
            result = cursor.fetchone()
            conn.close()
        
        answers = eval(result[0]) if result and result[0] else {}
        difficulty = result[1] if result else ''
        stored_questions = json.loads(result[2]) if result and result[2] else []
        
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
        
        questions = stored_questions if stored_questions else module_data
        
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
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT answers, start_time, questions FROM user_progress 
                WHERE user_id = ? AND module_name = ?
            ''', (user_id, module_name))
            result = cursor.fetchone()
            conn.close()
        
        if result:
            answers = eval(result[0]) if result[0] else {}
            start_time = result[1]
            stored_questions = json.loads(result[2]) if result[2] else []
            time_spent = time.time() - start_time
            
            module = modules[module_name]
            questions = stored_questions if stored_questions else module.get_questions()
            score = module.calculate_score(questions, answers)
            
            total_questions = len(questions)
            
            with db_lock:
                conn = sqlite3.connect(DB_PATH)
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
                try:
                    bot.delete_message(user_id, test_data['message_id'])
                except:
                    pass
            
            percentage = (score / total_questions) * 100 if total_questions > 0 else 0
            result_text = f"""
🎉 Тест завершен!

Результаты:
✅ Правильных: {score}/{total_questions}
📊 Процент: {percentage:.1f}%
⏱️ Время: {time_spent:.0f}с

Модуль: {module_name.replace('_', ' ').title()}
            """
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔄 Новый тест", callback_data="start"))
            
            bot.send_message(user_id, result_text.strip(), reply_markup=markup)
            
            if hasattr(module, 'generate_certificate'):
                try:
                    certificate_path = module.generate_certificate(user_id, score, total_questions, time_spent)
                    if certificate_path:
                        with open(certificate_path, 'rb') as cert:
                            bot.send_document(user_id, cert, caption="Сертификат")
                        os.remove(certificate_path)
                except:
                    pass
        
        del active_tests[user_id]
        
    except Exception as e:
        logger.error(f"Error finishing test: {e}")
        bot.send_message(user_id, "Ошибка завершения теста")

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    data = call.data
    
    try:
        if data == "start":
            if call.message and call.message.message_id:
                try:
                    bot.delete_message(user_id, call.message.message_id)
                except:
                    pass
            start_handler(call.message)
            bot.answer_callback_query(call.id)
            return
        
        if data == "help":
            bot.edit_message_text(
                "Инструкция:\n1. Выберите тест\n2. Введите данные\n3. Выберите сложность\n4. Отвечайте (можно отменить выбор X)\n5. Далее/Завершить\n6. Получите результат",
                user_id, call.message.message_id
            )
            bot.answer_callback_query(call.id)
            return
        
        if data.startswith("difficulty:"):
            difficulty = data.split(":", 1)[1]
            test_data = active_tests.get(user_id)
            if test_
                module_name = test_data['module']
                module = modules[module_name]
                info = getattr(module, 'DIFFICULTIES', {}).get(difficulty, {})
                
                if 'ql' in dir(module):
                    questions = module.ql.get_random_questions(info['questions'])
                else:
                    questions = []
                
                with db_lock:
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute('''
                        UPDATE user_progress SET difficulty = ?, questions = ? 
                        WHERE user_id = ? AND module_name = ?
                    ''', (difficulty, json.dumps(questions), user_id, module_name))
                    conn.commit()
                    conn.close()
                
                test_data['questions'] = questions
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
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT answers FROM user_progress 
                        WHERE user_id = ? AND module_name = ?
                    ''', (user_id, module_name))
                    result = cursor.fetchone()
                    answers = eval(result[0]) if result and result[0] else {}
                    
                    if question_idx not in answers:
                        answers[question_idx] = []
                    
                    answer_id = int(answer_idx)
                    if answer_id in answers[question_idx]:
                        answers[question_idx].remove(answer_id)
                    else:
                        answers[question_idx].append(answer_id)
                    
                    cursor.execute('''
                        UPDATE user_progress SET answers = ? WHERE user_id = ? AND module_name = ?
                    ''', (str(answers), user_id, module_name))
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
        
        elif data.startswith("finish:"):
            _, module_name = data.split(":", 1)
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
