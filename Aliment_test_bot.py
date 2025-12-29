# 29.12 12:56 Aliment_test_bot.py (ФИНАЛЬНАЯ с questions_library)
import json
import sqlite3
import time
import os
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from datetime import datetime
from telebot import types

from questions_library import QuestionsLibrary

ql = QuestionsLibrary("Aliment_test_bot_questions.json")

DIFFICULTIES = {
    'rezerv': {'questions': 20, 'time': 35*60, 'name': 'Резерв'},
    'bazovyy': {'questions': 25, 'time': 40*60, 'name': 'Базовый'},
    'standart': {'questions': 30, 'time': 45*60, 'name': 'Стандартный'},
    'expert': {'questions': 50, 'time': 90*60, 'name': 'Эксперт'}
}

def get_questions():
    markup = types.InlineKeyboardMarkup(row_width=1)
    total_questions = ql.get_questions_count()
    
    for diff_key, info in DIFFICULTIES.items():
        count = min(info['questions'], total_questions)
        markup.add(types.InlineKeyboardButton(
            f"{info['name']} ({count}в, {info['time']//60}мин)", 
            callback_data=f"difficulty:{diff_key}"
        ))
    return {
        'type': 'difficulty_menu',
        'markup': markup,
        'text': f'Выберите сложность теста:\nЗагружено вопросов: {total_questions}'
    }

def calculate_score(questions, answers):
    score = 0
    for i, q in enumerate(questions):
        if i in answers and answers[i]:
            correct_indices = q.get('correct', [])
            user_answer = answers[i]
            if isinstance(user_answer, list) and isinstance(correct_indices, list):
                if set(user_answer) == set(correct_indices):
                    score += 1
            elif isinstance(correct_indices, list) and user_answer == correct_indices[0]:
                score += 1
    return score

def generate_certificate(user_id, score, total_questions, time_spent):
    db_path = "test_bot.db"
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT full_name, position, department FROM users 
                WHERE user_id = ? LIMIT 1
            """, (user_id,))
            user_data = cursor.fetchone()
            
            if not user_
                return None
                
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
                f"ФИО: {user_data[0] or 'Не указано'}",
                f"Должность: {user_data[1] or 'Не указано'}",
                f"Подразделение: {user_data[2] or 'Не указано'}",
                f"Результат: {score}/{total_questions} ({score/total_questions*100:.0f}%)",
                f"Время прохождения: {int(time_spent//60)} мин {int(time_spent%60)} сек",
                f"Дата: {datetime.now().strftime('%d.%m.%Y')}"
            ]
            for line in info:
                c.drawCentredText(width/2, y, line)
                y -= 1.2*cm
            
            c.save()
            return filename
    except Exception:
        return None
