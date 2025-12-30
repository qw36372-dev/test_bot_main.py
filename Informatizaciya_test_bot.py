# Aliment_test_bot.py 29.12 16:14
import os
import sqlite3
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from telebot import types
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleProducer
import io

QUESTIONS_FILE = "Informatizaciya_questions.json"
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
    with open(QUESTIONS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

QUESTIONS = load_questions()

def get_grade(score, total):
    percentage = (score / total) * 100
    if percentage >= 90:
        return "отлично", percentage
    elif percentage >= 75:
        return "хорошо", percentage
    elif percentage >= 60:
        return "удовлетворительно", percentage
    else:
        return "неудовлетворительно", percentage

def save_user_data(user_id, fio, position, department):
    from test_bot_main import db_lock, DB_PATH
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO users (user_id, fio, position, department) VALUES (?, ?, ?, ?)",
            (user_id, fio, position, department)
        )
        conn.commit()
        conn.close()

def start_test(bot, user_id, chat_id, message_id, level):
    user_states = getattr(bot, 'user_states', {})
    
    if not QUESTIONS:
        safe_edit_message(bot, chat_id, message_id, "❌ Библиотека вопросов недоступна.")
        return
    
    questions_count = LEVELS[level]["questions"]
    test_questions = random.sample(QUESTIONS, min(questions_count, len(QUESTIONS)))
    
    user_states[user_id] = {
        'state': 'test_active',
        'module_name': 'Aliment_test_bot',
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
    if user_id not in user_states or user_states[user_id]['state'] != 'test_active':
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
    
    time_left = test_data['test_end_time'] - datetime.now()
    time_str = str(time_left).split('.')[0]
    
    question_text = (
        f"📝 Вопрос {current_q + 1}/{len(test_data['test_questions'])}\n\n"
        f"⏰ Осталось времени: {time_str}\n\n"
        f"{question['question']}"
    )
    
    safe_edit_message(bot, chat_id, message_id, question_text, reply_markup=markup)

def finish_test(bot, user_id, chat_id, message_id):
    user_states = getattr(bot, 'user_states', {})
    if user_id not in user_states:
        return
    
    test_data = user_states[user_id]
    questions = test_data['test_questions']
    correct_answers = 0
    
    for i, q in enumerate(questions):
        correct = q['correct'].split(', ')
        user_answer = test_data['user_answers'].get(i, [])
        if set(user_answer) == set(correct):
            correct_answers += 1
    
    total = len(questions)
    grade, percentage = get_grade(correct_answers, total)
    test_time = str(datetime.now() - test_data['test_start_time']).split('.')[0]
    passed = 1 if percentage >= 60 else 0
    
    from test_bot_main import db_lock, DB_PATH
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT fio, position, department FROM users WHERE user_id=?",
            (user_id,)
        )
        user_info = cursor.fetchone()
        conn.close()
    
    if user_info:
        fio, position, department = user_info
    else:
        fio = position = department = "Не указано"
    
    result_text = (
        f"🏆 Результаты теста:\n\n"
        f"👤 Ф.И.О.: {fio}\n"
        f"💼 Должность: {position}\n"
        f"🏢 Подразделение: {department}\n"
        f"📊 Уровень сложности: {test_data['level'].title()}\n"
        f"📈 Оценка: {grade}\n"
        f"✅ Правильных ответов: {correct_answers} из {total}\n"
        f"📊 Процент: {percentage:.0f}%\n"
        f"⏱️ Время тестирования: {test_time}"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📜 Получить сертификат", callback_data="generate_cert"))
    markup.add(types.InlineKeyboardButton("🔄 Повторить тест", callback_data="restart_test"))
    markup.add(types.InlineKeyboardButton("👁️ Показать ответы (60с)", callback_data="show_answers"))
    markup.add(types.InlineKeyboardButton("🏠 В главное меню", callback_data="back_main"))
    
    safe_edit_message(bot, chat_id, message_id, result_text, reply_markup=markup)
    
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO test_stats (user_id, module_name, level, score, total_questions, percentage, test_time, passed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, 'Aliment_test_bot', test_data['level'], correct_answers, total, percentage, test_time, passed)
        )
        conn.commit()
        conn.close()
    
    user_states[user_id] = {'state': 'test_finished', 'results': locals()}

def generate_certificate(bot, user_id, chat_id):
    user_states = getattr(bot, 'user_states', {})
    if user_id not in user_states or 'results' not in user_states[user_id]:
        bot.send_message(chat_id, "❌ Нет данных для сертификата.")
        return
    
    results = user_states[user_id]['results']
    fio = results['fio']
    position = results['position']
    department = results['department']
    level = results['test_data']['level'].title()
    grade = results['grade']
    correct = results['correct_answers']
    total = results['total']
    percentage = f"{results['percentage']:.0f}%"
    test_time = results['test_time']
    
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    p.setFont("Helvetica-Bold", 24)
    p.drawCentredText(width/2, height-100, "СЕРТИФИКАТ")
    p.setFont("Helvetica", 16)
    p.drawCentredText(width/2, height-150, f"выдан {fio}")
    
    p.setFont("Helvetica", 12)
    y = height - 250
    fields = [
        f"Должность: {position}",
        f"Подразделение: {department}",
        f"Уровень сложности: {level}",
        f"Оценка: {grade}",
        f"Правильных ответов: {correct} из {total}",
        f"Процент правильных ответов: {percentage}",
        f"Время тестирования: {test_time}"
    ]
    
    for field in fields:
        p.drawString(100, y, field)
        y -= 25
    
    p.showPage()
    p.save()
    buffer.seek(0)
    
    bot.send_document(chat_id, document=buffer, filename="certificate.pdf")

def safe_edit_message(bot, chat_id, message_id, text, reply_markup=None):
    try:
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup)
    except Exception:
        pass

def register_user(bot, user_id, chat_id, message_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📝 Ввести данные", callback_data="enter_data"))
    safe_edit_message(bot, chat_id, message_id, 
                     "👤 Для начала тестирования введите свои данные:\n"
                     "Ф.И.О., Должность, Подразделение", 
                     reply_markup=markup)
    setattr(bot, 'user_states', getattr(bot, 'user_states', {}))
    user_states = getattr(bot, 'user_states', {})
    user_states[user_id] = {'state': 'waiting_fio', 'chat_id': chat_id, 'message_id': message_id}

def handle_callback(bot, call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    data = call.data
    
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
        for level in LEVELS.keys():
            btn = types.InlineKeyboardButton(level.title(), callback_data=f"start_{level}")
            markup.add(btn)
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_register"))
        safe_edit_message(bot, chat_id, message_id, "🎯 Выберите уровень сложности:", reply_markup=markup)
    
    elif data.startswith("start_"):
        level = data.replace("start_", "")
        start_test(bot, user_id, chat_id, message_id, level)
    
    elif data.startswith("answer_"):
        parts = data.split("_")
        q_index = int(parts[1])
        answer = int(parts[2])
        
        if state_data['state'] == 'test_active':
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
        user_states[user_id] = {'state': 'select_level'}
        markup = types.InlineKeyboardMarkup(row_width=1)
        for level in LEVELS.keys():
            btn = types.InlineKeyboardButton(level.title(), callback_data=f"start_{level}")
            markup.add(btn)
        safe_edit_message(bot, chat_id, message_id, "🎯 Повторите тест. Выберите уровень:", reply_markup=markup)
    
    elif data == "show_answers":
        # Показать правильные ответы на 60 секунд
        pass  # Implementation omitted for brevity
    
    elif data == "back_register":
        register_user(bot, user_id, chat_id, message_id)
    
    elif data == "back_main":
        from test_bot_main import start_command
        start_command(types.Message())

@bot.message_handler(func=lambda message: True)
def handle_text(bot, message):
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
            bot.send_message(
                message.chat.id,
                f"✅ Данные сохранены:\n"
                f"👤 {fio}\n"
                f"💼 {position}\n"
                f"🏢 {department}\n\n"
                "Выберите действие:",
                reply_markup=markup
            )
            state_data['state'] = 'data_entered'
            bot.send_message(message.chat.id, "/start", parse_mode='Markdown')
        else:
            bot.reply_to(message, "Пожалуйста, введите данные в формате: ФИО, должность, подразделение")
