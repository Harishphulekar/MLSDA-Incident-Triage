"""CLI Evaluation Runner: Executes 20+ Scenarios, Computes Metrics, Compares Prompt Variants."""
import argparse
import asyncio
import csv
import json
import os
import sys
import time
from typing import Any, Dict, List
from tabulate import tabulate

from src.agents.orchestrator import incident_orchestrator
from src.agentops.evaluation.metrics import (
    evaluate_scenario,
    EvaluationScore,
    EvaluationSummary
)
from src.rag.retriever import retriever

def run_batch_evaluation(scenarios_path: str, prompt_version: str) -> Dict[str, Any]:
    """Runs all incident scenarios through the orchestrator and computes metrics."""
    with open(scenarios_path, "r", encoding="utf-8") as f:
        scenarios: List[Dict[str, Any]] = json.load(f)

    print(f"\n================================================================================")
    print(f"🚀 Running Incident Triage Evaluation Suite on {len(scenarios)} Scenarios")
    print(f"   Prompt Version: {prompt_version}")
    print(f"================================================================================\n")

    scores: List[EvaluationScore] = []
    total_cost = 0.0
    start_time = time.time()

    for idx, sc in enumerate(scenarios, 1):
        sc_id = sc["scenario_id"]
        title = sc["title"]
        print(f"[{idx:02d}/{len(scenarios)}] Evaluating {sc_id}: {title[:45]}...", end=" ", flush=True)

        # Retrieve documents for evaluation comparison
        retrieved_docs = retriever.retrieve(f"{sc['alert_payload']} {sc['on_call_notes']}", top_k=3)
        doc_texts = [d.content for d in retrieved_docs]

        # Execute incident through real pipeline
        result = incident_orchestrator.process_incident_sync(
            alert_payload=sc["alert_payload"],
            on_call_notes=sc["on_call_notes"],
            client_id="eval_runner",
            run_id=f"eval_{sc_id.lower().replace('-', '_')}",
            prompt_version=prompt_version
        )

        cost_info = result.get("cost", {})
        total_cost += cost_info.get("total_cost_dollars", 0.0)

        # Score with TruLens-compatible metrics
        score = evaluate_scenario(result, sc, doc_texts)
        scores.append(score)

        status_flag = "✅ PASS" if score.routing_correct and score.groundedness >= 0.7 else "⚠️ ESCALATED" if not score.evidence_verified else "❌ FAIL"
        print(f"{status_flag} (Grounded: {score.groundedness:.2f}, Faithful: {score.faithfulness:.2f})")

    duration = time.time() - start_time

    # Calculate dataset aggregates
    mean_g = round(sum(s.groundedness for s in scores) / len(scores), 4)
    mean_c = round(sum(s.context_relevance for s in scores) / len(scores), 4)
    mean_f = round(sum(s.faithfulness for s in scores) / len(scores), 4)
    mean_h = round(sum(s.hallucination_rate for s in scores) / len(scores), 4)
    routing_acc = round(sum(1 for s in scores if s.routing_correct) / len(scores), 4)
    
    # Human escalation precision & recall confusion matrix
    # TP: required escalation and system escalated
    # FP: did NOT require escalation but system escalated
    # FN: required escalation but system failed to escalate
    # TN: did not require escalation and system did not escalate
    tp = 0
    fp = 0
    fn = 0
    tn = 0

    for s, sc in zip(scores, scenarios):
        target_needed = sc.get("requires_human_escalation", False)
        actual_route = str(s.details.get("actual_routing", ""))
        system_escalated = ("escalate" in actual_route) or (actual_route == "security_soc") or (not s.evidence_verified)

        if target_needed and system_escalated:
            tp += 1
        elif not target_needed and system_escalated:
            fp += 1
        elif target_needed and not system_escalated:
            fn += 1
        else:
            tn += 1

    esc_precision = round(tp / max(1, tp + fp), 4) if (tp + fp) > 0 else 0.0
    esc_recall = round(tp / max(1, tp + fn), 4) if (tp + fn) > 0 else 0.0
    esc_f1 = round(2 * (esc_precision * esc_recall) / (esc_precision + esc_recall), 4) if (esc_precision + esc_recall) > 0 else 0.0

    summary = EvaluationSummary(
        prompt_version=prompt_version,
        scenarios_evaluated=len(scores),
        mean_groundedness=mean_g,
        mean_context_relevance=mean_c,
        mean_faithfulness=mean_f,
        mean_hallucination_rate=mean_h,
        routing_accuracy=routing_acc,
        human_escalation_precision=esc_precision,
        human_escalation_recall=esc_recall,
        human_escalation_f1=esc_f1,
        total_cost_dollars=round(total_cost, 6)
    )

    return {
        "summary": summary.model_dump(),
        "scores": [s.model_dump() for s in scores],
        "duration_seconds": round(duration, 2)
    }

def print_summary_table(summary: Dict[str, Any]):
    table = [
        ["Metric", "Value", "Description"],
        ["Scenarios Evaluated", summary["scenarios_evaluated"], "Fixed benchmark test set"],
        ["Mean Groundedness", f"{summary['mean_groundedness'] * 100:.1f}%", "Claims anchored in retrieved context"],
        ["Mean Context Relevance", f"{summary['mean_context_relevance'] * 100:.1f}%", "Retrieved corpus tokens relevant to alert"],
        ["Mean Faithfulness", f"{summary['mean_faithfulness'] * 100:.1f}%", "Output adherence to operational facts"],
        ["Hallucination Rate", f"{summary['mean_hallucination_rate'] * 100:.1f}%", "Unsupported / unverified assertions"],
        ["Routing Accuracy", f"{summary['routing_accuracy'] * 100:.1f}%", "Exact match on expected routing team"],
        ["Human Escalation Precision", f"{summary['human_escalation_precision'] * 100:.1f}%", "TP / (TP + FP) on mandatory escalations"],
        ["Human Escalation Recall", f"{summary.get('human_escalation_recall', 1.0) * 100:.1f}%", "TP / (TP + FN) on mandatory escalations"],
        ["Human Escalation F1 Score", f"{summary.get('human_escalation_f1', 0.0) * 100:.1f}%", "Harmonic mean 2*P*R / (P+R)"],
        ["Total Evaluation Cost", f"${summary['total_cost_dollars']:.6f}", "Model inference cost across all 20 runs"]
    ]
    print("\n" + tabulate(table, headers="firstrow", tablefmt="fancy_grid"))

def compare_results(file1: str, file2: str):
    """Compares before-and-after results between two evaluation runs."""
    with open(file1, "r", encoding="utf-8") as f:
        data1 = json.load(f)["summary"]
    with open(file2, "r", encoding="utf-8") as f:
        data2 = json.load(f)["summary"]

    print("\n================================================================================")
    print(f"📊 PROMPT VARIANT COMPARISON: {data1['prompt_version']} vs {data2['prompt_version']}")
    print("================================================================================\n")

    diff_table = [
        ["Metric", f"Baseline ({data1['prompt_version']})", f"Improved ({data2['prompt_version']})", "Delta / Impact"],
        ["Mean Groundedness", f"{data1['mean_groundedness']*100:.1f}%", f"{data2['mean_groundedness']*100:.1f}%", f"{(data2['mean_groundedness'] - data1['mean_groundedness'])*100:+.1f}%"],
        ["Context Relevance", f"{data1['mean_context_relevance']*100:.1f}%", f"{data2['mean_context_relevance']*100:.1f}%", f"{(data2['mean_context_relevance'] - data1['mean_context_relevance'])*100:+.1f}%"],
        ["Faithfulness", f"{data1['mean_faithfulness']*100:.1f}%", f"{data2['mean_faithfulness']*100:.1f}%", f"{(data2['mean_faithfulness'] - data1['mean_faithfulness'])*100:+.1f}%"],
        ["Hallucination Rate", f"{data1['mean_hallucination_rate']*100:.1f}%", f"{data2['mean_hallucination_rate']*100:.1f}%", f"{(data2['mean_hallucination_rate'] - data1['mean_hallucination_rate'])*100:+.1f}%"],
        ["Routing Accuracy", f"{data1['routing_accuracy']*100:.1f}%", f"{data2['routing_accuracy']*100:.1f}%", f"{(data2['routing_accuracy'] - data1['routing_accuracy'])*100:+.1f}%"],
        ["Escalation Precision", f"{data1.get('human_escalation_precision', 0.0)*100:.1f}%", f"{data2.get('human_escalation_precision', 0.0)*100:.1f}%", f"{(data2.get('human_escalation_precision', 0.0) - data1.get('human_escalation_precision', 0.0))*100:+.1f}%"],
        ["Escalation Recall", f"{data1.get('human_escalation_recall', 1.0)*100:.1f}%", f"{data2.get('human_escalation_recall', 1.0)*100:.1f}%", f"{(data2.get('human_escalation_recall', 1.0) - data1.get('human_escalation_recall', 1.0))*100:+.1f}%"],
        ["Escalation F1 Score", f"{data1.get('human_escalation_f1', 0.0)*100:.1f}%", f"{data2.get('human_escalation_f1', 0.0)*100:.1f}%", f"{(data2.get('human_escalation_f1', 0.0) - data1.get('human_escalation_f1', 0.0))*100:+.1f}%"],
        ["Total Cost (20 runs)", f"${data1['total_cost_dollars']:.6f}", f"${data2['total_cost_dollars']:.6f}", f"${data2['total_cost_dollars'] - data1['total_cost_dollars']:+.6f}"]
    ]
    print(tabulate(diff_table, headers="firstrow", tablefmt="fancy_grid"))

def main():
    parser = argparse.ArgumentParser(description="AgentOps Evaluation Runner for Incident Triage Assistant")
    parser.add_argument("--scenarios", default="./src/agentops/evaluation/scenarios.json", help="Path to scenarios JSON file")
    parser.add_argument("--prompt-version", default="v1.1.0", help="Prompt template version (v1.0.0, v1.1.0)")
    parser.add_argument("--output", default="eval_results.json", help="Output path for JSON results")
    parser.add_argument("--compare", nargs=2, metavar=("FILE1", "FILE2"), help="Compare two previous result JSON files")

    args = parser.parse_args()

    if args.compare:
        compare_results(args.compare[0], args.compare[1])
        return

    output = run_batch_evaluation(args.scenarios, args.prompt_version)
    print_summary_table(output["summary"])

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"\n📁 Detailed evaluation results saved to '{args.output}'")

    # Also save CSV for tabular inspection
    csv_file = args.output.replace(".json", ".csv")
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Scenario_ID", "Groundedness", "Context_Relevance", "Faithfulness", "Hallucination_Rate", "Routing_Correct", "Actual_Cause", "Expected_Cause"])
        for s in output["scores"]:
            writer.writerow([
                s["scenario_id"], s["groundedness"], s["context_relevance"],
                s["faithfulness"], s["hallucination_rate"], s["routing_correct"],
                s["details"]["actual_cause"], s["details"]["expected_cause"]
            ])
    print(f"📁 CSV summary saved to '{csv_file}'\n")

if __name__ == "__main__":
    main()
