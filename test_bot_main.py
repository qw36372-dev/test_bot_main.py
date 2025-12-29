import os
import time
import logging
import importlib.util
import telebot
from telebot import types
import signal
import sys
import sqlite3

logging.basicConfig(level=logging.INFO)
API_TOKEN = os.environ.get("API_TOKEN")
if not API_TOKEN:
    raise ValueError("API_TOKEN not found")

bot = telebot.TeleBot(API_TOKEN)
user_data = {}
test_modules = {}

class States:
    START = 0
    REG_FIO = 1
    REG_POSITION = 2
    REG_DEPARTMENT = 3
    SPECIALIZATION = 4
    DIFFICULTY = 5
    TESTING = 6

def load_test_modules():
    for filename in os.listdir('.'):
        if filename.endswith("_test_bot.py"):
            module_name = filename[:-3]
            spec = importlib.util.spec_from_file_location(module_name, filename)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            test_modules[module_name] = module
            logging.info(f"Loaded {module_name}")

def init_db():
    conn = sqlite3.connect('users.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, fio TEXT, position TEXT, department TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS results 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
                  specialization TEXT, difficulty TEXT, score INTEGER, time_taken REAL)''')
    conn.commit()
    conn.close()

def safe_edit(chat_id, message_id, text, reply_markup=None):
    try:
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, 
                            text=text, reply_markup=reply_markup, parse_mode=None)
        return True
    except Exception as e:
        if "message is not modified" in str(e).lower() or "message to edit not found" in str(e).lower():
            return True
        logging.error(f"Edit error: {e}")
        return False

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    user_data[user_id] = {'state': States.START, 'message_id': message.message_id}
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Начать тест", callback_data="start_test"))
    bot.send_message(message.chat.id, "Добро пожаловать! Нажмите кнопку для начала.", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    if user_id not in user_
        user_data[user_id] = {'state': States.START}
    data = user_data[user_id]
    data['message_id'] = message_id
    
    if call.data.startswith(('ans_', 'clear_', 'next_q')):
        if data.get('test_instance'):
            data['test_instance'].handle_callback(call)
        bot.answer_callback_query(call.id)
        return
        
    if call.data == "start_test":
        data['state'] = States.SPECIALIZATION
        markup = types.InlineKeyboardMarkup(row_width=1)
        for mod_name in test_modules:
            markup.add(types.InlineKeyboardButton(mod_name.replace('_test_bot', '').title(), 
                                                callback_data=f"spec_{mod_name}"))
        safe_edit(chat_id, message_id, "Выберите специализацию:", markup)
        
    elif call.data.startswith("spec_"):
        data['specialization'] = call.data[5:]
        data['state'] = States.DIFFICULTY
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("Легкий", callback_data="diff_easy"))
        markup.add(types.InlineKeyboardButton("Средний", callback_data="diff_medium"))
        markup.add(types.InlineKeyboardButton("Сложный", callback_data="diff_hard"))
        safe_edit(chat_id, message_id, "Выберите уровень сложности:", markup)
        
    elif call.data.startswith("diff_"):
        data['difficulty'] = call.data[5:]
        data['state'] = States.REG_FIO
        safe_edit(chat_id, message_id, "Введите ФИО:", types.InlineKeyboardMarkup())
        bot.answer_callback_query(call.id)
        bot.register_next_step_handler_by_chat_id(chat_id, process_fio)
        
    elif call.data == "finish_test":
        if data.get('test_instance'):
            data['test_instance'].finish_test(chat_id, message_id)
        safe_edit(chat_id, message_id, "Тест завершен! Сертификат отправлен.")
        
    elif call.data == "certificate":
        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import A4
            import io
            
            buffer = io.BytesIO()
            p = canvas.Canvas(buffer, pagesize=A4)
            width, height = A4
            
            fio = data['fio']
            position = data['position']
            department = data['department']
            score = data.get('score', 0)
            total = data.get('total_questions', 10)
            
            p.setFont("Helvetica-Bold", 20)
            p.drawCentredText(width/2, height-100, "СЕРТИФИКАТ")
            p.setFont("Helvetica", 14)
            p.drawCentredText(width/2, height-150, fio)
            p.drawCentredText(width/2, height-180, f"{position}, {department}")
            p.drawCentredText(width/2, height-220, f"Балл: {score}/{total}")
            p.showPage()
            p.save()
            
            buffer.seek(0)
            bot.send_document(chat_id, document=buffer, 
                            filename=f"certificate_{chat_id}.pdf")
            safe_edit(chat_id, message_id, "✅ Сертификат отправлен!")
        except Exception as e:
            logging.error(f"Certificate error: {e}")
            safe_edit(chat_id, message_id, "❌ Ошибка генерации сертификата")
    
    elif call.data == "new_test":
        del user_data[user_id]
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Начать тест", callback_data="start_test"))
        safe_edit(chat_id, message_id, "Добро пожаловать! Нажмите кнопку для начала.", markup)
        
    bot.answer_callback_query(call.id)

def process_fio(message):
    user_id = message.from_user.id
    if user_id in user_
        user_data[user_id]['fio'] = message.text.strip()
        user_data[user_id]['state'] = States.REG_POSITION
        bot.send_message(message.chat.id, "Введите должность:")

def process_position(message):
    user_id = message.from_user.id
    if user_id in user_
        user_data[user_id]['position'] = message.text.strip()
        user_data[user_id]['state'] = States.REG_DEPARTMENT
        bot.send_message(message.chat.id, "Введите подразделение:")

def process_department(message):
    user_id = message.from_user.id
    if user_id in user_
        user_data[user_id]['department'] = message.text.strip()
        user_data[user_id]['state'] = States.TESTING
        start_test(user_id, message.chat.id)

def start_test(user_id, chat_id):
    data = user_data[user_id]
    spec_module = test_modules[data['specialization']]
    test_instance = spec_module.TestBot(bot, data, chat_id)
    data['test_instance'] = test_instance
    data['start_time'] = time.time()
    test_instance.send_question(chat_id, data['message_id'])

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    init_db()
    load_test_modules()
    logging.info("Bot started")
    bot.infinity_polling(skip_pending=True)
