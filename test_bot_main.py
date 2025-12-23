import os
import time
import logging
import importlib.util
import telebot
from telebot import types

API_TOKEN = os.environ.get("API_TOKEN")
if not API_TOKEN:
    raise RuntimeError("API_TOKEN not set in environment")

bot = telebot.TeleBot(API_TOKEN)
BACKGROUND_IMAGE = "background.jpg.png"

SPECIALIZATIONS = {
    "🚨 ООУПДС": "OUPDS_test_bot.py",
    "📊 Исполнительное производство": "Ispolniteli_test_bot.py",
    "🎯 Дознание": "Doznanie_test_bot.py",
    "🧑‍🧑‍🧒 Алименты": "Aliment_test_bot.py",
    "⏳ Исполнительный розыск и реализация имущества": "Rozisk_test_bot.py",
    "📈 Организация профессиональной подготовки": "Prof_test_bot.py",
    "📡 Организация управления и контроля": "OKO_test_bot.py",
    "📱 Информатизация и информационная безопасность": "Informatizaciya_test_bot.py",
    "💻 Кадровая работа": "Kadri_test_bot.py",
    "🔒 Обеспечение собственной безопасности": "Bezopasnost_test_bot.py",
    "💼 Управленческая деятельность": "Starshie_test_bot.py"
}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

loaded_bots = {}
user_cooldown = {}

def load_bot_module(filename: str):
    """✅ ИСПРАВЛЕННАЯ ЛОГИКА: удаляем сломанные модули из кэша"""
    if filename in loaded_bots and loaded_bots[filename] is not None:
        return loaded_bots[filename]

    full_path = os.path.join(os.path.dirname(__file__), filename)
    logger.info(f"🔄 Попытка загрузки модуля: {filename} → {full_path}")
    
    if not os.path.exists(full_path):
        logger.error(f"❌ Файл бота НЕ НАЙДЕН: {full_path}")
        loaded_bots[filename] = None  # ✅ Помечаем как недоступный
        return None

    try:
        # ✅ УДАЛЯЕМ СТАРЫЙ МОДУЛЬ ИЗ КЭША ПРИ ПЕРЕЗАГРУЗКЕ
        if filename in loaded_bots:
            del loaded_bots[filename]
        
        spec = importlib.util.spec_from_file_location(filename, full_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # ✅ ПРОВЕРКА НАЛИЧИЯ ВСЕХ ТРЕБУЕМЫХ ФУНКЦИЙ
        required_functions = ['init_test_module', 'start_test', 'is_test_user', 'handle_message', 'handle_callback']
        missing = [f for f in required_functions if not hasattr(module, f)]
        
        if missing:
            raise RuntimeError(f"Отсутствуют обязательные функции: {missing}")
        
        # ✅ ИНИЦИАЛИЗАЦИЯ МОДУЛЯ
        module.init_test_module()
        
        loaded_bots[filename] = module
        logger.info(f"✅ ✅ Модуль ПОЛНОСТЬЮ загружен: {filename} ({len(required_functions)} функций)")
        return module
        
    except Exception as e:
        logger.error(f"❌ ❌ ОШИБКА загрузки {filename}: {e}")
        logger.error(f"   Полный traceback: {str(e)}")
        loaded_bots[filename] = None  # ✅ Помечаем как сломанный
        return None

def is_spam(user_id: int, cooldown: float) -> bool:
    now = time.time()
    last_time = user_cooldown.get(user_id, 0)
    if now - last_time < cooldown:
        return True
    user_cooldown[user_id] = now
    return False

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    if is_spam(user_id, cooldown=2.0):
        return

    keyboard = types.InlineKeyboardMarkup(row_width=1)
    for specialization, bot_file in SPECIALIZATIONS.items():
        keyboard.add(types.InlineKeyboardButton(specialization, callback_data=f"test:{bot_file}"))

    welcome_text = (
        "🎉 Добро пожаловать в систему тестов\n\n"
        "ФССП\n\n"
        "📋 Здесь вы сможете пройти профессиональный тест "
        "и узнать свой уровень подготовки.\n\n"
        "✅ Тесты разработаны в рамках специальной подготовки и содержат актуальные вопросы.\n\n"
        "🔁 Для повторного прохождения теста введите команду: /start\n\n"
        "🎯 <b>А сейчас: Выберите вашу специализацию ниже ⏬</b>"
    )

    if os.path.exists(BACKGROUND_IMAGE):
        try:
            with open(BACKGROUND_IMAGE, "rb") as photo:
                bot.send_photo(message.chat.id, photo, caption=welcome_text, parse_mode="HTML", reply_markup=keyboard)
            return
        except Exception as e:
            logger.error(f"Ошибка отправки фото: {e}")

    bot.send_message(message.chat.id, welcome_text, parse_mode="HTML", reply_markup=keyboard)

# ✅ ГЛАВНЫЙ ОБРАБОТЧИК СООБЩЕНИЙ (только НЕ команды)
@bot.message_handler(func=lambda message: message.text and not message.text.startswith('/') and message.text.strip())
def global_message_handler(message):
    user_id = message.from_user.id
    
    # ✅ ПРОВЕРКА ТЕСТОВЫХ МОДУЛЕЙ (только загруженных)
    for filename, module in list(loaded_bots.items()):
        if module is None:  # ✅ ПРОПУСКАЕМ СЛОМАННЫЕ МОДУЛИ
            continue
        try:
            if (hasattr(module, 'is_test_user') and 
                module.is_test_user(user_id) and 
                hasattr(module, 'handle_message')):
                if module.handle_message(message):
                    return
        except Exception as e:
            logger.error(f"❌ Ошибка в handle_message модуля {filename}: {e}")
            continue
    
    # ✅ НЕИЗВЕСТНОЕ СООБЩЕНИЕ
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🚀 Начать тест", callback_data="start_menu"))
    bot.send_message(message.chat.id, "🚀 Нажмите кнопку для начала теста", reply_markup=keyboard)

# ✅ ГЛАВНЫЙ CALLBACK ОБРАБОТЧИК
@bot.callback_query_handler(func=lambda call: True)
def global_callback_handler(call):
    user_id = call.from_user.id
    
    # ✅ КРИТИЧНО: ОТВЕТ НА ВСЕ CALLBACK
    bot.answer_callback_query(call.id)
    
    # ✅ ПРОВЕРКА ТЕСТОВЫХ МОДУЛЕЙ (только загруженных)
    for filename, module in list(loaded_bots.items()):
        if module is None:  # ✅ ПРОПУСКАЕМ СЛОМАННЫЕ
            continue
        try:
            if (hasattr(module, 'handle_callback') and 
                module.handle_callback(call)):
                return
        except Exception as e:
            logger.error(f"❌ Ошибка handle_callback в {filename}: {e}")
            continue
    
    # ✅ ОСНОВНАЯ ЛОГИКА МЕНЮ
    data = call.data or ""
    
    if data == "start_menu":
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        for specialization, bot_file in SPECIALIZATIONS.items():
            keyboard.add(types.InlineKeyboardButton(specialization, callback_data=f"test:{bot_file}"))
        welcome_text = "🎉 Добро пожаловать в систему тестов\n\nФССП\n\n📋 Выберите специализацию:"
        try:
            bot.edit_message_text(welcome_text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=keyboard)
        except:
            bot.send_message(call.message.chat.id, welcome_text, parse_mode="HTML", reply_markup=keyboard)
        return
    
    if data.startswith("test:"):
        bot_file = data.split("test:", 1)[1]
        logger.info(f"🚀 Запуск теста: {bot_file} для пользователя {user_id}")
        
        module = load_bot_module(bot_file)  # ✅ ПЕРЕЗАГРУЗИМ ПРИ НЕОБХОДИМОСТИ
        
        if not module:
            error_msg = f"❌ Модуль {bot_file} не загружен. Проверьте логи."
            logger.error(error_msg)
            try:
                bot.edit_message_text(error_msg, call.message.chat.id, call.message.message_id)
            except:
                bot.send_message(call.message.chat.id, error_msg)
            return
        
        if not hasattr(module, "start_test"):
            error_msg = f"❌ В модуле {bot_file} отсутствует функция start_test()"
            logger.error(error_msg)
            try:
                bot.edit_message_text(error_msg, call.message.chat.id, call.message.message_id)
            except:
                bot.send_message(call.message.chat.id, error_msg)
            return
        
        try:
            logger.info(f"✅ Запуск start_test() для {bot_file}")
            module.start_test(bot, call)
            logger.info(f"✅ Тест {bot_file} успешно запущен")
        except Exception as e:
            error_msg = f"❌ Ошибка запуска теста {bot_file}: {str(e)[:100]}"
            logger.error(error_msg)
            logger.error(f"Полная ошибка: {e}")
            try:
                bot.edit_message_text(error_msg, call.message.chat.id, call.message.message_id)
            except:
                bot.send_message(call.message.chat.id, error_msg)

if __name__ == "__main__":
    logger.info("🚀 Главный бот запущен...")
    logger.info(f"📁 Рабочая директория: {os.getcwd()}")
    logger.info(f"📋 Доступные модули: {list(SPECIALIZATIONS.values())}")
    
    # ✅ ПРОВЕРКА ФАЙЛОВ ПРИ СТАРТЕ
    for name, filename in SPECIALIZATIONS.items():
        full_path = os.path.join(os.path.dirname(__file__), filename)
        status = "✅" if os.path.exists(full_path) else "❌"
        logger.info(f"   {status} {name}: {filename}")
    
    bot.infinity_polling()
