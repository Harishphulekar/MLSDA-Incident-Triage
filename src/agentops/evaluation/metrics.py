"""TruLens-Compatible Evaluation Metrics: Groundedness, Context Relevance, Faithfulness, Hallucination Rate."""
import re
from typing import Any, Dict, List
from pydantic import BaseModel

class EvaluationScore(BaseModel):
    scenario_id: str
    groundedness: float
    context_relevance: float
    faithfulness: float
    hallucination_rate: float
    routing_correct: bool
    evidence_verified: bool
    details: Dict[str, Any]

class EvaluationSummary(BaseModel):
    prompt_version: str
    scenarios_evaluated: int
    mean_groundedness: float
    mean_context_relevance: float
    mean_faithfulness: float
    mean_hallucination_rate: float
    routing_accuracy: float
    human_escalation_precision: float
    total_cost_dollars: float

def compute_context_relevance(alert_text: str, on_call_note: str, retrieved_docs: List[str]) -> float:
    """
    Calculates Context Relevance score in [0.0, 1.0].
    Measures the proportion of retrieved document content directly relevant to the incident query.
    """
    if not retrieved_docs:
        return 0.0

    query_tokens = set(re.findall(r"\w+", f"{alert_text} {on_call_note}".lower()))
    stopwords = {"and", "the", "or", "to", "in", "is", "at", "on", "a", "an", "for", "with", "from"}
    query_keywords = {t for t in query_tokens if len(t) > 3 and t not in stopwords}

    if not query_keywords:
        return 0.5

    relevance_scores = []
    for doc in retrieved_docs:
        doc_tokens = set(re.findall(r"\w+", doc.lower()))
        overlap = len(query_keywords.intersection(doc_tokens))
        rel = min(1.0, overlap / max(1, len(query_keywords) * 0.4))
        relevance_scores.append(rel)

    return round(sum(relevance_scores) / len(relevance_scores), 4)

def compute_groundedness(hypothesis: str, actions: List[str], citations: List[Dict[str, Any]], retrieved_docs: List[str]) -> float:
    """
    Calculates Groundedness score in [0.0, 1.0].
    Measures whether the diagnostic claims and citations are derived from retrieved corpus evidence.
    """
    if not retrieved_docs:
        # If no documents were retrieved, claims cannot be grounded in context
        return 0.0 if (hypothesis or actions) else 1.0

    corpus_text = " ".join(retrieved_docs).lower()
    
    # 1. Evaluate citation validity
    citation_score = 1.0
    if citations:
        valid_citations = 0
        for c in citations:
            passage = c.get("quoted_passage", "").strip().lower()
            section = c.get("section", "").strip().lower()
            if (passage and passage in corpus_text) or (section and section in corpus_text):
                valid_citations += 1
        citation_score = valid_citations / len(citations)
    else:
        # Prompt v1 without citations gets lower groundedness anchor
        citation_score = 0.5

    # 2. Evaluate hypothesis term support
    hyp_words = [w for w in re.findall(r"\w+", hypothesis.lower()) if len(w) > 4]
    if hyp_words:
        supported_words = sum(1 for w in hyp_words if w in corpus_text)
        hyp_score = supported_words / len(hyp_words)
    else:
        hyp_score = 0.5

    groundedness = (0.6 * citation_score) + (0.4 * hyp_score)
    return round(min(1.0, max(0.0, groundedness)), 4)

def compute_faithfulness(result: Dict[str, Any], scenario: Dict[str, Any]) -> float:
    """
    Calculates Faithfulness score in [0.0, 1.0].
    Measures whether the system output remains faithful to verified operational reality and expected cause.
    """
    expected_cause = scenario.get("expected_cause_class", "").lower()
    actual_cause = result.get("cause_class", "").lower()
    
    # If blocked by security guardrail for injection, it is faithful to safety protocol
    if result.get("status") == "blocked" and "security" in expected_cause:
        return 1.0

    # Semantic keyword alignment
    exp_words = set(re.findall(r"\w+", expected_cause))
    act_words = set(re.findall(r"\w+", actual_cause))
    overlap = len(exp_words.intersection(act_words))

    cause_alignment = min(1.0, overlap / max(1, len(exp_words)))
    
    # Check if confidence reflects evidence sufficiency
    evidence_sufficient = result.get("evidence_sufficient", False)
    confidence = float(result.get("confidence", 0.5))

    calibration = 1.0 - abs(confidence - (0.9 if evidence_sufficient else 0.35))
    faithfulness = (0.7 * cause_alignment) + (0.3 * calibration)
    return round(min(1.0, max(0.0, faithfulness)), 4)

def evaluate_scenario(result: Dict[str, Any], scenario: Dict[str, Any], retrieved_docs: List[str]) -> EvaluationScore:
    """Computes TruLens triad + hallucination rate for a single incident scenario."""
    hyp = result.get("hypothesis", "")
    actions = result.get("recommended_actions", [])
    citations = result.get("evidence_citations", [])

    groundedness = compute_groundedness(hyp, actions, citations, retrieved_docs)
    context_relevance = compute_context_relevance(
        scenario.get("alert_payload", ""),
        scenario.get("on_call_notes", ""),
        retrieved_docs
    )
    faithfulness = compute_faithfulness(result, scenario)
    hallucination_rate = round(max(0.0, 1.0 - groundedness), 4)

    expected_routing = scenario.get("expected_routing")
    actual_routing = result.get("routing_decision")
    routing_correct = (expected_routing == actual_routing)

    return EvaluationScore(
        scenario_id=scenario.get("scenario_id", "unknown"),
        groundedness=groundedness,
        context_relevance=context_relevance,
        faithfulness=faithfulness,
        hallucination_rate=hallucination_rate,
        routing_correct=routing_correct,
        evidence_verified=result.get("evidence_sufficient", False),
        details={
            "actual_cause": result.get("cause_class"),
            "expected_cause": scenario.get("expected_cause_class"),
            "actual_routing": actual_routing,
            "expected_routing": expected_routing,
            "confidence": result.get("confidence")
        }
    )
