import random
import time
import json
import os
import logging
from telebot import types

logging.basicConfig(level=logging.INFO)

class TestBot:
    def __init__(self, bot_instance, user_data, chat_id):
        self.bot = bot_instance
        self.user_data = user_data
        self.chat_id = chat_id
        self.current_question = 0
        self.user_answers = {}
        
        # Поиск JSON в той же папке
        questions_file = "Aliment_test_bot_questions.json"
        if not os.path.exists(questions_file):
            self.questions = [{"text": "Файл вопросов не найден! Проверьте наличие Aliment_test_bot_questions.json", "options": ["Ошибка"], "correct": 0}]
            logging.error(f"Questions file not found: {questions_file}")
        else:
            try:
                with open(questions_file, 'r', encoding='utf-8') as f:
                    all_questions = json.load(f)
                
                difficulty = self.user_data.get('difficulty', 'easy')
                self.questions = all_questions.get(difficulty, all_questions.get('easy', []))
                
                if not self.questions:
                    self.questions = [{"text": f"Вопросы для уровня '{difficulty}' не найдены! Доступные: {list(all_questions.keys())}", "options": ["Ошибка"], "correct": 0}]
                    logging.warning(f"No questions for difficulty: {difficulty}")
            except json.JSONDecodeError as e:
                self.questions = [{"text": f"Ошибка в JSON файле вопросов: {str(e)}", "options": ["Ошибка"], "correct": 0}]
                logging.error(f"JSON decode error: {e}")
        
        self.total_questions = len(self.questions)
        logging.info(f"Loaded {self.total_questions} questions for {difficulty}")

    def send_question(self, chat_id, message_id):
        if self.current_question >= self.total_questions:
            self.finish_test(chat_id, message_id)
            return
            
        q = self.questions[self.current_question]
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        buttons = []
        for i, opt in enumerate(q["options"]):
            selected = "✅ " if self.user_answers.get(self.current_question) == i else ""
            buttons.append(types.InlineKeyboardButton(
                f"{selected}{opt}", callback_data=f"ans_{self.current_question}_{i}"
            ))
        buttons.append(types.InlineKeyboardButton("❌ Очистить выбор", callback_data=f"clear_{self.current_question}"))
        if self.current_question < self.total_questions - 1:
            buttons.append(types.InlineKeyboardButton("➡️ Далее", callback_data="next_q"))
        buttons.append(types.InlineKeyboardButton("🏁 Завершить тест", callback_data="finish_test"))
        markup.add(*buttons)
        
        text = f"Вопрос {self.current_question + 1}/{self.total_questions}\n\n{q['text']}"
        
        try:
            self.bot.edit_message_text(chat_id=chat_id, message_id=message_id, 
                                     text=text, reply_markup=markup, parse_mode=None)
        except Exception as e:
            logging.error(f"Edit message error: {e}")
            self.bot.send_message(chat_id, text, reply_markup=markup)

    def handle_callback(self, call):
        data = call.data
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        
        if data.startswith("ans_"):
            _, q_idx, ans_idx = data.split("_")
            self.current_question = int(q_idx)
            self.user_answers[int(q_idx)] = int(ans_idx)
            self.bot.answer_callback_query(call.id, "Выбрано")
            self.send_question(chat_id, message_id)
            
        elif data.startswith("clear_"):
            _, q_idx = data.split("_")
            self.current_question = int(q_idx)
            self.user_answers.pop(self.current_question, None)
            self.bot.answer_callback_query(call.id, "Выбор отменен")
            self.send_question(chat_id, message_id)
            
        elif data == "next_q":
            if self.current_question < self.total_questions - 1:
                self.current_question += 1
            self.bot.answer_callback_query(call.id, "Следующий вопрос")
            self.send_question(chat_id, message_id)
            
        elif data == "finish_test":
            self.finish_test(chat_id, message_id)
            self.bot.answer_callback_query(call.id, "Тест завершен")

    def finish_test(self, chat_id, message_id):
        score = sum(1 for i, ans in self.user_answers.items() 
                   if i < len(self.questions) and ans == self.questions[i]["correct"])
        time_taken = time.time() - self.user_data['start_time']
        percentage = (score / self.total_questions * 100) if self.total_questions > 0 else 0
        
        # Сохранение данных в user_data для сертификата
        self.user_data['score'] = score
        self.user_data['total_questions'] = self.total_questions
        
        # Сохранение в БД
        try:
            conn = sqlite3.connect('users.db', check_same_thread=False)
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO users (user_id, fio, position, department) VALUES (?, ?, ?, ?)",
                     (chat_id, self.user_data['fio'], self.user_data['position'], self.user_data['department']))
            c.execute("INSERT INTO results (user_id, specialization, difficulty, score, time_taken) VALUES (?, ?, ?, ?, ?)",
                     (chat_id, self.user_data['specialization'], self.user_data['difficulty'], score, time_taken))
            conn.commit()
            conn.close()
            logging.info(f"Test results saved for user {chat_id}: {score}/{self.total_questions}")
        except Exception as e:
            logging.error(f"DB save error: {e}")
        
        # Статистика пользователя
        try:
            conn = sqlite3.connect('users.db', check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT COUNT(*), AVG(score), AVG(time_taken) FROM results WHERE user_id=?", (chat_id,))
            stats = c.fetchone()
            total_tests = stats[0] if stats and stats[0] > 0 else 0
            avg_score_raw = stats[1] if stats and stats[1] else 0
            avg_score = (avg_score_raw / 10 * 100) if avg_score_raw else 0  # Нормализация под 10 вопросов
            avg_time = stats[2] if stats and stats[2] else 0
            conn.close()
        except:
            total_tests = avg_score = avg_time = 0
        
        text = (f"✅ Тест завершен!\n\n"
                f"📊 Результат: **{score}/{self.total_questions} ({percentage:.1f}%)**\n"
                f"⏱️ Время: **{time_taken:.0f}с**\n\n"
                f"👤 **{self.user_data['fio']}**\n"
                f"💼 **{self.user_data['position']}**\n"
                f"🏢 **{self.user_data['department']}**\n\n"
                f"📈 **Статистика:**\n"
                f"• Всего тестов: {total_tests}\n"
                f"• Средний балл: {avg_score:.1f}%\n"
                f"• Среднее время: {avg_time:.0f}с")
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("📜 Сертификат", callback_data="certificate"))
        markup.add(types.InlineKeyboardButton("🔄 Новый тест", callback_data="new_test"))
        markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="start_test"))
        
        try:
            self.bot.edit_message_text(chat_id=chat_id, message_id=message_id, 
                                     text=text, reply_markup=markup, parse_mode='Markdown')
        except Exception as e:
            logging.error(f"Finish edit error: {e}")
            self.bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')
