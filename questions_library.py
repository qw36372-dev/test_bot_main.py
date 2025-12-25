import json
import random
import os
import glob

class QuestionsLibrary:
    def __init__(self, questions_file):
        self.questions_file = self._find_questions_file(questions_file)
        self.questions = []
        self._load_questions()

    def _find_questions_file(self, base_name):
        if os.path.exists(base_name):
            return base_name
        patterns = [
            base_name.replace(' ', '_'),
            base_name.replace(' ', ''),
            f"{os.path.splitext(base_name)[0]}.json",
            f"{os.path.splitext(os.path.splitext(base_name)[0])[0]}_questions.json"
        ]
        for pattern in patterns:
            if os.path.exists(pattern):
                print(f"Found questions: {pattern}")
                return pattern
        candidates = glob.glob("*_questions*.json") + glob.glob("*.json")
        if candidates:
            print(f"Using first found: {candidates[0]}")
            return candidates[0]
        raise FileNotFoundError(f"No questions file found near {base_name}. Candidates: {candidates}")

    def _load_questions(self):
        try:
            print(f"Loading: {self.questions_file}")
            with open(self.questions_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.questions = self._validate_questions(data)
            print(f"Loaded {len(self.questions)} questions")
        except Exception as e:
            raise RuntimeError(f"Failed to load {self.questions_file}: {e}")

    def _validate_questions(self, questions):
        if not isinstance(questions, list):
            return []
        validated = []
        for i, q in enumerate(questions):
            if not isinstance(q, dict): continue
            if 'question' not in q or 'options' not in q or 'correct' not in q: continue
            if not isinstance(q['question'], str) or not q['question'].strip(): continue
            if not isinstance(q['options'], list) or len(q['options']) < 2: continue
            if not isinstance(q['correct'], list) or not q['correct']: continue
            valid_correct = [idx for idx in q['correct'] if 0 <= idx < len(q['options'])]
            if not valid_correct: continue
            q['correct'] = valid_correct
            validated.append(q)
        return validated

    def get_questions_count(self):
        return len(self.questions)

    def get_random_questions(self, count):
        if count <= 0: raise ValueError("Count must be positive")
        if len(self.questions) < count: raise ValueError(f"Not enough questions. Need {count}, have {len(self.questions)}")
        return random.sample(self.questions, count)
