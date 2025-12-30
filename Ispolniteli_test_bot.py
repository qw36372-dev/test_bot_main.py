# Ispolniteli_test_bot.py 30.12 14:25
import json
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from telebot import types
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import io

MODULE_NAME = "Ispolniteli"
QUESTIONS_FILE = f"{MODULE_NAME}_questions.json"
DB_PATH = "test_bot.db"
LEVELS = {
    "резерв": {"questions": 20, "time_minutes": 35},
    "базовый": {"questions": 30, "time_minutes": 25},
    "стандартный": {"questions": 40, "time_minutes": 20},
    "продвинутый": {"questions": 50, "time_minutes": 20}
}

def load_questions():
    if not Path(QUESTIONS_FILE).exists():
        return []
    try:
        with open(QUESTIONS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

QUESTIONS = load_questions()

def get_grade(score, total):
    percentage = (score / total) * 100
    if percentage >= 90: return "отлично", percentage
    elif percentage >= 75: return "хорошо", percentage
    elif percentage >= 60: return "удовлетворительно", percentage
    return "неудовлетворительно", percentage

def save_user_data(user_id, fio, position, department, db_path=DB_PATH):
    import threading
    lock = threading.Lock()
    with lock:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO users (user_id, fio, position, department) VALUES (?, ?, ?, ?)", 
                      (user_id, fio, position, department))
        conn.commit()
        conn.close()

def safe_edit_message(bot, chat_id, message_id, text, reply_markup=None):
    try:
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup)
    except:
        pass

def register_user(bot, user_id, chat_id, message_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📝 Ввести данные", callback_data="enter_data"))
    safe_edit_message(bot, chat_id, message_id, 
                     f"👤 Для начала теста **{MODULE_NAME}** введите свои данные:\n"
                     "Ф.И.О., Должность, Подразделение", 
                     reply_markup=markup)
    
    if not hasattr(bot, 'user_states'):
        setattr(bot, 'user_states', {})
    user_states = getattr(bot, 'user_states', {})
    user_states[user_id] = {'state': 'waiting_fio', 'chat_id': chat_id, 'message_id': message_id, 'module': MODULE_NAME}

def handle_module_callbacks(bot, call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    data = call.data
    
    if not hasattr(bot, 'user_states'):
        return
    user_states = getattr(bot, 'user_states', {})
    if user_id not in user_states:
        return
    
    state_data = user_states[user_id]
    
    if data == "enter_data":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("📝 Ввести данные")
        bot.send_message(chat_id, "Введите Ф.И.О., должность и подразделение одной строкой:", reply_markup=markup)
        state_data['waiting_for'] = 'user_data'
    
    elif data == "select_level":
        markup = types.InlineKeyboardMarkup(row_width=1)
        for level in LEVELS:
            btn = types.InlineKeyboardButton(level.title(), callback_data=f"start_{level}")
            markup.add(btn)
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_register"))
        safe_edit_message(bot, chat_id, message_id, "🎯 Выберите уровень сложности:", reply_markup=markup)
    
    elif data.startswith("start_"):
        level = data.replace("start_", "")
        start_test(bot, user_id, chat_id, message_id, level)
    
    elif data.startswith("answer_"):
        parts = data.split("_")
        if len(parts) == 3:
            q_index = int(parts[1])
            answer = int(parts[2])
            
            if state_data.get('state') == 'test_active' and 'user_answers' in state_data:
                if q_index not in state_data['user_answers']:
                    state_data['user_answers'][q_index] = []
                if answer not in state_data['user_answers'][q_index]:
                    state_data['user_answers'][q_index].append(answer)
                
                state_data['current_question'] += 1
                bot.answer_callback_query(call.id)
                show_question(bot, user_id, chat_id, message_id)
    
    elif data == "generate_cert":
        generate_certificate(bot, user_id, chat_id)
    
    elif data == "restart_test":
        markup = types.InlineKeyboardMarkup(row_width=1)
        for level in LEVELS:
            btn = types.InlineKeyboardButton(level.title(), callback_data=f"start_{level}")
            markup.add(btn)
        safe_edit_message(bot, chat_id, message_id, "🎯 Повторите тест. Выберите уровень:", reply_markup=markup)
    
    elif data == "show_answers":
        show_correct_answers(bot, user_id, chat_id, message_id)
    
    elif data == "back_register":
        register_user(bot, user_id, chat_id, message_id)
    
    elif data == "back_main":
        bot.send_message(chat_id, "/start")

def start_test(bot, user_id, chat_id, message_id, level):
    if not QUESTIONS:
        safe_edit_message(bot, chat_id, message_id, "❌ Библиотека вопросов недоступна.")
        return
    
    questions_count = LEVELS[level]["questions"]
    test_questions = random.sample(QUESTIONS, min(questions_count, len(QUESTIONS)))
    
    user_states = getattr(bot, 'user_states', {})
    user_states[user_id] = {
        'state': 'test_active',
        'module_name': MODULE_NAME,
        'test_questions': test_questions,
        'current_question': 0,
        'user_answers': {},
        'test_start_time': datetime.now(),
        'test_end_time': datetime.now() + timedelta(minutes=LEVELS[level]["time_minutes"]),
        'level': level,
        'chat_id': chat_id,
        'message_id': message_id
    }
    
    show_question(bot, user_id, chat_id, message_id)

def show_question(bot, user_id, chat_id, message_id):
    user_states = getattr(bot, 'user_states', {})
    if user_id not in user_states or user_states[user_id].get('state') != 'test_active':
        return
    
    test_data = user_states[user_id]
    current_q = test_data['current_question']
    
    if current_q >= len(test_data['test_questions']):
        finish_test(bot, user_id, chat_id, message_id)
        return
    
    if datetime.now() > test_data['test_end_time']:
        safe_edit_message(bot, chat_id, message_id, "⏰ Время вышло! Тест завершен.")
        finish_test(bot, user_id, chat_id, message_id)
        return
    
    question = test_data['test_questions'][current_q]
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for i, option in enumerate(question['options'], 1):
        callback_data = f"answer_{current_q}_{i}"
        btn = types.InlineKeyboardButton(f"{i}. {option}", callback_data=callback_data)
        markup.add(btn)
    
    markup.add(types.InlineKeyboardButton("🏁 Завершить тест", callback_data="finish_test"))
    
    time_left = test_data['test_end_time'] - datetime.now()
    time_str = str(time_left).split('.')[0]
    
    question_text = f"📝 Вопрос {current_q + 1}/{len(test_data['test_questions'])}\n\n⏰ Осталось: {time_str}\n\n{question['question']}"
    safe_edit_message(bot, chat_id, message_id, question_text, reply_markup=markup)

def finish_test(bot, user_id, chat_id, message_id):
    user_states = getattr(bot, 'user_states', {})
    if user_id not in user_states:
        return
    
    test_data = user_states[user_id]
    questions = test_data['test_questions']
    correct_answers = 0
    
    for i, q in enumerate(questions):
        correct = q['correct']
        user_answer = test_data['user_answers'].get(i, [])
        if set(user_answer) == set(correct):
            correct_answers += 1
    
    total = len(questions)
    grade, percentage = get_grade(correct_answers, total)
    test_time = str(datetime.now() - test_data['test_start_time']).split('.')[0]
    passed = 1 if percentage >= 60 else 0
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT fio, position, department FROM users WHERE user_id=?", (user_id,))
    user_info = cursor.fetchone()
    conn.close()
    
    fio = position = department = "Не указано"
    if user_info:
        fio, position, department = user_info
    
    result_text = (f"🏆 Результаты теста **{MODULE_NAME}**:\n\n"
                  f"👤 {fio}\n💼 {position}\n🏢 {department}\n"
                  f"📊 Уровень: {test_data['level'].title()}\n"
                  f"📈 Оценка: {grade}\n✅ Правильно: {correct_answers}/{total}\n"
                  f"📊 {percentage:.0f}%\n⏱️ {test_time}")
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📜 Сертификат", callback_data="generate_cert"))
    markup.add(types.InlineKeyboardButton("🔄 Повторить", callback_data="restart_test"))
    markup.add(types.InlineKeyboardButton("👁️ Ответы (60с)", callback_data="show_answers"))
    markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="back_main"))
    
    safe_edit_message(bot, chat_id, message_id, result_text, reply_markup=markup)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO test_stats (user_id, module_name, level, score, total_questions, percentage, test_time, passed) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (user_id, MODULE_NAME, test_data['level'], correct_answers, total, percentage, test_time, passed))
    conn.commit()
    conn.close()
    
    user_states[user_id] = {'state': 'test_finished'}

def show_correct_answers(bot, user_id, chat_id, message_id):
    user_states = getattr(bot, 'user_states', {})
    if user_id not in user_states or user_states[user_id].get('state') != 'test_finished':
        return
    
    test_data = user_states[user_id]
    answers_text = "✅ Правильные ответы:\n\n"
    for i, q in enumerate(test_data['test_questions']):
        correct = [str(idx+1) for idx in q['correct']]
        answers_text += f"Q{i+1}: {', '.join(correct)}\n"
    
    safe_edit_message(bot, chat_id, message_id, answers_text)
    # Авто-возврат через 60с можно добавить Thread

def generate_certificate(bot, user_id, chat_id):
    user_states = getattr(bot, 'user_states', {})
    if user_id not in user_states:
        bot.send_message(chat_id, "❌ Нет данных для сертификата.")
        return
    
    test_data = user_states[user_id]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT fio, position, department FROM users WHERE user_id=?", (user_id,))
    user_info = cursor.fetchone()
    conn.close()
    
    if not user_info:
        bot.send_message(chat_id, "❌ Данные пользователя не найдены.")
        return
        
    fio, position, department = user_info
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    p.setFont("Helvetica-Bold", 24)
    p.drawCentredText(width/2, height-100, f"СЕРТИФИКАТ {MODULE_NAME}")
    p.setFont("Helvetica", 16)
    p.drawCentredText(width/2, height-150, f"выдан {fio}")
    
    p.setFont("Helvetica", 12)
    y = height - 250
    fields = [
        f"Должность: {position}",
        f"Подразделение: {department}",
        f"Уровень: {test_data['level'].title()}",
        f"Оценка: {test_data.get('grade', 'N/A')}",
        f"Правильно: {test_data.get('correct_answers', 0)} из {len(test_data.get('test_questions', []))}"
    ]
    for field in fields:
        p.drawString(100, y, field)
        y -= 25
    
    p.showPage()
    p.save()
    buffer.seek(0)
    bot.send_document(chat_id, document=buffer, filename=f"{MODULE_NAME}_certificate.pdf")

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    user_id = message.from_user.id
    user_states = getattr(bot, 'user_states', {})
    
    if user_id not in user_states:
        return
    
    state_data = user_states[user_id]
    if state_data.get('waiting_for') == 'user_data':
        parts = message.text.split(',', 2)
        if len(parts) >= 3:
            fio, position, department = [p.strip() for p in parts[:3]]
            save_user_data(user_id, fio, position, department)
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🎯 Выбрать уровень", callback_data="select_level"))
            bot.send_message(message.chat.id, f"✅ Данные сохранены:\n👤 {fio}\n💼 {position}\n🏢 {department}\n\nВыберите уровень:", reply_markup=markup)
            state_data['state'] = 'data_entered'
        else:
            bot.reply_to(message, "Формат: ФИО, должность, подразделение")
