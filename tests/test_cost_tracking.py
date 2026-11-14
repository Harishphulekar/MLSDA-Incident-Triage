"""Tests for LLM Token Accounting and Cost Tracking."""
from src.agentops.cost_tracker import CostTracker

def test_cost_tracker_calculation_and_aggregation():
    tracker = CostTracker(cost_per_1k_prompt=0.00015, cost_per_1k_completion=0.00060)
    
    # Call 1: Triage Agent (1000 prompt tokens, 500 completion tokens)
    # Cost = (1000/1000 * 0.00015) + (500/1000 * 0.00060) = 0.00015 + 0.00030 = 0.00045
    call1 = tracker.record_call(
        run_id="run_cost_test_01",
        agent_name="TriageAgent",
        step="classification",
        model="gpt-4o-mini",
        prompt_version="v1.1.0",
        prompt_tokens=1000,
        completion_tokens=500
    )
    assert call1.cost_dollars == 0.00045
    assert call1.total_tokens == 1500

    # Call 2: Verification Agent (500 prompt tokens, 200 completion tokens)
    # Cost = (500/1000 * 0.00015) + (200/1000 * 0.00060) = 0.000075 + 0.00012 = 0.000195
    call2 = tracker.record_call(
        run_id="run_cost_test_01",
        agent_name="VerificationAgent",
        step="verification",
        model="gpt-4o-mini",
        prompt_version="v1.1.0",
        prompt_tokens=500,
        completion_tokens=200
    )

    agg = tracker.get_run_aggregates("run_cost_test_01")
    assert agg.total_calls == 2
    assert agg.total_tokens == 2200
    assert agg.total_cost_dollars == round(0.00045 + 0.000195, 6)
    assert agg.estimated_cost_per_100_runs == round(agg.total_cost_dollars * 100, 4)
    assert agg.largest_cost_step == "TriageAgent::classification"
