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
        spec = importlib.util.spec_from_file_location(filename[:-3], filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, 'init_test_module'):
            module.init_test_module()
        logger.info(f"Loaded module: {filename} ({getattr(module, 'ql', 'N/A').get_questions_count() if hasattr(module, 'ql') and hasattr(getattr(module, 'ql', None), 'get_questions_count') else 'N/A'} questions)")
        return module
    except Exception as e:
        logger.error(f"Failed to load {filename}: {e}")
        return None

def reload_modules():
    global loaded_bots
    logger.info("Reloading modules...")
    loaded_bots.clear()
    for name, filename in SPECIALIZATIONS.items():
        full_path = os.path.join(os.path.dirname(__file__), filename)
        if os.path.exists(full_path):
            loaded_bots[filename] = load_bot_module(full_path)
        else:
            loaded_bots[filename] = None
            logger.warning(f"Missing file: {filename}")

def show_main_menu(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton("ООУПДС")
    btn2 = types.KeyboardButton("Исполнители")
    btn3 = types.KeyboardButton("Дознание")
    btn4 = types.KeyboardButton("Алименты")
    btn5 = types.KeyboardButton("Розыск")
    btn6 = types.KeyboardButton("ОПП")
    btn7 = types.KeyboardButton("ОКО")
    btn8 = types.KeyboardButton("Информатизация")
    btn9 = types.KeyboardButton("Кадры")
    btn10 = types.KeyboardButton("ОСБ")
    btn11 = types.KeyboardButton("Управление")
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7, btn8, btn9, btn10, btn11)
    bot.send_message(message.chat.id, "Выберите специализацию:", reply_markup=markup)

@bot.message_handler(commands=['start'])
def start_handler(message):
    show_main_menu(message)

@bot.message_handler(func=lambda message: True)
def global_message_handler(message):
    text = message.text.strip()
    for name, filename in SPECIALIZATIONS.items():
        if text in [name, f"ООУПДС {name}", f"Исполнители {name}", f"Дознание {name}", f"Алименты {name}", f"Розыск {name}", name, f"ОПП {name}", f"ОКО {name}", f"Информатизация {name}",f"Кадры {name}", f"ОСБ {name}", f"Управление {name}"]:
            handle_specialization(message, name)
            return
    for filename, module in loaded_bots.items():
        if module and hasattr(module, 'handle_message') and module.handle_message(message):
            return
    bot.reply_to(message, "Нажмите кнопку специализации или /start")

@bot.callback_query_handler(func=lambda call: True)
def global_callback_handler(call):
    for filename, module in loaded_bots.items():
        try:
            if module and hasattr(module, 'handle_callback') and module.handle_callback(call):
                bot.answer_callback_query(call.id)
                return
        except Exception as e:
            logger.error(f"Callback error in {filename}: {e}")
            continue
    bot.answer_callback_query(call.id, "Неизвестная кнопка")

def handle_specialization(message, specialization_name):
    filename = SPECIALIZATIONS.get(specialization_name)
    if not filename or filename not in loaded_bots or not loaded_bots[filename]:
        bot.reply_to(message, f"Модуль {specialization_name} не загружен. Проверьте логи.")
        return
    try:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Запустить тест", callback_data=specialization_name))
        markup.add(types.InlineKeyboardButton("Перезагрузить модуль", callback_data=f"reload_{specialization_name}"))
        bot.reply_to(message, f"Специализация: {specialization_name}", reply_markup=markup)
    except Exception as e:
        logger.error(f"Specialization error {specialization_name}: {e}")
        bot.reply_to(message, "Ошибка запуска специализации")

@bot.callback_query_handler(func=lambda call: call.data in SPECIALIZATIONS or call.data.startswith('reload_'))
def specialization_handler(call):
    data = call.data
    if data.startswith('reload_'):
        spec_name = data[7:]
        filename = SPECIALIZATIONS.get(spec_name)
        if filename:
            loaded_bots[filename] = load_bot_module(os.path.join(os.path.dirname(__file__), filename))
            bot.answer_callback_query(call.id, f"Модуль {spec_name} перезагружен")
        return
    filename = SPECIALIZATIONS.get(data)
    if filename and filename in loaded_bots and loaded_bots[filename]:
        try:
            loaded_bots[filename].start_test(bot, call)
            bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"Start test error {filename}: {e}")
            bot.answer_callback_query(call.id, "Ошибка запуска теста", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "Модуль не загружен. Проверьте логи", show_alert=True)

def signal_handler(sig, frame):
    logger.info("Shutting down gracefully...")
    for timer in active_timers.values():
        timer.cancel()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == "__main__":
    logger.info("Starting test bot...")
    reload_modules()
    logger.info("Available modules:")
    for name, filename in SPECIALIZATIONS.items():
        full_path = os.path.join(os.path.dirname(__file__), filename)
        status = "✅ OK" if filename in loaded_bots and loaded_bots[filename] else "Недоступен"
        logger.info(f"  {status} {name}: {filename}")
    try:
        bot.infinity_polling(none_stop=True, interval=1, timeout=30)
    except KeyboardInterrupt:
        logger.info("Тест временно недоступен")
    except Exception as e:
        logger.error(f"Ошибка запуска теста: {e}")
