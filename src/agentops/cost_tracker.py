"""LLM Token Consumption and Cost Tracking."""
import time
from typing import Dict, List, Optional
from pydantic import BaseModel
from src.agentops.metrics import LLM_TOKEN_USAGE_TOTAL, LLM_COST_DOLLARS_TOTAL

class ModelCallCost(BaseModel):
    call_id: str
    run_id: str
    agent_name: str
    step: str
    model: str
    prompt_version: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_dollars: float
    is_measured: bool  # True if directly reported by provider, False if estimated
    timestamp: float

class CostAggregates(BaseModel):
    run_id: str
    total_calls: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_cost_dollars: float
    estimated_cost_per_100_runs: float
    largest_cost_step: Optional[str]

class CostTracker:
    """Tracks token consumption and calculates costs using configurable pricing."""
    def __init__(self, cost_per_1k_prompt: float = 0.00015, cost_per_1k_completion: float = 0.00060):
        self.pricing: Dict[str, Dict[str, float]] = {
            # Default rate per 1,000 tokens
            "default": {
                "prompt": cost_per_1k_prompt,
                "completion": cost_per_1k_completion
            },
            "gpt-4o-mini": {
                "prompt": 0.00015,
                "completion": 0.00060
            },
            "gpt-4o": {
                "prompt": 0.00500,
                "completion": 0.01500
            },
            "stub": {
                "prompt": 0.00015,
                "completion": 0.00060
            }
        }
        self._history: List[ModelCallCost] = []

    def record_call(
        self,
        run_id: str,
        agent_name: str,
        step: str,
        model: str,
        prompt_version: str,
        prompt_tokens: int,
        completion_tokens: int,
        is_measured: bool = True
    ) -> ModelCallCost:
        total_tokens = prompt_tokens + completion_tokens
        rates = self.pricing.get(model, self.pricing["default"])
        cost = (prompt_tokens / 1000.0 * rates["prompt"]) + (completion_tokens / 1000.0 * rates["completion"])

        record = ModelCallCost(
            call_id=f"call_{int(time.time() * 1000)}_{len(self._history)}",
            run_id=run_id,
            agent_name=agent_name,
            step=step,
            model=model,
            prompt_version=prompt_version,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_dollars=round(cost, 6),
            is_measured=is_measured,
            timestamp=time.time()
        )
        self._history.append(record)

        # Update Prometheus metrics
        LLM_TOKEN_USAGE_TOTAL.labels(model=model, prompt_version=prompt_version, token_type="prompt").inc(prompt_tokens)
        LLM_TOKEN_USAGE_TOTAL.labels(model=model, prompt_version=prompt_version, token_type="completion").inc(completion_tokens)
        LLM_COST_DOLLARS_TOTAL.labels(model=model, prompt_version=prompt_version).inc(cost)

        return record

    def get_run_aggregates(self, run_id: str) -> CostAggregates:
        calls = [c for c in self._history if c.run_id == run_id]
        if not calls:
            return CostAggregates(
                run_id=run_id,
                total_calls=0,
                total_prompt_tokens=0,
                total_completion_tokens=0,
                total_tokens=0,
                total_cost_dollars=0.0,
                estimated_cost_per_100_runs=0.0,
                largest_cost_step=None
            )

        total_prompt = sum(c.prompt_tokens for c in calls)
        total_comp = sum(c.completion_tokens for c in calls)
        total_tok = sum(c.total_tokens for c in calls)
        total_cost = sum(c.cost_dollars for c in calls)

        # Find largest cost-consuming execution step
        step_costs: Dict[str, float] = {}
        for c in calls:
            key = f"{c.agent_name}::{c.step}"
            step_costs[key] = step_costs.get(key, 0.0) + c.cost_dollars
        
        largest_step = max(step_costs.items(), key=lambda x: x[1])[0] if step_costs else None

        return CostAggregates(
            run_id=run_id,
            total_calls=len(calls),
            total_prompt_tokens=total_prompt,
            total_completion_tokens=total_comp,
            total_tokens=total_tok,
            total_cost_dollars=round(total_cost, 6),
            estimated_cost_per_100_runs=round(total_cost * 100, 4),
            largest_cost_step=largest_step
        )

    def get_all_records(self) -> List[ModelCallCost]:
        return list(self._history)

cost_tracker = CostTracker()
