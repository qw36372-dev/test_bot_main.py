import sqlite3
import json
import threading
import time
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
import os
import random
from questions_library import QuestionsLibrary
from telebot import types

ql = None
conn = None
cursor = None
bot = None
user_last_msg = {}
active_timers = {}
user_states = {}
current_test_users = set()
db_lock = threading.Lock()
DIFFICULTIES = {
    'резерв': {'questions': 20, 'time': 35*60, 'name': 'Резерв'},
    'базовый': {'questions': 30, 'time': 25*60, 'name': 'Базовый'},
    'стандартный': {'questions': 40, 'time': 20*60, 'name': 'Стандартный'},
    'продвинутый': {'questions': 50, 'time': 20*60, 'name': 'Продвинутый'}
}

def init_test_module():
    global ql, conn, cursor
    try:
        db_name = f"{os.path.splitext(__file__)[0]}.db"
        ql = QuestionsLibrary(f"{os.path.splitext(__file__)[0]}_questions.json")
        conn = sqlite3.connect(db_name, check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            position TEXT,
            department TEXT,
            first_start INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS active_tests (
            user_id INTEGER PRIMARY KEY,
            difficulty TEXT,
            questions TEXT,
            answers TEXT DEFAULT '[]',
            current_question INTEGER DEFAULT 0,
            start_time REAL,
            time_limit INTEGER,
            message_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS stats (
            user_id INTEGER,
            difficulty TEXT,
            attempts INTEGER DEFAULT 0,
            successful INTEGER DEFAULT 0,
            best_score REAL DEFAULT 0,
            PRIMARY KEY (user_id, difficulty)
        );
        ''')
        conn.commit()
        print(f"✅ Модуль {os.path.basename(__file__)} инициализирован (БД: {db_name})")
    except Exception as e:
        print(f"❌ Ошибка инициализации {__file__}: {e}")

def rate_limit_check(user_id):
    now = time.time()
    if user_id in user_last_msg and now - user_last_msg[user_id] < 1:
        return False
    user_last_msg[user_id] = now
    return True

def get_grade(percent):
    if percent >= 90: return 'отлично'
    elif percent >= 75: return 'хорошо'
    elif percent >= 60: return 'удовлетворительно'
    return 'неудовлетворительно'

def start_timer(user_id, time_limit, stop_event):
    start_time = time.time()
    while not stop_event.is_set():
        elapsed = time.time() - start_time
        time_left = max(0, time_limit - elapsed)
        if time_left <= 0:
            finish_test(user_id, timeout=True)
            break
        time.sleep(1)

def finish_test(user_id, timeout=False):
    global bot
    if bot is None:
        print("BOT НЕ ИНИЦИАЛИЗИРОВАН")
        return
        
    print(f"Завершение теста для {user_id}")
    
    if user_id in active_timers:
        active_timers[user_id].set()
        del active_timers[user_id]
    
    if user_id not in current_test_users:
        print(f"Пользователь {user_id} не в current_test_users")
        return
    
    try:
        with db_lock:
            cursor.execute("SELECT * FROM active_tests WHERE user_id=?", (user_id,))
            test_data = cursor.fetchone()
            if not test_data:
                print(f"Нет данных теста для {user_id}")
                return
            
            questions = json.loads(test_data[2])
            user_answers = json.loads(test_data[3] or '[]')
            
            score = 0
            for i, q in enumerate(questions):
                user_answer = user_answers[i] if i < len(user_answers) else []
                if set(user_answer) == set(q['correct']):
                    score += 1
            
            total_questions = len(questions)
            percent = (score / total_questions) * 100
            difficulty = test_data[1]
            grade = get_grade(percent)
            
            cursor.execute("INSERT OR IGNORE INTO stats (user_id, difficulty, attempts) VALUES (?, ?, 0)", (user_id, difficulty))
            
            sql_update = """UPDATE stats SET 
                attempts = attempts + 1, 
                successful = successful + CASE WHEN ? >= 0.6 * ? THEN 1 ELSE 0 END, 
                best_score = CASE WHEN ? > best_score THEN ? ELSE best_score END 
                WHERE user_id = ? AND difficulty = ?"""
            cursor.execute(sql_update, (score, total_questions, percent, percent, user_id, difficulty))
            
            cursor.execute("DELETE FROM active_tests WHERE user_id=?", (user_id,))
            conn.commit()
        
        current_test_users.discard(user_id)
        user_last_msg.pop(user_id, None)
        user_states.pop(user_id, None)
        
        cursor.execute("SELECT full_name, position, department FROM users WHERE user_id=?", (user_id,))
        user_data = cursor.fetchone()
        if not user_data:
            user_data = ('Не указано', 'Не указано', 'Не указано')
        
        elapsed_time = int(time.time() - test_data[6])
        minutes, seconds = divmod(elapsed_time, 60)
        
        result_text = f"""РЕЗУЛЬТАТЫ ТЕСТА
Ф.И.О.: {user_data[0]}
Должность: {user_data[1]}
Подразделение: {user_data[2]}
Уровень: {DIFFICULTIES[difficulty]['name']}
Оценка: {grade}
Правильно: {score} из {total_questions}
Процент: {percent:.0f}%
Время: {minutes:02d}:{seconds:02d}"""
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(types.InlineKeyboardButton("Ответы", callback_data=f"show_answers_{user_id}"))
        markup.add(types.InlineKeyboardButton("Сертификат", callback_data=f"cert_{user_id}"))
        markup.add(types.InlineKeyboardButton("Повторить", callback_data="repeat_test"))
        markup.add(types.InlineKeyboardButton("Статистика", callback_data="show_stats"))
        markup.add(types.InlineKeyboardButton("Меню", callback_data="start_menu"))
        
        bot.send_message(user_id, result_text, reply_markup=markup)
        
    except Exception as e:
        print(f"finish_test {user_id}: {e}")

def generate_certificate(user_id):
    global bot
    if bot is None:
        return
    
    try:
        with db_lock:
            cursor.execute("""
                SELECT u.full_name, u.position, u.department, s.difficulty, s.best_score 
                FROM users u JOIN stats s ON u.user_id = s.user_id 
                WHERE u.user_id = ? ORDER BY s.best_score DESC LIMIT 1
            """, (user_id,))
            data = cursor.fetchone()
        
        if not 
            bot.send_message(user_id, "❌ Нет данных для сертификата")
            return
        
        filename = f"cert_{user_id}_{int(time.time())}.pdf"
        c = canvas.Canvas(filename, pagesize=A4)
        width, height = A4
        
        c.setFont("Helvetica-Bold", 28)
        c.drawCentredText(width/2, height-5*cm, "СЕРТИФИКАТ")
        c.setFont("Helvetica-Bold", 18)
        c.drawCentredText(width/2, height-8*cm, "прохождение тестирования")
        
        c.setFont("Helvetica", 14)
        y = height - 12*cm
        info = [
            f"Ф.И.О.: {data[0] or 'Не указано'}",
            f"Должность: {data[1] or 'Не указано'}",
            f"Подразделение: {data[2] or 'Не указано'}",
            f"Уровень: {DIFFICULTIES[data[3]]['name']}",
            f"Результат: {data[4]:.0f}%",
            f"Дата: {datetime.now().strftime('%d.%m.%Y')}"
        ]
        
        for line in info:
            c.drawCentredText(width/2, y, line)
            y -= 1.2*cm
        
        c.save()
        
        try:
            with open(filename, 'rb') as f:
                bot.send_document(user_id, f, caption="📄 Сертификат")
        except Exception as e:
            bot.send_message(user_id, f"❌ Ошибка PDF: {e}")
        finally:
            if os.path.exists(filename):
                os.remove(filename)
    except Exception as e:
        print(f"❌ generate_certificate {user_id}: {e}")

def start_test(bot_instance, call):
    global bot
    bot = bot_instance
    user_id = call.from_user.id
    
    if not ql:
        init_test_module()
    
    current_test_users.add(user_id)
    
    with db_lock:
        cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        cursor.execute("SELECT first_start FROM users WHERE user_id=?", (user_id,))
        result = cursor.fetchone()
        
        if result and result[0] == 0:
            markup = types.InlineKeyboardMarkup(row_width=2)
            for diff, info in DIFFICULTIES.items():
                markup.add(types.InlineKeyboardButton(
                    f"{info['name']} ({info['questions']}в, {info['time']//60}м)",
                    callback_data=f"test_diff_{diff}"
                ))
            bot.edit_message_text("🎯 Выберите сложность:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        else:
            user_states[user_id] = 'waiting_name'
            bot.send_message(user_id, "👋 Введите Ф.И.О.:")
            bot.send_message(user_id, "⚠️ Время ограничено!")

def handle_test_text(message):
    pass

def start_quiz(user_id, difficulty):
    config = DIFFICULTIES[difficulty]
    questions = ql.get_random_questions(config['questions'])
    
    with db_lock:
        cursor.execute("INSERT OR REPLACE INTO active_tests (user_id, difficulty, questions, start_time, time_limit, current_question, answers) VALUES (?, ?, ?, ?, ?, 0, '[]')", 
                       (user_id, difficulty, json.dumps(questions), time.time(), config['time']))
        conn.commit()
    
    stop_event = threading.Event()
    active_timers[user_id] = stop_event
    threading.Thread(target=start_timer, args=(user_id, config['time'], stop_event), daemon=True).start()
    show_next_question(user_id, 0)

def show_next_question(user_id, question_index):
    global bot
    if bot is None:
        return
    
    with db_lock:
        cursor.execute("SELECT questions, answers FROM active_tests WHERE user_id=?", (user_id,))
        result = cursor.fetchone()
        if not result:
            return
        
        questions = json.loads(result[0])
        if question_index >= len(questions):
            finish_test(user_id)
            return
        
        answers = json.loads(result[1] or '[]')
        selected = answers[question_index] if question_index < len(answers) else []
        q = questions[question_index]
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        for i, option in enumerate(q['options']):
            status = "✅" if i in selected else "○"
            markup.add(types.InlineKeyboardButton(
                f"{status} {i+1}. {option}", 
                callback_data=f"answer_{question_index}_{i}"
            ))
        
        if selected:
            markup.add(types.InlineKeyboardButton("➡️ ДАЛЕЕ", callback_data=f"next_{question_index}"))
        
        question_text = f"⏰ Время...\n📝 {question_index+1}/{len(questions)}\n\n{q['question']}\nВыбрано: {len(selected)}"
        
        cursor.execute("SELECT message_id FROM active_tests WHERE user_id=?", (user_id,))
        msg_result = cursor.fetchone()
        
        try:
            if msg_result and msg_result[0]:
                bot.edit_message_text(question_text, user_id, msg_result[0], reply_markup=markup)
            else:
                msg = bot.send_message(user_id, question_text, reply_markup=markup)
                cursor.execute("UPDATE active_tests SET message_id=? WHERE user_id=?", (msg.message_id, user_id))
                conn.commit()
        except:
            msg = bot.send_message(user_id, question_text, reply_markup=markup)
            cursor.execute("UPDATE active_tests SET message_id=? WHERE user_id=?", (msg.message_id, user_id))
            conn.commit()
        
        cursor.execute("UPDATE active_tests SET current_question=? WHERE user_id=?", (question_index, user_id))
        conn.commit()

def handle_answer(call):
    data = call.data.split('_')
    question_idx = int(data[1])
    answer_idx = int(data[2])
    user_id = call.from_user.id
    
    with db_lock:
        cursor.execute("SELECT answers FROM active_tests WHERE user_id=?", (user_id,))
        result = cursor.fetchone()
        answers = json.loads(result[0] or '[]')
        
        while len(answers) <= question_idx:
            answers.append([])
        
        if answer_idx not in answers[question_idx]:
            answers[question_idx].append(answer_idx)
        
        cursor.execute("UPDATE active_tests SET answers=? WHERE user_id=?", (json.dumps(answers), user_id))
        conn.commit()
    
    selected = [idx+1 for idx in answers[question_idx]]
    bot.answer_callback_query(call.id, f"✅ Выбрано: {selected}")
    
    show_next_question(user_id, question_idx)

def show_user_stats(user_id):
    global bot
    if bot is None:
        return
    
    with db_lock:
        cursor.execute("SELECT difficulty, attempts, successful, best_score FROM stats WHERE user_id=?", (user_id,))
        stats = cursor.fetchall()
    
    if not stats:
        bot.send_message(user_id, "📊 Статистика пуста")
        return
    
    text = "📊 Статистика:\n\n"
    for diff, attempts, success, score in stats:
        rate = f"{success}/{attempts}" if attempts else "0/0"
        text += f"• {DIFFICULTIES[diff]['name']}: {rate} ({score:.0f}%)\n"
    
    bot.send_message(user_id, text)

def show_correct_answers(user_id):
    global bot
    if bot is None:
        return
    
    with db_lock:
        cursor.execute("SELECT questions, answers FROM active_tests WHERE user_id=?", (user_id,))
        result = cursor.fetchone()
    
    if not result:
        bot.send_message(user_id, "❌ Нет теста")
        return
    
    questions = json.loads(result[0])
    answers = json.loads(result[1] or '[]')
    
    text = "📋 ПРАВИЛЬНЫЕ ОТВЕТЫ:\n\n"
    for i, q in enumerate(questions):
        user_ans = answers[i] if i < len(answers) else []
        correct = [idx+1 for idx in q['correct']]
        status = "✅" if set(user_ans) == set(q['correct']) else "❌"
        text += f"{status} Вопрос {i+1}: {q['question']}\nПравильно: {', '.join(map(str, correct))}\n\n"
    
    for i in range(0, len(text), 4000):
        bot.send_message(user_id, text[i:i+4000])

def is_test_user(user_id):
    return user_id in current_test_users

def handle_message(message):
    return handle_test_text(message)

def handle_callback(call):
    user_id = call.from_user.id
    
    if user_id not in current_test_users:
        return False
    
    data = call.data
    
    try:
        if data.startswith('next_'):
            question_idx = int(data.split('_')[1])
            show_next_question(user_id, question_idx + 1)
            return True
        
        if data.startswith('test_diff_'):
            difficulty = data.replace('test_diff_', '')
            if difficulty in DIFFICULTIES:
                start_quiz(user_id, difficulty)
            return True
        
        elif data.startswith('answer_'):
            handle_answer(call)
            return True
        
        elif data.startswith('show_answers_'):
            show_correct_answers(user_id)
            return True
        
        elif data.startswith('cert_'):
            generate_certificate(user_id)
            return True
        
        elif data == 'repeat_test':
            markup = types.InlineKeyboardMarkup(row_width=2)
            for diff, info in DIFFICULTIES.items():
                markup.add(types.InlineKeyboardButton(
                    f"{info['name']} ({info['questions']}в)",
                    callback_data=f"test_diff_{diff}"
                ))
            bot.send_message(user_id, "🎯 Сложность:", reply_markup=markup)
            return True
        
        elif data == 'show_stats':
            show_user_stats(user_id)
            return True
        
        elif data == 'start_menu':
            current_test_users.discard(user_id)
            return False
            
    except Exception as e:
        print(f"❌ Callback: {e}")
    
    return False
