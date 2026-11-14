"""Toxicity and Abusive Content Guardrail."""
import re
from typing import List
from pydantic import BaseModel

class ToxicityResult(BaseModel):
    is_toxic: bool
    toxicity_score: float
    categories: List[str]

# Toxicity indicators including profanity, abusive threats, harassment, sabotage
TOXIC_TERMS = [
    (re.compile(r"\b(idiot|stupid|moron|dumb|useless\s+bot|incompetent)\b", re.IGNORECASE), "insult"),
    (re.compile(r"\b(kill\s+yourself|destroy\s+them|burn\s+down|sabotage)\b", re.IGNORECASE), "threat_violence"),
    (re.compile(r"\b(hate|racist|slur|f\*\*\*|b\*\*\*\*|sh\*t)\b", re.IGNORECASE), "profanity_hate")
]

class ToxicityChecker:
    """Evaluates text for offensive, toxic, or hostile content."""
    def check_text(self, text: str) -> ToxicityResult:
        if not text:
            return ToxicityResult(is_toxic=False, toxicity_score=0.0, categories=[])

        matched_cats: List[str] = []
        for pattern, cat in TOXIC_TERMS:
            if pattern.search(text):
                matched_cats.append(cat)

        if matched_cats:
            score = min(1.0, 0.4 + 0.3 * len(matched_cats))
            return ToxicityResult(is_toxic=True, toxicity_score=score, categories=list(set(matched_cats)))

        return ToxicityResult(is_toxic=False, toxicity_score=0.0, categories=[])

toxicity_checker = ToxicityChecker()
