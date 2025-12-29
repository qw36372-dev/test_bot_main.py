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
        self.start_time = time.time()
        
        # Загрузка вопросов из JSON
        self.questions = self._load_questions()
        self.total_questions = len(self.questions)
        logging.info(f"TestBot initialized: {self.total_questions} questions for {self.user_data.get('difficulty', 'easy')}")

    def _load_questions(self):
        """Загрузка и валидация вопросов из JSON"""
        questions_file = "Aliment_test_bot_questions.json"
        
        if not os.path.exists(questions_file):
            logging.error(f"Questions file not found: {questions_file}")
            return [{"text": "❌ Файл вопросов не найден! Проверьте Aliment_test_bot_questions.json", 
                    "options": ["Создать файл вопросов"], "correct": 0}]
        
        try:
            with open(questions_file, 'r', encoding='utf-8') as f:
                all_questions = json.load(f)
            
            difficulty = self.user_data.get('difficulty', 'easy').lower()
            questions = all_questions.get(difficulty, all_questions.get('easy', []))
            
            if not questions:
                available_levels = list(all_questions.keys())
                logging.warning(f"No questions for '{difficulty}'. Available: {available_levels}")
                return [{"text": f"❌ Вопросы для '{difficulty}' не найдены! Доступно: {available_levels}", 
                        "options": ["easy", "medium", "hard"], "correct": 0}]
            
            # Валидация вопросов
            validated_questions = []
            for q in questions:
                if (isinstance(q.get('text'), str) and 
                    isinstance(q.get('options'), list) and 
                    isinstance(q.get('correct'), int) and
                    q['correct'] < len(q['options'])):
                    validated_questions.append(q)
                else:
                    logging.warning(f"Invalid question format: {q}")
            
            logging.info(f"Loaded {len(validated_questions)} valid questions for {difficulty}")
            return validated_questions if validated_questions else [{"text": "❌ Нет валидных вопросов!", "options": ["Ошибка"], "correct": 0}]
            
        except json.JSONDecodeError as e:
            logging.error(f"JSON decode error in {questions_file}: {e}")
            return [{"text": f"❌ Ошибка JSON: {str(e)[:100]}...", "options": ["Ошибка"], "correct": 0}]
        except Exception as e:
            logging.error(f"Error loading questions: {e}")
            return [{"text": f"❌ Ошибка загрузки: {str(e)}", "options": ["Ошибка"], "correct": 0}]

    def send_question(self, chat_id, message_id):
        """Отправка текущего вопроса"""
        if self.current_question >= self.total_questions:
            self.finish_test(chat_id, message_id)
            return
            
        q = self.questions[self.current_question]
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        # Кнопки ответов
        buttons = []
        for i, option in enumerate(q["options"]):
            selected = "✅ " if self.user_answers.get(self.current_question) == i else ""
            buttons.append(types.InlineKeyboardButton(
                f"{selected}{option}", 
                callback_data=f"ans_{self.current_question}_{i}"
            ))
        
        # Кнопки навигации
        buttons.append(types.InlineKeyboardButton("❌ Очистить выбор", 
                                                callback_data=f"clear_{self.current_question}"))
        
        if self.current_question < self.total_questions - 1:
            buttons.append(types.InlineKeyboardButton("➡️ Далее", callback_data="next_q"))
        buttons.append(types.InlineKeyboardButton("🏁 Завершить тест", callback_data="finish_test"))
        
        markup.add(*buttons)
        text = f"**Вопрос {self.current_question + 1}/{self.total_questions}**\n\n{q['text']}"
        
        try:
            self.bot.edit_message_text(
                chat_id=chat_id, 
                message_id=message_id, 
                text=text, 
                reply_markup=markup, 
                parse_mode='Markdown'
            )
        except Exception as e:
            logging.error(f"Edit message error: {e}")
            self.bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

    def handle_callback(self, call):
        """Обработка callback от кнопок"""
        data = call.data
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        
        try:
            if data.startswith("ans_"):
                _, q_idx_str, ans_idx_str = data.split("_")
                q_idx = int(q_idx_str)
                ans_idx = int(ans_idx_str)
                
                self.current_question = q_idx
                self.user_answers[q_idx] = ans_idx
                self.bot.answer_callback_query(call.id, "✅ Выбрано")
                
            elif data.startswith("clear_"):
                _, q_idx_str = data.split("_")
                q_idx = int(q_idx_str)
                self.current_question = q_idx
                self.user_answers.pop(q_idx, None)
                self.bot.answer_callback_query(call.id, "❌ Выбор отменен")
                
            elif data == "next_q":
                if self.current_question < self.total_questions - 1:
                    self.current_question += 1
                self.bot.answer_callback_query(call.id, "➡️ Следующий вопрос")
                
            elif data == "finish_test":
                self.finish_test(chat_id, message_id)
                self.bot.answer_callback_query(call.id, "🏁 Тест завершен")
                return
                
            self.send_question(chat_id, message_id)
            
        except Exception as e:
            logging.error(f"Callback handler error: {e}")
            self.bot.answer_callback_query(call.id, "❌ Ошибка")

    def finish_test(self, chat_id, message_id):
        """Завершение теста и подсчет результатов"""
        score = 0
        for i, ans in self.user_answers.items():
            if i < len(self.questions) and ans == self.questions[i]["correct"]:
                score += 1
                
        time_taken = time.time() - self.user_data.get('start_time', time.time())
        percentage = (score / self.total_questions * 100) if self.total_questions > 0 else 0
        
        # Сохранение в user_data для сертификата
        self.user_data['score'] = score
        self.user_data['total_questions'] = self.total_questions
        self.user_data['percentage'] = percentage
        
        # Сохранение в БД
        try:
            conn = sqlite3.connect('users.db', check_same_thread=False)
            c = conn.cursor()
            c.execute("""INSERT OR REPLACE INTO users 
                        (user_id, fio, position, department) 
                        VALUES (?, ?, ?, ?)""",
                     (chat_id, self.user_data['fio'], self.user_data['position'], self.user_data['department']))
            
            c.execute("""INSERT INTO results 
                        (user_id, specialization, difficulty, score, time_taken) 
                        VALUES (?, ?, ?, ?, ?)""",
                     (chat_id, self.user_data['specialization'], self.user_data['difficulty'], 
                      score, time_taken))
            conn.commit()
            conn.close()
            logging.info(f"Results saved: {chat_id} - {score}/{self.total_questions}")
        except Exception as e:
            logging.error(f"DB save error: {e}")
        
        # Статистика пользователя
        stats = self._get_user_stats(chat_id)
        
        text = (f"**✅ Тест успешно завершен!**\n\n"
                f"**📊 Результат текущего теста:**\n"
                f"• Балл: `{score}/{self.total_questions}`\n"
                f"• Процент: `{percentage:.1f}%`\n"
                f"• Время: `{time_taken:.0f}с`\n\n"
                f"**👤 Исполнитель:**\n"
                f"• `{self.user_data['fio']}`\n"
                f"• `{self.user_data['position']}`\n"
                f"• `{self.user_data['department']}`\n\n"
                f"**📈 Общая статистика:**\n"
                f"• Тестов пройдено: `{stats['total_tests']}`\n"
                f"• Средний балл: `{stats['avg_score']:.1f}%`\n"
                f"• Среднее время: `{stats['avg_time']:.0f}с`")
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("📜 Получить сертификат", callback_data="certificate"))
        markup.add(types.InlineKeyboardButton("🔄 Пройти новый тест", callback_data="new_test"))
        markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="start_test"))
        
        try:
            self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=markup,
                parse_mode='Markdown'
            )
        except Exception as e:
            logging.error(f"Finish message error: {e}")
            self.bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

    def _get_user_stats(self, chat_id):
        """Получение статистики пользователя"""
        try:
            conn = sqlite3.connect('users.db', check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT COUNT(*), AVG(score), AVG(time_taken) FROM results WHERE user_id=?", (chat_id,))
            stats = c.fetchone() or (0, 0, 0)
            conn.close()
            
            total_tests = stats[0]
            avg_score_raw = stats[1] or 0
            avg_score = (avg_score_raw / 10 * 100) if avg_score_raw else 0
            avg_time = stats[2] or 0
            
            return {
                'total_tests': int(total_tests),
                'avg_score': avg_score,
                'avg_time': avg_time
            }
        except:
            return {'total_tests': 0, 'avg_score': 0, 'avg_time': 0}
