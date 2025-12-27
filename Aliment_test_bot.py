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
current_test_users = set()
db_lock = threading.Lock()
active_timers = {}
user_states = {}

DIFFICULTIES = {
    'rezerv': {'questions': 20, 'time': 35*60, 'name': 'Резерв'},
    'bazovyy': {'questions': 25, 'time': 40*60, 'name': 'Базовый'},
    'standart': {'questions': 30, 'time': 45*60, 'name': 'Стандартный'},
    'expert': {'questions': 50, 'time': 90*60, 'name': 'Эксперт'}
}

def safe_delete_message(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass

def init_test_module(bot_instance):
    global ql, conn, cursor, bot
    bot = bot_instance
    try:
        db_name = f"{os.path.splitext(__file__)[0]}.db"
        ql = QuestionsLibrary(f"{os.path.splitext(__file__)[0]}_questions.json")
        conn = sqlite3.connect(db_name, check_same_thread=False)
        cursor = conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, 
                full_name TEXT, 
                position TEXT, 
                department TEXT, 
                first_start INTEGER DEFAULT 1
            ); 
            CREATE TABLE IF NOT EXISTS active_tests (
                user_id INTEGER PRIMARY KEY, 
                questions TEXT, 
                answers TEXT, 
                start_time REAL, 
                difficulty TEXT, 
                current_question INTEGER DEFAULT 0, 
                message_id INTEGER, 
                test_time REAL DEFAULT 0
            ); 
            CREATE TABLE IF NOT EXISTS stats (
                user_id INTEGER, 
                difficulty TEXT, 
                attempts INTEGER DEFAULT 0, 
                successful INTEGER DEFAULT 0, 
                best_score REAL DEFAULT 0, 
                avg_time REAL DEFAULT 0, 
                PRIMARY KEY (user_id, difficulty)
            );
        """)
        conn.commit()
        print(f"Aliment module OK: {ql.get_questions_count()} questions")
    except Exception as e:
        print(f"Aliment init error: {e}")
        raise

def start_test(user_id, difficulty):
    current_test_users.add(user_id)
    with db_lock:
        cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        cursor.execute("SELECT first_start FROM users WHERE user_id=?", (user_id,))
        result = cursor.fetchone()
        if result and result[0] == 0:
            show_difficulty_menu(user_id)
        else:
            bot.send_message(user_id, "Введите ФИО:")
            user_states[user_id] = 'full_name'
    conn.commit()

def show_difficulty_menu(user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for diff, info in DIFFICULTIES.items():
        markup.add(types.InlineKeyboardButton(
            f"{info['name']} ({info['questions']}в, {info['time']//60}мин)", 
            callback_data=f"{diff}_start"
        ))
    bot.send_message(user_id, "Выберите сложность:", reply_markup=markup)

def handle_test_text(message):
    user_id = message.from_user.id
    if user_id not in current_test_users:
        return False
    state = user_states.get(user_id)
    if state == 'full_name':
        cursor.execute("UPDATE users SET full_name=? WHERE user_id=?", (message.text, user_id))
        user_states[user_id] = 'position'
        bot.send_message(user_id, "Должность:")
    elif state == 'position':
        cursor.execute("UPDATE users SET position=? WHERE user_id=?", (message.text, user_id))
        user_states[user_id] = 'department'
        bot.send_message(user_id, "Подразделение:")
    elif state == 'department':
        cursor.execute("UPDATE users SET department=?, first_start=0 WHERE user_id=?", (message.text, user_id))
        conn.commit()
        show_difficulty_menu(user_id)
        del user_states[user_id]
    return True

def get_remaining_time(user_id):
    if user_id not in active_timers:
        return 0
    elapsed = time.time() - active_timers[user_id].start_time
    return max(0, active_timers[user_id].interval - elapsed)

def show_next_question(user_id, question_index):
    with db_lock:
        cursor.execute("SELECT questions FROM active_tests WHERE user_id=?", (user_id,))
        result = cursor.fetchone()
        if not result:
            return
        questions = json.loads(result[0])
        if question_index >= len(questions):
            cursor.execute("SELECT difficulty FROM active_tests WHERE user_id=?", (user_id,))
            if cursor.fetchone():
                finish_test(user_id)
                conn.commit()
            return
        
        q = questions[question_index]
        cursor.execute("SELECT answers FROM active_tests WHERE user_id=?", (user_id,))
        result = cursor.fetchone()
        answers = json.loads(result[0] if result else '[]')
        while len(answers) <= question_index:
            answers.append([])
        selected = [idx+1 for idx in answers[question_index]]
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        for i, option in enumerate(q['options']):
            status = "X" if i in answers[question_index] else str(i+1)
            markup.add(types.InlineKeyboardButton(f"{status} {option}", callback_data=f"answer_{question_index}_{i}"))
        
        if selected or question_index == len(questions) - 1:
            btn_text = "Завершить тест" if question_index == len(questions) - 1 else "Далее"
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"next_{question_index}"))
        
        remain_time = get_remaining_time(user_id)
        minutes_left = max(0, int(remain_time / 60))
        seconds_left = int(remain_time % 60)
        question_text = f"{minutes_left}:{seconds_left:02d} {question_index+1}/{len(questions)}\n\n{q['question']}\nВыбрано: {len(selected)}"
        
        cursor.execute("SELECT message_id FROM active_tests WHERE user_id=?", (user_id,))
        msg_result = cursor.fetchone()
        try:
            if msg_result and msg_result[0]:
                bot.edit_message_text(question_text, user_id, msg_result[0], reply_markup=markup)
            else:
                msg = bot.send_message(user_id, question_text, reply_markup=markup)
                cursor.execute("UPDATE active_tests SET message_id=? WHERE user_id=?", (msg.message_id, user_id))
        except:
            msg = bot.send_message(user_id, question_text, reply_markup=markup)
            cursor.execute("UPDATE active_tests SET message_id=? WHERE user_id=?", (msg.message_id, user_id))
        
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
        answers = json.loads(result[0] if result else '[]')
        while len(answers) <= question_idx:
            answers.append([])
        if answer_idx not in answers[question_idx]:
            answers[question_idx].append(answer_idx)
        cursor.execute("UPDATE active_tests SET answers=? WHERE user_id=?", (json.dumps(answers), user_id))
        conn.commit()
    selected = [idx+1 for idx in answers[question_idx]]
    bot.answer_callback_query(call.id, f"Выбрано: {selected}")
    show_next_question(user_id, question_idx)

def finish_test(user_id, timeout=False):
    print(f"DEBUG: finish_test({user_id}, timeout={timeout}) START")
    
    if user_id in active_timers:
        active_timers[user_id].cancel()
        del active_timers[user_id]
        print(f"DEBUG: timer cancelled for {user_id}")
    
    if user_id not in current_test_users:
        print(f"DEBUG: user {user_id} not in current_test_users")
        return
    
    try:
        with db_lock:
            cursor.execute("SELECT questions, answers, start_time, difficulty, message_id FROM active_tests WHERE user_id=?", (user_id,))
            result = cursor.fetchone()
            print(f"DEBUG: DB result: {result}")
            
            if not result:
                bot.send_message(user_id, "Нет данных теста")
                print(f"DEBUG: No test data for {user_id}")
                return
                
            questions = json.loads(result[0])
            user_answers = json.loads(result[1] or '[]')
            start_time = result[2]
            difficulty = result[3]
            msg_id = result[4]
            
            print(f"DEBUG: questions={len(questions)}, answers={len(user_answers)}")
            
            test_time = time.time() - start_time
            score = 0
            for i, q in enumerate(questions):
                if len(user_answers) > i and set(user_answers[i]) == set(q['correct']):
                    score += 1
            
            total_questions = len(questions)
            percent = (score / total_questions) * 100
            
            print(f"DEBUG: score={score}/{total_questions} ({percent:.1f}%)")
            
            cursor.execute("INSERT OR IGNORE INTO stats (user_id, difficulty, attempts) VALUES (?, ?, 0)", (user_id, difficulty))
            cursor.execute("""
                UPDATE stats SET 
                attempts = attempts + 1, 
                successful = successful + CASE WHEN ? >= 60 THEN 1 ELSE 0 END, 
                best_score = CASE WHEN ? > best_score OR best_score IS NULL THEN ? ELSE best_score END, 
                avg_time = CASE WHEN avg_time = 0 THEN ? ELSE (avg_time * (attempts) + ?) / (attempts + 1) END 
                WHERE user_id = ? AND difficulty = ?
            """, (percent, percent, percent, test_time, test_time, user_id, difficulty))
            
            cursor.execute("DELETE FROM active_tests WHERE user_id=?", (user_id,))
            conn.commit()
            
            if msg_id:
                safe_delete_message(user_id, msg_id)
        
        result_text = f"Результат: {score}/{total_questions} ({percent:.1f}%) Время: {int(test_time//60)}:{int(test_time%60):02d} {DIFFICULTIES[difficulty]['name']}"
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("Сертификат", callback_data="certificate"))
        markup.add(types.InlineKeyboardButton("Статистика", callback_data="show_stats"))
        markup.add(types.InlineKeyboardButton("Главное меню", callback_data="start_menu"))
        
        bot.send_message(user_id, result_text, reply_markup=markup)
        print(f"DEBUG: finish_test({user_id}) SUCCESS")
        current_test_users.discard(user_id)
        
    except Exception as e:
        print(f"CRITICAL ERROR in finish_test({user_id}): {e}")
        bot.send_message(user_id, f"Ошибка завершения: {str(e)}")

def generate_certificate(user_id):
    with db_lock:
        cursor.execute("""
            SELECT u.full_name, u.position, u.department, s.best_score, s.difficulty, s.avg_time 
            FROM users u LEFT JOIN stats s ON u.user_id = s.user_id 
            WHERE u.user_id = ? ORDER BY s.best_score DESC LIMIT 1
        """, (user_id,))
        data = cursor.fetchone()
    if not 
        bot.send_message(user_id, "Нет данных для сертификата")
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
        f"ФИО: {data[0] or 'Не указано'}",
        f"Должность: {data[1] or 'Не указано'}",
        f"Подразделение: {data[2] or 'Не указано'}",
        f"Лучший результат: {data[3]:.0f}%" if data[3] else "Лучший результат: Не указан",
        f"Сложность: {DIFFICULTIES[data[4]]['name']}" if data[4] else "Сложность: Не указана",
        f"Среднее время: {int(data[5]//60)} мин" if data[5] else "Среднее время: Не указано"
    ]
    for line in info:
        c.drawCentredText(width/2, y, line)
        y -= 1.2*cm
    c.save()
    try:
        with open(filename, 'rb') as f:
            bot.send_document(user_id, f, caption="Ваш сертификат")
        os.remove(filename)
    except:
        bot.send_message(user_id, "Ошибка отправки сертификата")

def show_user_stats(user_id):
    with db_lock:
        cursor.execute("SELECT difficulty, attempts, successful, best_score, avg_time FROM stats WHERE user_id=?", (user_id,))
        stats = cursor.fetchall()
    if not stats:
        bot.send_message(user_id, "Статистика пуста")
        return
    text = "Ваша статистика:\n\n"
    for diff, attempts, success, score, avg_time in stats:
        rate = f"{success}/{attempts}" if attempts else "0/0"
        time_min = int(avg_time//60) if avg_time else 0
        text += f"{DIFFICULTIES[diff]['name']}: {rate} ({score:.0f}%, {time_min}мин)\n"
    bot.send_message(user_id, text)

def handle_test_callback(call):
    data = call.data
    user_id = call.from_user.id
    print(f"DEBUG: handle_test_callback({user_id}): '{data}'")
    
    if user_id not in current_test_users and not data.endswith('_start'):
        print(f"DEBUG: user {user_id} not in test")
        return False
        
    try:
        if data.endswith('_start'):
            diff = data.split('_')[0]
            if diff not in DIFFICULTIES:
                return False
            info = DIFFICULTIES[diff]
            questions = ql.get_random_questions(info['questions'])
            start_time = time.time()
            with db_lock:
                cursor.execute("""
                    INSERT OR REPLACE INTO active_tests 
                    (user_id, questions, answers, start_time, difficulty, current_question) 
                    VALUES (?, ?, '[]', ?, ?, 0)
                """, (user_id, json.dumps(questions), start_time, diff))
                conn.commit()
            timer = threading.Timer(info['time'], lambda: finish_test(user_id, True))
            timer.start_time = start_time
            active_timers[user_id] = timer
            timer.start()
            show_next_question(user_id, 0)
            return True
        
        elif data.startswith('answer_'):
            print(f"DEBUG: answer clicked")
            handle_answer(call)
            return True
            
        elif data.startswith('next_'):
            question_idx = int(data.split('_')[1])
            print(f"DEBUG: next_ {question_idx} -> {question_idx+1}")
            show_next_question(user_id, question_idx + 1)
            return True
            
        elif data == 'certificate':
            print(f"DEBUG: certificate")
            generate_certificate(user_id)
            return True
        elif data == 'show_stats':
            print(f"DEBUG: show_stats")
            show_user_stats(user_id)
            return True
        elif data == 'start_menu':
            print(f"DEBUG: start_menu")
            finish_test(user_id)
            current_test_users.discard(user_id)
            return False
    except Exception as e:
        print(f"CRITICAL: handle_test_callback({user_id}, '{data}'): {e}")
        bot.answer_callback_query(call.id, f"Ошибка: {str(e)[:50]}")
        return False

def handle_message(message):
    return handle_test_text(message)

def handle_callback(call):
    return handle_test_callback(call)

def is_test_user(user_id):
    return user_id in current_test_users
