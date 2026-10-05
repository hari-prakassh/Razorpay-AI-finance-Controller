"""
AI Finance Controller - Main Entry Point.
Executes the end-to-end multi-source reconciliation loop:
1. Synthetic Data Generation (with hidden Ground Truth)
2. Hybrid Multi-Source Reconciliation (Deterministic -> Rules -> LLM -> Confidence Gating)
3. Honest Ground Truth Evaluation (Precision, Recall, Stage Breakdown, Error Confusion Matrix)
4. Exception & Report Generation (matches.csv, exceptions.csv, metrics.json, dashboard.html)
5. Terminal CLI Dashboard
"""

import os
import sys
import argparse

# Ensure standard UTF-8 console output on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.data_generator import generate_synthetic_dataset
from src.pipeline import ReconciliationPipeline
from src.evaluator import evaluate_reconciliation
from src.reporter import save_results, print_cli_dashboard
from src.dashboard import generate_html_dashboard


def main():
    parser = argparse.ArgumentParser(description="AI Finance Controller - Multi-Source Reconciliation")
    parser.add_argument("--data-dir", default="data", help="Directory for dataset files")
    parser.add_argument("--results-dir", default="results", help="Directory for output files")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument("--skip-gen", action="store_true", help="Skip synthetic data generation if files already exist")
    parser.add_argument("--chat", action="store_true", help="Launch interactive conversational copilot with the AI Finance Controller")
    parser.add_argument("--web", action="store_true", help="Launch interactive web application with in-app AI Copilot and data upload")
    args = parser.parse_args()

    if args.web:
        from src.web_app import start_server
        start_server(port=5000, open_browser=True)
        return

    # Step 1: Ensure Synthetic Data Exists
    gt_path = os.path.join(args.data_dir, "ground_truth.csv")
    if not args.skip_gen or not os.path.exists(gt_path):
        print(f"[*] Step 1: Generating realistic synthetic dataset (seed={args.seed})...")
        stats = generate_synthetic_dataset(output_dir=args.data_dir, seed=args.seed)
        print(f"    -> Generated {stats['bank_records_count']} Bank lines, {stats['gateway_records_count']} Gateway lines, {stats['ledger_records_count']} Ledger lines.")
        print(f"    -> Ground truth mapped across {stats['ground_truth_groups_count']} reconciliation groups.\n")

    # Step 2: Run Reconciliation Pipeline
    print("[*] Step 2: Executing Hybrid Reconciliation Pipeline...")
    print("    -> Stage A: Exact Deterministic Matcher")
    print("    -> Stage B: Rule-Based Domain Matcher (MDR fees, TDS, Regex, Batch Splits)")
    print("    -> Stage C: LLM Matcher (Claude API / Fallback Reasoner on leftovers)")
    print("    -> Stage D: Strict Confidence Gating\n")

    pipeline = ReconciliationPipeline(data_dir=args.data_dir)
    pipe_results = pipeline.run()

    # Step 3: Honest Evaluation against Hidden Ground Truth
    print("[*] Step 3: Evaluating Decisions Honestly Against Hidden Ground Truth...")
    eval_results = evaluate_reconciliation(
        matches=pipe_results["all_matches"],
        ground_truth=pipe_results["ground_truth"],
        pipeline_summary=pipe_results["summary"],
        llm_telemetry=pipe_results["llm_telemetry"]
    )

    # Step 4: Save Outputs and Exception Report
    print(f"[*] Step 4: Exporting audit artifacts into '{args.results_dir}/'...")
    file_paths = save_results(
        matches=pipe_results["all_matches"],
        eval_results=eval_results,
        output_dir=args.results_dir
    )

    dashboard_path = os.path.join(args.results_dir, "reconciliation_dashboard.html")
    generate_html_dashboard(
        matches=pipe_results["all_matches"],
        eval_results=eval_results,
        output_path=dashboard_path
    )

    print(f"    -> Saved {file_paths['matches_csv']}")
    print(f"    -> Saved {file_paths['exceptions_csv']} ({file_paths['exceptions_count']} flagged items)")
    print(f"    -> Saved {file_paths['metrics_json']}")
    print(f"    -> Generated Visual Dashboard: {dashboard_path}\n")

    # Step 5: Render CLI Summary
    print_cli_dashboard(eval_results, file_paths["exceptions_csv"])

    print(f"Reconciliation Complete. Open '{dashboard_path}' in your browser to view the static report.")
    print("To launch the live Web Application with in-app AI Copilot and custom Data Upload:")
    print("    py app.py   (or py run.py --web)\n")

    # Step 6: Interactive Agent Chat (if --chat or --interactive requested)
    if args.chat:
        from src.agent import FinanceControllerAgent
        agent = FinanceControllerAgent()
        print("\n" + "=" * 80)
        print("          AI FINANCE CONTROLLER : INTERACTIVE AGENT COPILOT")
        print("          Ask anything about the reconciled batch, exceptions, or audit decisions.")
        print("          (Type 'exit' or 'quit' to leave)")
        print("=" * 80)

        # Build context
        with open(file_paths["exceptions_csv"], "r", encoding="utf-8") as f:
            import csv
            exceptions_list = list(csv.DictReader(f))
        chat_context = {
            "exceptions": exceptions_list,
            "metrics": eval_results,
            "summary": pipe_results["summary"]
        }

        while True:
            try:
                user_q = input("\n[You] > ").strip()
                if not user_q:
                    continue
                if user_q.lower() in ("exit", "quit", "q"):
                    print("[AI Controller] Signing off audit session. All records logged.")
                    break
                response = agent.answer_query(user_q, chat_context)
                print(f"\n[AI Controller]\n{response}\n")
            except (KeyboardInterrupt, EOFError):
                break


if __name__ == "__main__":
    main()
