import os
import time
import logging
import importlib.util
import telebot
from telebot import types
import signal
import sys

API_TOKEN = os.environ.get("API_TOKEN")
if not API_TOKEN:
    raise RuntimeError("API_TOKEN not set in environment")

bot = telebot.TeleBot(API_TOKEN)
loaded_bots = {}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

BACKGROUND_IMAGE = "background.jpg.png"

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

def load_bot_module(filename):
    try:
        full_path = os.path.join(os.path.dirname(__file__), filename)
        spec = importlib.util.spec_from_file_location(filename[:-3], full_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, 'init_test_module'):
            module.init_test_module()
        logger.info(f"Loaded module: {filename}")
        return module
    except Exception as e:
        logger.error(f"Failed to load {filename}: {e}")
        return None

def reload_modules():
    global loaded_bots
    logger.info("Reloading modules...")
    loaded_bots.clear()
    for name, filename in SPECIALIZATIONS.items():
        loaded_bots[filename] = load_bot_module(filename)

def safe_delete_message(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass

def show_main_menu(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        ["ООУПДС", "Исполнители"],
        ["Дознание", "Алименты"], 
        ["Розыск", "ОПП"],
        ["ОКО", "Информатизация"],
        ["Кадры", "ОСБ"],
        ["Управление"]
    ]
    for row in buttons:
        markup.row(*[types.KeyboardButton(name) for name in row])
    bot.send_message(message.chat.id, "Главное меню. Выберите специализацию:", reply_markup=markup)
    safe_delete_message(message.chat.id, message.message_id)

@bot.message_handler(commands=['start'])
def start_handler(message):
    show_main_menu(message)

@bot.message_handler(func=lambda message: True)
def global_message_handler(message):
    text = message.text.strip() if message.text else ""
    if text in SPECIALIZATIONS:
        handle_specialization(message, text)
        return
    
    for filename, module in loaded_bots.items():
        if module and hasattr(module, 'handle_message') and module.handle_message(message):
            return
    show_main_menu(message)

def handle_specialization(message, specialization_name):
    filename = SPECIALIZATIONS.get(specialization_name)
    if not filename or filename not in loaded_bots or not loaded_bots[filename]:
        bot.send_message(message.chat.id, f"Модуль {specialization_name} не загружен")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🚀 Запустить тест", callback_data=specialization_name),
        types.InlineKeyboardButton("🔄 Перезагрузить модуль", callback_data=f"reload_{specialization_name}")
    )
    bot.send_message(message.chat.id, f"Специализация: {specialization_name}", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def universal_callback_handler(call):
    data = call.data
    
    if data.startswith('reload_'):
        spec_name = data[7:]
        filename = SPECIALIZATIONS.get(spec_name)
        if filename:
            loaded_bots[filename] = load_bot_module(filename)
            bot.answer_callback_query(call.id, f"Модуль {spec_name} перезагружен")
            safe_delete_message(call.message.chat.id, call.message.message_id)
            handle_specialization(call.message, spec_name)
        return True
    
    if call.data in SPECIALIZATIONS:
        safe_delete_message(call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "Выберите сложность")
        
        filename = SPECIALIZATIONS[call.data]
        module = loaded_bots.get(filename)
        if module and hasattr(module, 'DIFFICULTIES'):
            difficulties = module.DIFFICULTIES
        else:
            difficulties = {
                'rezerv': {'questions': 20, 'time': 35*60, 'name': 'Резерв'},
                'baza': {'questions': 30, 'time': 30*60, 'name': 'Базовый'},
                'standard': {'questions': 40, 'time': 20*60, 'name': 'Стандартный'},
                'expert': {'questions': 50, 'time': 20*60, 'name': 'Эксперт'}
            }
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        for diff_key, info in difficulties.items():
            markup.add(types.InlineKeyboardButton(
                f"{info['name']} ({info['questions']}в, {info['time']//60}мин)",
                callback_data=f"{call.data}_{diff_key}_start"
            ))
        bot.send_message(call.from_user.id, "Выберите сложность:", reply_markup=markup)
        return True
    
    # ✅: Обработка запуска теста {spec}_{difficulty}_start
    if '_' in data and data.endswith('_start'):
        parts = data.rsplit('_', 1)
        spec_name = parts[0]
        difficulty = parts[1][:-6]  # убираем "_start"
        
        filename = SPECIALIZATIONS.get(spec_name)
        module = loaded_bots.get(filename)
        if module and hasattr(module, 'start_test'):
            safe_delete_message(call.message.chat.id, call.message.message_id)
            module.start_test(call.from_user.id, difficulty)
            bot.answer_callback_query(call.id, f"Тест {difficulty} запущен")
            return True
    
    # Модули (вопросы/ответы)
    for filename, module in loaded_bots.items():
        try:
            if module and hasattr(module, 'handle_callback') and module.handle_callback(call):
                bot.answer_callback_query(call.id)
                return True
        except Exception as e:
            logger.error(f"Callback error in {filename}: {e}")
            continue
    
    bot.answer_callback_query(call.id, "Неизвестная кнопка")
        bot.infinity_polling(none_stop=True, interval=1, timeout=30)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
