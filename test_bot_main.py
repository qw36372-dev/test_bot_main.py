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

SPECIALIZATIONS = {
    "Алименты": "Aliment_test_bot.py",
    "ООУПДС": "OUPDS_test_bot.py",
    "Исполнители": "Ispolniteli_test_bot.py",
    "Дознание": "Doznanie_test_bot.py",
    "Резерв": "Rezerv_test_bot.py",
    "Практика": "Praktika_test_bot.py",
    "УПК": "UPK_test_bot.py",
    "КоАП": "KoAP_test_bot.py",
    "Судьи": "Sudji_test_bot.py",
    "Адвокаты": "Advokaty_test_bot.py",
    "Прокуроры": "Prokurory_test_bot.py"
}

def safe_delete_message(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass

def load_bot_module(file_path):
    module_name = os.path.splitext(os.path.basename(file_path))[0]
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None:
        logger.error(f"Cannot load module spec for {file_path}")
        return None
    
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    if hasattr(module, 'questions') and module.questions:
        logger.info(f"Loaded module: {file_path} ({len(module.questions)} questions)")
        return module
    else:
        logger.error(f"Module {file_path} has no questions")
        return None

def load_all_modules():
    module_dir = os.path.dirname(__file__)
    for spec_name, filename in SPECIALIZATIONS.items():
        full_path = os.path.join(module_dir, filename)
        if os.path.exists(full_path):
            loaded_bots[filename] = load_bot_module(full_path)
        else:
            logger.warning(f"Module not found: {full_path}")
            loaded_bots[filename] = None

def show_main_menu(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    for spec_name in SPECIALIZATIONS.keys():
        markup.add(types.InlineKeyboardButton(spec_name, callback_data=spec_name))
    bot.send_message(user_id, "🎓 Выберите специализацию:", reply_markup=markup)

def handle_specialization(message, specialization_name):
    filename = SPECIALIZATIONS.get(specialization_name)
    if not filename or filename not in loaded_bots or not loaded_bots[filename]:
        bot.send_message(message.chat.id, f"Модуль {specialization_name} не загружен")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    status_text = "✓ Загружен" if filename in loaded_bots and loaded_bots[filename] else "✗ Ошибка"
    
    markup.add(
        types.InlineKeyboardButton(
            text="🚀 Запустить тест",
            callback_data=f"{specialization_name}_start"
        ),
        types.InlineKeyboardButton(
            text=f"🔄 Перезагрузить модуль ({status_text})",
            callback_data=f"reload_{specialization_name}"
        )
    )
    bot.send_message(message.chat.id, f"Специализация: {specialization_name}", reply_markup=markup)

@bot.message_handler(commands=['start'])
def start_command(message):
    safe_delete_message(message.chat.id, message.message_id)
    show_main_menu(message.chat.id)

@bot.message_handler(func=lambda message: True)
def global_message_handler(message):
    safe_delete_message(message.chat.id, message.message_id)

@bot.callback_query_handler(func=lambda call: True)
def universal_callback_handler(call):
    data = call.data
    
    if data.startswith('reload_'):
        spec_name = data[7:]
        filename = SPECIALIZATIONS.get(spec_name)
        if filename:
            module_dir = os.path.dirname(__file__)
            full_path = os.path.join(module_dir, filename)
            loaded_bots[filename] = load_bot_module(full_path)
            bot.answer_callback_query(call.id, f"Модуль {spec_name} перезагружен")
            safe_delete_message(call.message.chat.id, call.message.message_id)
            handle_specialization(call.message, spec_name)
        return True
    
    if call.data in SPECIALIZATIONS:
        safe_delete_message(call.message.chat.id, call.message.message_id)
        handle_specialization(call.message, call.data)
        return True
    
    # Обработка кнопок сложности и тестов из модулей
    for filename, module in loaded_bots.items():
        if module:
            try:
                if module.handle_callback(call):
                    return True
            except Exception as e:
                logger.error(f"Callback error in {filename}: {e}")
                continue
    
    bot.answer_callback_query(call.id, "Неизвестная кнопка")
    return False

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    load_all_modules()
    
    logger.info("Available modules:")
    for name, filename in SPECIALIZATIONS.items():
        status = "✓ LOADED" if filename in loaded_bots and loaded_bots[filename] else "MISSING"
        logger.info(f"  {status} {name}: {filename}")
    
    try:
        bot.infinity_polling(none_stop=True, interval=1, timeout=30)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
