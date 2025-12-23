import json
import random
from typing import List, Dict
import os

class QuestionsLibrary:
    def __init__(self, questions_file: str = "questions.json"):
        self.questions_file = questions_file
        self.questions: List[Dict] = []
        self._load_questions()
    
    def _load_questions(self):
        if not os.path.exists(self.questions_file):
            raise FileNotFoundError(
                f"Файл {self.questions_file} не найден! "
                f"Создайте файл questions.json с вопросами."
            )
        
        try:
            with open(self.questions_file, 'r', encoding='utf-8') as f:
                self.questions = json.load(f)
            
            print(f"✅ Загружено {len(self.questions)} вопросов из {self.questions_file}")
            self._validate_questions()
            
        except json.JSONDecodeError as e:
            raise ValueError(f"Ошибка в формате JSON файла {self.questions_file}: {e}")
        except Exception as e:
            raise RuntimeError(f"Ошибка загрузки вопросов: {e}")
    
    def _validate_questions(self):
        for i, q in enumerate(self.questions):
            if not all(key in q for key in ['question', 'options', 'correct']):
                raise ValueError(f"Вопрос {i+1}: отсутствуют обязательные поля")
            
            if len(q['options']) < 3:
                print(f"⚠️ Вопрос {i+1}: меньше 3 вариантов ответа")
            
            if not q['correct']:
                raise ValueError(f"Вопрос {i+1}: нет правильных ответов")
            
            max_idx = len(q['options']) - 1
            for idx in q['correct']:
                if not (0 <= idx <= max_idx):
                    raise ValueError(f"Вопрос {i+1}: неверный индекс правильного ответа {idx}")
    
    def get_random_questions(self, count: int) -> List[Dict]:
        available_count = min(count, len(self.questions))
        if available_count == 0:
            raise ValueError("Библиотека вопросов пуста!")
        selected_questions = random.sample(self.questions, available_count)
        print(f"🎲 Выбрано {available_count} случайных вопросов")
        return selected_questions
    
    def get_total_count(self) -> int:
        return len(self.questions)
    
    def get_question_stats(self) -> Dict:
        multi_choice = sum(1 for q in self.questions if len(q['correct']) > 1)
        return {
            'total': len(self.questions),
            'multi_choice': multi_choice,
            'single_choice': len(self.questions) - multi_choice,
            'avg_options': sum(len(q['options']) for q in self.questions) / len(self.questions)
        }
    
    def reload(self):
        self._load_questions()
    
    def __len__(self):
        return len(self.questions)
    
    def __repr__(self):
        stats = self.get_question_stats()
        return f"QuestionsLibrary(total={stats['total']}, multi={stats['multi_choice']})"

if __name__ == "__main__":
    try:
        ql = QuestionsLibrary()
        print(f"📊 Статистика: {ql.get_question_stats()}")
        print(f"📦 Всего вопросов: {len(ql)}")
        questions = ql.get_random_questions(5)
        print(f"\n🎲 Пример 5 случайных вопросов:")
        for i, q in enumerate(questions, 1):
            correct = [idx+1 for idx in q['correct']]
            print(f"{i}. {q['question'][:60]}... Правильные: {correct}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
