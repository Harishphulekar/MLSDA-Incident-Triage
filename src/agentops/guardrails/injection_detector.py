"""Prompt Injection and System Override Defense."""
import re
from typing import Dict, List, Tuple
from pydantic import BaseModel

class GuardrailVerdict(BaseModel):
    is_safe: bool
    risk_score: float  # 0.0 (safe) to 1.0 (dangerous)
    detected_patterns: List[str]
    category: str
    remediation_action: str

# Regular expression rules for prompt injection and override attacks
INJECTION_PATTERNS = [
    # System instruction override attempts
    (re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|directives|rules|prompts)", re.IGNORECASE), "system_override"),
    (re.compile(r"disregard\s+(all\s+)?(previous|prior)\s+(rules|guidelines)", re.IGNORECASE), "system_override"),
    (re.compile(r"forget\s+(everything|all)\s+you\s+(were\s+told|know)", re.IGNORECASE), "system_override"),
    
    # Role hijacking & Jailbreaks
    (re.compile(r"you\s+are\s+now\s+(DAN|unrestricted|godmode|root|an\s+attacker|unfiltered)", re.IGNORECASE), "role_hijacking"),
    (re.compile(r"act\s+as\s+a\s+(superadmin|penetration\s+tester|unconstrained\s+ai)", re.IGNORECASE), "role_hijacking"),
    (re.compile(r"<\s*\|?\s*im_start\s*\|?>|system\s*:\s*you\s*are", re.IGNORECASE), "format_spoofing"),

    # Direct unauthorized operational command injection
    (re.compile(r"(sudo\s+rm\s+-rf|drop\s+database|truncate\s+table|format\s+c:|mkfs\.)", re.IGNORECASE), "malicious_command"),
    (re.compile(r"(curl|wget)\s+https?://[^\s]+\s*\|\s*(sh|bash)", re.IGNORECASE), "malicious_command"),
    
    # Tool permission elevation
    (re.compile(r"(grant\s+all\s+privileges|bypass\s+permissions|execute\s+arbitrary\s+code)", re.IGNORECASE), "privilege_elevation"),
    (re.compile(r"force\s+(execute|run)\s+(remediation|script)\s+without\s+approval", re.IGNORECASE), "unauthorized_execution")
]

class PromptInjectionDetector:
    """Evaluates untrusted user inputs (alerts, notes) for adversarial prompt injection."""
    def __init__(self, sensitivity_threshold: float = 0.5):
        self.sensitivity_threshold = sensitivity_threshold

    def evaluate(self, text: str) -> GuardrailVerdict:
        if not text or not text.strip():
            return GuardrailVerdict(
                is_safe=True,
                risk_score=0.0,
                detected_patterns=[],
                category="clean",
                remediation_action="allow"
            )

        matched_patterns: List[str] = []
        matched_categories: List[str] = []

        for pattern, category in INJECTION_PATTERNS:
            matches = pattern.findall(text)
            if matches:
                matched_patterns.append(pattern.pattern)
                matched_categories.append(category)

        if matched_patterns:
            risk_score = min(1.0, 0.4 + (0.3 * len(matched_patterns)))
            is_safe = risk_score < self.sensitivity_threshold
            category_summary = ", ".join(set(matched_categories))
            
            return GuardrailVerdict(
                is_safe=is_safe,
                risk_score=risk_score,
                detected_patterns=matched_patterns,
                category=category_summary,
                remediation_action="block" if not is_safe else "flag_and_continue"
            )

        return GuardrailVerdict(
            is_safe=True,
            risk_score=0.0,
            detected_patterns=[],
            category="clean",
            remediation_action="allow"
        )

injection_detector = PromptInjectionDetector()
