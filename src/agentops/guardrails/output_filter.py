"""Output Filtering Guardrail: Enforces Human Advisory Boundaries and Valid Citations."""
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

class OutputFilterResult(BaseModel):
    passed: bool
    violations: List[str]
    sanitized_output: Dict[str, Any]
    escalation_required: bool

# Patterns where the AI claims it executed or completed remediation actions
ACTION_CLAIM_PATTERNS = [
    re.compile(r"i\s+(have\s+)?(executed|run|restarted|killed|deleted|dropped|modified|patched|applied)", re.IGNORECASE),
    re.compile(r"the\s+(system|assistant|bot)\s+(has\s+)?(remediated|fixed|restarted|cleaned\s+up)", re.IGNORECASE),
    re.compile(r"successfully\s+(restarted|deleted|dropped|executed|applied)", re.IGNORECASE),
    re.compile(r"remediation\s+(has\s+been|was)\s+(completed|performed|executed)", re.IGNORECASE)
]

class OutputFilter:
    """Enforces that AI responses never claim execution, only provide advisory guidance, and validate citations."""
    
    def filter_response(self, response_data: Dict[str, Any], retrieved_corpus_docs: Optional[List[str]] = None) -> OutputFilterResult:
        violations: List[str] = []
        sanitized = dict(response_data)
        escalation_required = False

        # 1. Check for false remediation claims in hypothesis and recommendations
        text_to_check = str(response_data.get("hypothesis", "")) + " " + " ".join(response_data.get("recommended_actions", []))
        
        for pattern in ACTION_CLAIM_PATTERNS:
            if pattern.search(text_to_check):
                violations.append(f"Forbidden remediation claim detected: '{pattern.pattern}'")
                escalation_required = True

        # 2. Check for unauthorized automatic resolution routing if evidence is low or risky
        confidence = float(response_data.get("confidence", 0.0))
        routing = str(response_data.get("routing_decision", "")).lower()
        if routing == "auto_resolve":
            violations.append("Unauthorized autonomous resolution decision: auto-resolve is forbidden for AI assistant.")
            sanitized["routing_decision"] = "escalate_sre"
            escalation_required = True

        # 3. Check citation validity against retrieved documents if available
        citations = response_data.get("evidence_citations", [])
        if retrieved_corpus_docs is not None and citations:
            corpus_text = " ".join(retrieved_corpus_docs).lower()
            for cit in citations:
                if isinstance(cit, dict):
                    passage = cit.get("quoted_passage", "").strip().lower()
                    section = cit.get("section", "").strip().lower()
                    if passage and len(passage) > 20 and passage not in corpus_text:
                        violations.append(f"Unverified citation detected: '{passage[:40]}...' not found in retrieved corpus.")

        # 4. Enforce human advisory phrasing on recommended actions
        actions = sanitized.get("recommended_actions", [])
        enforced_actions = []
        for act in actions:
            # Clean imperative action claims
            clean_act = act
            for pat in ACTION_CLAIM_PATTERNS:
                clean_act = pat.sub("Advise human engineer to inspect and", clean_act)
            if not any(clean_act.lower().startswith(prefix) for prefix in ["recommend", "advise", "suggest", "inspect", "check", "verify", "consider"]):
                clean_act = f"Recommend: {clean_act}"
            enforced_actions.append(clean_act)
        sanitized["recommended_actions"] = enforced_actions

        passed = len(violations) == 0
        if not passed:
            # Mark advisory note in response
            sanitized["guardrail_notice"] = "Response filtered by AgentOps Guardrail to enforce human-in-the-loop advisory boundaries."
            if escalation_required:
                sanitized["routing_decision"] = "escalate_human_expert"

        return OutputFilterResult(
            passed=passed,
            violations=violations,
            sanitized_output=sanitized,
            escalation_required=escalation_required
        )

output_filter = OutputFilter()
