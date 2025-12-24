import json
import random
import os

class QuestionsLibrary:
    def __init__(self, questions_file):
        self.questions_file = questions_file
        self.questions = []
        self._load_questions()

    def _load_questions(self):
        try:
            if not os.path.exists(self.questions_file):
                raise FileNotFoundError(f"Questions file not found: {self.questions_file}")
            with open(self.questions_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.questions = self._validate_questions(data)
            print(f"Loaded {len(self.questions)} questions from {self.questions_file}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {self.questions_file}: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to load {self.questions_file}: {e}")

    def _validate_questions(self, questions):
        if not isinstance(questions, list):
            return []
        validated = []
        for i, q in enumerate(questions):
            if not isinstance(q, dict):
                continue
            if 'question' not in q or 'options' not in q or 'correct' not in q:
                continue
            if not isinstance(q['question'], str) or not q['question'].strip():
                continue
            if not isinstance(q['options'], list) or len(q['options']) < 2:
                continue
            if not isinstance(q['correct'], list) or not q['correct']:
                continue
            valid_correct = [idx for idx in q['correct'] if 0 <= idx < len(q['options'])]
            if not valid_correct:
                continue
            q['correct'] = valid_correct
            validated.append(q)
        return validated

    def get_questions_count(self):
        return len(self.questions)

    def get_random_questions(self, count):
        if count <= 0:
            raise ValueError("Count must be positive")
        if len(self.questions) < count:
            raise ValueError(f"Not enough questions. Need {count}, have {len(self.questions)}")
        return random.sample(self.questions, count)

    def validate(self):
        if not self.questions:
            return False, "No valid questions found"
        if len(self.questions) < 10:
            return False, f"Too few questions: {len(self.questions)}"
        return True, f"OK: {len(self.questions)} questions validated"

    def get_sample_question(self):
        if not self.questions:
            return None
        return random.choice(self.questions)
