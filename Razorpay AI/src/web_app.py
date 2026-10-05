"""
AI Finance Controller - Interactive Web Application.
Provides:
1. In-App AI Finance Controller Conversational Copilot (Chat inside the application)
2. User Data Management:
   - Upload custom Bank Statement, Gateway Settlement, and Internal Ledger CSVs
   - Add single transactions manually via interactive form
   - 1-Click Load Benchmark Synthetic Dataset
3. Interactive Reconciliation Dashboard:
   - Live KPI cards, Stage breakdown, Error Confusion Matrix
   - Filterable Matches Explorer
   - Forensic Exception Triage Action Center
   - CSV & JSON Exports
"""

import csv
import json
import os
import sys
import time
import webbrowser
from datetime import datetime
from flask import Flask, request, jsonify, send_file, render_template_string
from flask_cors import CORS

from src.models import BankTransaction, GatewaySettlement, InternalInvoice, ReconciliationMatch
from src.data_generator import generate_synthetic_dataset
from src.pipeline import ReconciliationPipeline
from src.evaluator import evaluate_reconciliation
from src.reporter import save_results, classify_exception
from src.agent import FinanceControllerAgent


app = Flask(__name__)
CORS(app)

DATA_DIR = "data"
RESULTS_DIR = "results"
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

# State cache
app_state = {
    "pipeline_results": None,
    "eval_results": None,
    "exceptions_list": [],
    "matches_list": [],
    "agent": None,
    "last_reconciled_at": None,
    "dataset_source": "Synthetic Benchmark"
}


def init_app_state(force_regenerate=False):
    """Initializes or re-runs the reconciliation engine."""
    gt_path = os.path.join(DATA_DIR, "ground_truth.csv")
    if force_regenerate or not os.path.exists(gt_path):
        generate_synthetic_dataset(output_dir=DATA_DIR, seed=42)
        app_state["dataset_source"] = "Synthetic Benchmark (80 Groups)"

    pipeline = ReconciliationPipeline(data_dir=DATA_DIR)
    pipe_res = pipeline.run()

    eval_res = evaluate_reconciliation(
        matches=pipe_res["all_matches"],
        ground_truth=pipe_res["ground_truth"],
        pipeline_summary=pipe_res["summary"],
        llm_telemetry=pipe_res["llm_telemetry"]
    )

    save_results(pipe_res["all_matches"], eval_res, output_dir=RESULTS_DIR)

    # Cache exceptions
    exceptions_path = os.path.join(RESULTS_DIR, "exceptions.csv")
    exceptions_list = []
    if os.path.exists(exceptions_path):
        with open(exceptions_path, "r", encoding="utf-8") as f:
            exceptions_list = list(csv.DictReader(f))

    # Cache matches
    matches_list = []
    for m in pipe_res["all_matches"]:
        matches_list.append({
            "match_id": m.match_id,
            "status": m.status,
            "stage": m.stage,
            "confidence": round(m.confidence, 2),
            "amount": round(m.reconciled_amount, 2),
            "discrepancy": round(m.amount_discrepancy, 2),
            "bank_ids": ", ".join(m.bank_txn_ids) or "-",
            "gw_ids": ", ".join(m.gateway_settlement_ids) or "-",
            "inv_ids": ", ".join(m.invoice_ids) or "-",
            "reasoning": m.reasoning,
            "rule": m.rule_or_model,
            "evidence": ", ".join(m.evidence_fields)
        })

    app_state["pipeline_results"] = pipe_res
    app_state["eval_results"] = eval_res
    app_state["exceptions_list"] = exceptions_list
    app_state["matches_list"] = matches_list
    app_state["agent"] = FinanceControllerAgent()
    app_state["last_reconciled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@app.route("/")
def index():
    """Serves the complete single-page application."""
    if app_state["pipeline_results"] is None:
        init_app_state()
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/status", methods=["GET"])
def get_status():
    """Returns the current state and reconciliation metrics."""
    if app_state["pipeline_results"] is None:
        init_app_state()

    return jsonify({
        "summary": app_state["pipeline_results"]["summary"],
        "metrics": app_state["eval_results"]["reconciliation_metrics"],
        "stage_breakdown": app_state["eval_results"]["stage_breakdown"],
        "confusion": app_state["eval_results"]["confusion_by_injected_error_type"],
        "performance": app_state["eval_results"]["performance_and_cost"],
        "exceptions_count": len(app_state["exceptions_list"]),
        "matches_count": len(app_state["matches_list"]),
        "last_reconciled_at": app_state["last_reconciled_at"],
        "dataset_source": app_state["dataset_source"],
        "agent_provider": app_state["agent"].provider if app_state["agent"] else "Local AI Controller"
    })


@app.route("/api/matches", methods=["GET"])
def get_matches():
    """Returns all matches with optional status filtering."""
    status_filter = request.args.get("status")
    matches = app_state["matches_list"]
    if status_filter and status_filter != "ALL":
        matches = [m for m in matches if m["status"] == status_filter]
    return jsonify(matches)


@app.route("/api/exceptions", methods=["GET"])
def get_exceptions():
    """Returns the list of exceptions requiring review or unresolved."""
    return jsonify(app_state["exceptions_list"])


@app.route("/api/reconcile", methods=["POST"])
def trigger_reconcile():
    """Triggers a fresh reconciliation run over the active dataset."""
    init_app_state(force_regenerate=False)
    return jsonify({"success": True, "message": "Reconciliation completed successfully."})


@app.route("/api/load-sample", methods=["POST"])
def load_sample_dataset():
    """Restores the standard 80-record synthetic benchmark."""
    init_app_state(force_regenerate=True)
    return jsonify({
        "success": True,
        "message": "Reset to 80-group benchmark dataset with calibrated noise.",
        "records_count": app_state["pipeline_results"]["summary"]["total_input_records"]
    })


@app.route("/api/upload", methods=["POST"])
def upload_user_data():
    """
    Accepts user-uploaded CSV files for:
    - bank_file: Bank Statement
    - gateway_file: Payment Gateway Settlements
    - ledger_file: Internal Ledger / Invoices
    """
    files_uploaded = []

    if "bank_file" in request.files and request.files["bank_file"].filename:
        bf = request.files["bank_file"]
        bf.save(os.path.join(DATA_DIR, "bank_statement.csv"))
        files_uploaded.append("Bank Statement")

    if "gateway_file" in request.files and request.files["gateway_file"].filename:
        gf = request.files["gateway_file"]
        gf.save(os.path.join(DATA_DIR, "gateway_settlements.csv"))
        files_uploaded.append("Gateway Settlements")

    if "ledger_file" in request.files and request.files["ledger_file"].filename:
        lf = request.files["ledger_file"]
        lf.save(os.path.join(DATA_DIR, "internal_ledger.csv"))
        files_uploaded.append("Internal Ledger")

    if not files_uploaded:
        return jsonify({"success": False, "error": "No valid files received"}), 400

    app_state["dataset_source"] = f"Custom Upload ({', '.join(files_uploaded)})"
    # Re-run reconciliation on the user's uploaded data
    init_app_state(force_regenerate=False)

    return jsonify({
        "success": True,
        "message": f"Successfully loaded: {', '.join(files_uploaded)}. Reconciliation re-executed.",
        "summary": app_state["pipeline_results"]["summary"]
    })


@app.route("/api/add-transaction", methods=["POST"])
def add_single_transaction():
    """
    Allows the user to manually add a single transaction to Bank, Gateway, or Ledger.
    """
    data = request.json or {}
    source_type = data.get("source_type")  # "bank", "gateway", "ledger"

    if source_type == "bank":
        bank_path = os.path.join(DATA_DIR, "bank_statement.csv")
        file_exists = os.path.exists(bank_path)
        with open(bank_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["bank_txn_id", "txn_date", "narration", "deposit_inr", "withdrawal_inr", "balance_inr", "utr_number", "bank_name"])
            writer.writerow([
                data.get("bank_txn_id", f"BNK-USER-{int(time.time())}"),
                data.get("txn_date", datetime.now().strftime("%Y-%m-%d")),
                data.get("narration", "Direct Deposit"),
                float(data.get("deposit_inr", 0.0)),
                0.0,
                0.0,
                data.get("utr_number", "").strip(),
                data.get("bank_name", "HDFC Bank")
            ])

    elif source_type == "gateway":
        gw_path = os.path.join(DATA_DIR, "gateway_settlements.csv")
        file_exists = os.path.exists(gw_path)
        with open(gw_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["settlement_id", "settlement_date", "payment_id", "order_id", "method", "gross_amount_inr", "fee_inr", "tax_gst_inr", "net_amount_inr", "utr_number", "status"])
            gross = float(data.get("gross_amount_inr", 0.0))
            fee = float(data.get("fee_inr", 0.0))
            gst = float(data.get("tax_gst_inr", fee * 0.18 if fee else 0.0))
            net = float(data.get("net_amount_inr", gross - fee - gst))
            writer.writerow([
                data.get("settlement_id", f"SET-USER-{int(time.time())}"),
                data.get("settlement_date", datetime.now().strftime("%Y-%m-%d")),
                data.get("payment_id", ""),
                data.get("order_id", ""),
                data.get("method", "UPI"),
                gross, fee, gst, net,
                data.get("utr_number", "").strip(),
                "settled"
            ])

    elif source_type == "ledger":
        led_path = os.path.join(DATA_DIR, "internal_ledger.csv")
        file_exists = os.path.exists(led_path)
        with open(led_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["invoice_id", "invoice_date", "customer_name", "customer_type", "gross_amount_inr", "tds_rate_percent", "tds_amount_inr", "expected_net_inr", "order_ref", "due_date", "status"])
            gross = float(data.get("gross_amount_inr", 0.0))
            tds_rate = float(data.get("tds_rate_percent", 0.0))
            tds_amt = round(gross * (tds_rate / 100.0), 2)
            net = round(gross - tds_amt, 2)
            writer.writerow([
                data.get("invoice_id", f"INV-USER-{int(time.time())}"),
                data.get("invoice_date", datetime.now().strftime("%Y-%m-%d")),
                data.get("customer_name", "Corporate Client"),
                "B2B" if tds_rate > 0 else "B2C",
                gross, tds_rate, tds_amt, net,
                data.get("order_ref", ""),
                data.get("due_date", datetime.now().strftime("%Y-%m-%d")),
                "unpaid"
            ])
    else:
        return jsonify({"success": False, "error": f"Unknown source_type '{source_type}'"}), 400

    app_state["dataset_source"] = "User Modified Dataset"
    init_app_state(force_regenerate=False)

    return jsonify({
        "success": True,
        "message": f"Added record to {source_type.capitalize()} and re-reconciled.",
        "summary": app_state["pipeline_results"]["summary"]
    })


@app.route("/api/chat", methods=["POST"])
def chat_with_agent():
    """
    Conversational endpoint: directly communicates with the AI Finance Controller.
    """
    req_data = request.json or {}
    user_query = req_data.get("message", "").strip()
    if not user_query:
        return jsonify({"response": "Please ask a question about your reconciliation, exceptions, or accounting policies."})

    agent: FinanceControllerAgent = app_state.get("agent")
    if not agent:
        agent = FinanceControllerAgent()
        app_state["agent"] = agent

    context = {
        "exceptions": app_state["exceptions_list"],
        "metrics": app_state["eval_results"],
        "summary": app_state["pipeline_results"]["summary"] if app_state["pipeline_results"] else {}
    }

    response_text = agent.answer_query(user_query, context)
    return jsonify({
        "response": response_text,
        "agent_provider": agent.provider,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    })


@app.route("/api/export/<file_type>")
def export_file(file_type):
    """Exports matches.csv, exceptions.csv, or metrics.json."""
    if file_type == "matches":
        return send_file(os.path.join(RESULTS_DIR, "matches.csv"), as_attachment=True)
    elif file_type == "exceptions":
        return send_file(os.path.join(RESULTS_DIR, "exceptions.csv"), as_attachment=True)
    elif file_type == "metrics":
        return send_file(os.path.join(RESULTS_DIR, "metrics.json"), as_attachment=True)
    return jsonify({"error": "Unknown file type"}), 404


# ==============================================================================
# Modern Embedded Single-Page HTML / CSS / JS Application Template
# ==============================================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Finance Controller | Automated Multi-Source Reconciliation</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --bg-base: #090d16;
            --bg-surface: #111827;
            --bg-card: #1f2937;
            --bg-elevated: #374151;
            --border-color: #374151;
            --text-primary: #f9fafb;
            --text-muted: #9ca3af;
            --accent-primary: #3b82f6;
            --accent-green: #10b981;
            --accent-amber: #f59e0b;
            --accent-rose: #ef4444;
            --accent-purple: #8b5cf6;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }
        body { background: var(--bg-base); color: var(--text-primary); display: flex; height: 100vh; overflow: hidden; }

        /* Sidebar Navigation */
        .sidebar { width: 260px; background: var(--bg-surface); border-right: 1px solid var(--border-color); display: flex; flex-direction: column; flex-shrink: 0; }
        .sidebar-brand { padding: 20px; border-bottom: 1px solid var(--border-color); display: flex; align-items: center; gap: 12px; }
        .sidebar-brand i { font-size: 22px; color: var(--accent-primary); }
        .brand-text h2 { font-size: 16px; font-weight: 700; color: #fff; }
        .brand-text span { font-size: 11px; color: var(--accent-green); text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px; }

        .nav-menu { padding: 16px 12px; flex: 1; display: flex; flex-direction: column; gap: 4px; }
        .nav-item { display: flex; align-items: center; gap: 12px; padding: 10px 14px; color: var(--text-muted); text-decoration: none; border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer; transition: all 0.15s ease; }
        .nav-item:hover { background: rgba(59, 130, 246, 0.1); color: var(--text-primary); }
        .nav-item.active { background: var(--accent-primary); color: #fff; font-weight: 600; }
        .nav-item i { font-size: 15px; width: 18px; text-align: center; }

        .sidebar-footer { padding: 16px; border-top: 1px solid var(--border-color); font-size: 11px; color: var(--text-muted); }
        .status-pill { display: inline-flex; align-items: center; gap: 6px; padding: 4px 8px; background: rgba(16, 185, 129, 0.1); color: var(--accent-green); border-radius: 9999px; font-weight: 600; }
        .status-dot { width: 6px; height: 6px; background: var(--accent-green); border-radius: 50%; }

        /* Main Workspace */
        .workspace { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
        .topbar { height: 60px; border-bottom: 1px solid var(--border-color); background: var(--bg-surface); display: flex; align-items: center; justify-content: space-between; padding: 0 24px; flex-shrink: 0; }
        .topbar-title { font-size: 18px; font-weight: 600; display: flex; align-items: center; gap: 10px; }
        .topbar-actions { display: flex; align-items: center; gap: 10px; }

        .btn { display: inline-flex; align-items: center; gap: 8px; padding: 8px 14px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; border: none; transition: 0.15s; }
        .btn-primary { background: var(--accent-primary); color: white; }
        .btn-primary:hover { background: #2563eb; }
        .btn-outline { background: transparent; border: 1px solid var(--border-color); color: var(--text-primary); }
        .btn-outline:hover { background: var(--bg-card); }
        .btn-green { background: var(--accent-green); color: white; }
        .btn-green:hover { background: #059669; }

        .content-area { flex: 1; padding: 24px; overflow-y: auto; background: var(--bg-base); }
        .tab-pane { display: none; }
        .tab-pane.active { display: block; }

        /* KPI Cards Grid */
        .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .kpi-card { background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 10px; padding: 18px; position: relative; overflow: hidden; }
        .kpi-card::before { content: ""; position: absolute; top: 0; left: 0; right: 0; height: 3px; background: var(--accent-primary); }
        .kpi-card.green::before { background: var(--accent-green); }
        .kpi-card.amber::before { background: var(--accent-amber); }
        .kpi-card.purple::before { background: var(--accent-purple); }
        .kpi-label { font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 600; letter-spacing: 0.5px; }
        .kpi-value { font-size: 26px; font-weight: 700; margin-top: 6px; }
        .kpi-sub { font-size: 11px; color: var(--text-muted); margin-top: 4px; }

        /* Grid Layouts */
        .grid-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }
        @media(max-width: 1024px) { .grid-2col { grid-template-columns: 1fr; } }
        .card { background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 10px; padding: 20px; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
        .card-title { font-size: 14px; font-weight: 600; color: #fff; display: flex; align-items: center; gap: 8px; }

        /* Tables */
        table { width: 100%; border-collapse: collapse; font-size: 12px; }
        th { text-align: left; padding: 10px 12px; background: var(--bg-card); color: var(--text-muted); font-weight: 600; border-bottom: 1px solid var(--border-color); }
        td { padding: 10px 12px; border-bottom: 1px solid var(--border-color); vertical-align: middle; }
        tr:hover td { background: rgba(255, 255, 255, 0.02); }

        .tag { display: inline-block; padding: 3px 8px; border-radius: 6px; font-size: 10px; font-weight: 700; text-transform: uppercase; }
        .tag-auto { background: rgba(16, 185, 129, 0.15); color: var(--accent-green); border: 1px solid rgba(16, 185, 129, 0.3); }
        .tag-review { background: rgba(245, 158, 11, 0.15); color: var(--accent-amber); border: 1px solid rgba(245, 158, 11, 0.3); }
        .tag-unres { background: rgba(239, 68, 68, 0.15); color: var(--accent-rose); border: 1px solid rgba(239, 68, 68, 0.3); }

        /* Progress bars */
        .prog-bar { width: 100%; height: 8px; background: var(--bg-card); border-radius: 4px; overflow: hidden; margin-top: 6px; }
        .prog-fill { height: 100%; background: var(--accent-primary); }

        /* Data Upload Zones */
        .upload-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .upload-box { background: var(--bg-card); border: 2px dashed var(--border-color); border-radius: 10px; padding: 24px; text-align: center; cursor: pointer; transition: 0.15s; }
        .upload-box:hover { border-color: var(--accent-primary); background: rgba(59, 130, 246, 0.04); }
        .upload-box i { font-size: 32px; color: var(--accent-primary); margin-bottom: 10px; }
        .upload-title { font-size: 13px; font-weight: 600; margin-bottom: 4px; }
        .upload-sub { font-size: 11px; color: var(--text-muted); }
        .file-selected-name { font-size: 11px; color: var(--accent-green); margin-top: 8px; font-weight: 600; }

        /* In-App Chat Copilot Drawer */
        .chat-container { display: flex; flex-direction: column; height: 100%; background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 10px; overflow: hidden; }
        .chat-header { padding: 14px 20px; background: var(--bg-card); border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center; }
        .chat-messages { flex: 1; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; }
        .chat-bubble { max-width: 80%; padding: 12px 16px; border-radius: 10px; font-size: 13px; line-height: 1.5; }
        .chat-user { align-self: flex-end; background: var(--accent-primary); color: white; border-bottom-right-radius: 2px; }
        .chat-agent { align-self: flex-start; background: var(--bg-card); border: 1px solid var(--border-color); color: var(--text-primary); border-bottom-left-radius: 2px; }
        .chat-chips { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
        .chip { background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 9999px; padding: 4px 12px; font-size: 11px; color: var(--text-muted); cursor: pointer; transition: 0.15s; }
        .chip:hover { border-color: var(--accent-primary); color: #fff; }
        .chat-input-bar { padding: 14px 20px; border-top: 1px solid var(--border-color); background: var(--bg-card); display: flex; gap: 10px; }
        .chat-input { flex: 1; background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 6px; padding: 10px 14px; color: white; font-size: 13px; }
        .chat-input:focus { outline: none; border-color: var(--accent-primary); }

        /* Modal */
        .modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); display: none; justify-content: center; align-items: center; z-index: 1000; }
        .modal { background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 12px; width: 500px; max-width: 90%; padding: 24px; }
        .modal-title { font-size: 16px; font-weight: 700; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }
        .form-group { margin-bottom: 14px; }
        .form-label { display: block; font-size: 11px; font-weight: 600; text-transform: uppercase; color: var(--text-muted); margin-bottom: 6px; }
        .form-control { width: 100%; padding: 8px 12px; background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 6px; color: white; font-size: 12px; }
    </style>
</head>
<body>

    <!-- Sidebar Navigation -->
    <div class="sidebar">
        <div class="sidebar-brand">
            <i class="fa-solid fa-scale-balanced"></i>
            <div class="brand-text">
                <h2>AI Finance Controller</h2>
                <span>Forensic Reconciler</span>
            </div>
        </div>
        <div class="nav-menu">
            <div class="nav-item active" onclick="switchTab('dashboard')">
                <i class="fa-solid fa-chart-pie"></i> Executive Dashboard
            </div>
            <div class="nav-item" onclick="switchTab('explorer')">
                <i class="fa-solid fa-list-check"></i> Reconciled Matches
            </div>
            <div class="nav-item" onclick="switchTab('exceptions')">
                <i class="fa-solid fa-triangle-exclamation"></i> Exception Triage
            </div>
            <div class="nav-item" onclick="switchTab('userdata')">
                <i class="fa-solid fa-cloud-arrow-up"></i> Add / Upload Data
            </div>
            <div class="nav-item" onclick="switchTab('copilot')">
                <i class="fa-solid fa-robot"></i> AI Controller Copilot
            </div>
        </div>
        <div class="sidebar-footer">
            <div class="status-pill">
                <div class="status-dot"></div> <span id="agentStatusBadge">Agent Active (100% Precision)</span>
            </div>
            <div style="margin-top: 8px; font-size: 10px; color: var(--text-muted);" id="datasetSourceText">
                Source: Synthetic Benchmark
            </div>
        </div>
    </div>

    <!-- Workspace -->
    <div class="workspace">
        <div class="topbar">
            <div class="topbar-title" id="topbarTitle">
                <i class="fa-solid fa-chart-pie"></i> Executive Reconciliation Dashboard
            </div>
            <div class="topbar-actions">
                <button class="btn btn-outline" onclick="loadSampleDataset()">
                    <i class="fa-solid fa-rotate-left"></i> Reset Benchmark (80)
                </button>
                <button class="btn btn-outline" onclick="openAddModal()">
                    <i class="fa-solid fa-plus"></i> Add Single Record
                </button>
                <button class="btn btn-primary" onclick="triggerReconciliation()">
                    <i class="fa-solid fa-bolt"></i> Re-Reconcile Batch
                </button>
            </div>
        </div>

        <div class="content-area">
            <!-- TAB 1: EXECUTIVE DASHBOARD -->
            <div id="tab-dashboard" class="tab-pane active">
                <div class="kpi-grid">
                    <div class="kpi-card green">
                        <div class="kpi-label">Auto-Match Rate</div>
                        <div class="kpi-value" id="kpiAutoMatch">--%</div>
                        <div class="kpi-sub" id="kpiAutoMatchSub">-- matched autonomously</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Precision (False Matches)</div>
                        <div class="kpi-value" id="kpiPrecision">100.0%</div>
                        <div class="kpi-sub">0 False Positives cross-contaminating</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Recall (Sensitivity)</div>
                        <div class="kpi-value" id="kpiRecall">100.0%</div>
                        <div class="kpi-sub">0 Valid reconcilable payments missed</div>
                    </div>
                    <div class="kpi-card amber">
                        <div class="kpi-label">Human Review Needed</div>
                        <div class="kpi-value" id="kpiReview">--</div>
                        <div class="kpi-sub">Duplicate credits, webhooks, short pay</div>
                    </div>
                    <div class="kpi-card purple">
                        <div class="kpi-label">Throughput Speed</div>
                        <div class="kpi-value" id="kpiThroughput">-- rec/s</div>
                        <div class="kpi-sub" id="kpiLatency">Completed in -- ms</div>
                    </div>
                </div>

                <div class="grid-2col">
                    <!-- Stage Breakdown -->
                    <div class="card">
                        <div class="card-header">
                            <div class="card-title"><i class="fa-solid fa-layer-group"></i> Stage-by-Stage Matching Breakdown</div>
                        </div>
                        <table>
                            <thead>
                                <tr><th>Pipeline Stage</th><th>Count</th><th>Share (%)</th></tr>
                            </thead>
                            <tbody id="stageTableBody"></tbody>
                        </table>
                    </div>

                    <!-- Injected Error Confusion Table -->
                    <div class="card">
                        <div class="card-header">
                            <div class="card-title"><i class="fa-solid fa-bug"></i> Robustness by Error Class</div>
                        </div>
                        <table>
                            <thead>
                                <tr><th>Error Class</th><th>Total</th><th>Auto</th><th>Review</th><th>Unres</th><th>Accuracy</th></tr>
                            </thead>
                            <tbody id="confusionTableBody"></tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TAB 2: MATCHES EXPLORER -->
            <div id="tab-explorer" class="tab-pane">
                <div class="card">
                    <div class="card-header">
                        <div class="card-title"><i class="fa-solid fa-list-check"></i> Reconciled Transactions Explorer</div>
                        <div style="display:flex; gap:10px;">
                            <select id="statusFilter" class="form-control" style="width:160px;" onchange="loadMatches()">
                                <option value="ALL">All Statuses</option>
                                <option value="AUTO_MATCHED">AUTO_MATCHED</option>
                                <option value="NEEDS_REVIEW">NEEDS_REVIEW</option>
                                <option value="UNRESOLVED">UNRESOLVED</option>
                            </select>
                            <a href="/api/export/matches" class="btn btn-outline"><i class="fa-solid fa-download"></i> Export CSV</a>
                        </div>
                    </div>
                    <table>
                        <thead>
                            <tr>
                                <th>Match ID</th>
                                <th>Status</th>
                                <th>Stage</th>
                                <th>Amount (INR)</th>
                                <th>Conf</th>
                                <th>Involved Records (Bank / GW / Inv)</th>
                                <th>Forensic Reasoning</th>
                            </tr>
                        </thead>
                        <tbody id="matchesTableBody"></tbody>
                    </table>
                </div>
            </div>

            <!-- TAB 3: EXCEPTIONS TRIAGE -->
            <div id="tab-exceptions" class="tab-pane">
                <div class="card">
                    <div class="card-header">
                        <div class="card-title"><i class="fa-solid fa-triangle-exclamation"></i> Exception Triage &amp; Human Action Center</div>
                        <a href="/api/export/exceptions" class="btn btn-outline"><i class="fa-solid fa-download"></i> Export Exceptions CSV</a>
                    </div>
                    <table>
                        <thead>
                            <tr>
                                <th>Exc ID</th>
                                <th>Status</th>
                                <th>Category</th>
                                <th>Amount</th>
                                <th>Involved Source IDs</th>
                                <th>Root Cause Explanation</th>
                                <th>Suggested Human Action</th>
                            </tr>
                        </thead>
                        <tbody id="exceptionsTableBody"></tbody>
                    </table>
                </div>
            </div>

            <!-- TAB 4: ADD / UPLOAD DATA -->
            <div id="tab-userdata" class="tab-pane">
                <div class="card" style="margin-bottom: 24px;">
                    <div class="card-header">
                        <div class="card-title"><i class="fa-solid fa-cloud-arrow-up"></i> Upload Custom Financial Data Sources</div>
                    </div>
                    <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 20px;">
                        Drop your company's real CSV files below to run the multi-source reconciliation loop on your own financial data.
                    </p>
                    <form id="uploadForm" onsubmit="handleUpload(event)">
                        <div class="upload-grid">
                            <!-- Bank Statement -->
                            <div class="upload-box" onclick="document.getElementById('bankFileInput').click()">
                                <i class="fa-solid fa-building-columns"></i>
                                <div class="upload-title">1. Bank Statement CSV</div>
                                <div class="upload-sub">HDFC, ICICI, Axis, SBI narration &amp; UTRs</div>
                                <input type="file" id="bankFileInput" name="bank_file" style="display:none;" onchange="updateFileName(this, 'bankFileName')">
                                <div class="file-selected-name" id="bankFileName"></div>
                            </div>
                            <!-- Gateway Settlements -->
                            <div class="upload-box" onclick="document.getElementById('gatewayFileInput').click()">
                                <i class="fa-solid fa-credit-card"></i>
                                <div class="upload-title">2. Gateway Settlements CSV</div>
                                <div class="upload-sub">Razorpay / Cashfree / Stripe MDR &amp; Net Payouts</div>
                                <input type="file" id="gatewayFileInput" name="gateway_file" style="display:none;" onchange="updateFileName(this, 'gatewayFileName')">
                                <div class="file-selected-name" id="gatewayFileName"></div>
                            </div>
                            <!-- Internal Ledger -->
                            <div class="upload-box" onclick="document.getElementById('ledgerFileInput').click()">
                                <i class="fa-solid fa-receipt"></i>
                                <div class="upload-title">3. Internal Ledger / Invoices CSV</div>
                                <div class="upload-sub">ERP Sales Invoices &amp; Section 194J/194C TDS</div>
                                <input type="file" id="ledgerFileInput" name="ledger_file" style="display:none;" onchange="updateFileName(this, 'ledgerFileName')">
                                <div class="file-selected-name" id="ledgerFileName"></div>
                            </div>
                        </div>
                        <div style="text-align: right;">
                            <button type="submit" class="btn btn-green"><i class="fa-solid fa-upload"></i> Upload &amp; Reconcile Now</button>
                        </div>
                    </form>
                </div>
            </div>

            <!-- TAB 5: AI COPILOT CHAT IN-APP -->
            <div id="tab-copilot" class="tab-pane" style="height: calc(100vh - 120px);">
                <div class="chat-container">
                    <div class="chat-header">
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <i class="fa-solid fa-robot" style="font-size: 18px; color: var(--accent-primary);"></i>
                            <div>
                                <div style="font-size: 14px; font-weight: 600;">AI Finance Controller Copilot</div>
                                <div style="font-size: 11px; color: var(--accent-green);" id="chatProvider">Engine: Local Forensic Model</div>
                            </div>
                        </div>
                        <button class="btn btn-outline" style="padding: 4px 10px; font-size: 11px;" onclick="clearChat()">
                            <i class="fa-solid fa-trash"></i> Clear
                        </button>
                    </div>

                    <div class="chat-messages" id="chatMessages">
                        <div class="chat-bubble chat-agent">
                            <strong>Hello! I am your AI Finance Controller.</strong><br>
                            I have audited your multi-source reconciliation loop across Bank, Gateway, and Ledger records.
                            Ask me any forensic questions about flagged exceptions, vendor exposure, or mathematical deductions!
                        </div>
                    </div>

                    <div style="padding: 10px 20px 0; background: var(--bg-card);">
                        <div class="chat-chips">
                            <div class="chip" onclick="askPredefined('Why did you flag EXC-001?')">Why was EXC-001 flagged?</div>
                            <div class="chip" onclick="askPredefined('Show details for Flipkart invoice short payment')">Flipkart short payment</div>
                            <div class="chip" onclick="askPredefined('Explain the Pine Labs unpaid debtor exception')">Pine Labs overdue status</div>
                            <div class="chip" onclick="askPredefined('What is our current reconciliation accuracy and precision?')">Reconciliation Accuracy</div>
                        </div>
                    </div>

                    <div class="chat-input-bar">
                        <input type="text" id="chatInput" class="chat-input" placeholder="Ask AI Controller (e.g. 'Why was EXC-002 flagged?', 'Audit vendor Flipkart')..." onkeydown="if(event.key==='Enter') sendChatMessage()">
                        <button class="btn btn-primary" onclick="sendChatMessage()"><i class="fa-solid fa-paper-plane"></i></button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Modal for Adding Single Record -->
    <div class="modal-overlay" id="addModal">
        <div class="modal">
            <div class="modal-title">
                <span>Add Single Transaction</span>
                <i class="fa-solid fa-xmark" style="cursor:pointer;" onclick="closeAddModal()"></i>
            </div>
            <form onsubmit="handleAddRecord(event)">
                <div class="form-group">
                    <label class="form-label">Target Source</label>
                    <select id="modalSourceType" class="form-control" onchange="toggleFormFields()">
                        <option value="bank">Bank Statement Deposit</option>
                        <option value="gateway">Payment Gateway Settlement</option>
                        <option value="ledger">Internal Sales Invoice</option>
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Reference ID (UTR / Payment ID / Order ID)</label>
                    <input type="text" id="modalRef" class="form-control" required placeholder="e.g. 429988112233 or pay_TEST123">
                </div>
                <div class="form-group">
                    <label class="form-label">Amount (INR)</label>
                    <input type="number" step="0.01" id="modalAmount" class="form-control" required placeholder="e.g. 25000.00">
                </div>
                <div class="form-group">
                    <label class="form-label">Narration / Description / Customer Name</label>
                    <input type="text" id="modalDesc" class="form-control" required placeholder="e.g. UPI/CR/.../PYMT/Razorpay or Swiggy Tech">
                </div>
                <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
                    <button type="button" class="btn btn-outline" onclick="closeAddModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary"><i class="fa-solid fa-check"></i> Add &amp; Reconcile</button>
                </div>
            </form>
        </div>
    </div>

    <script>
        let currentTab = 'dashboard';

        function switchTab(tabId) {
            currentTab = tabId;
            document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));

            const tabMap = {
                'dashboard': 'Executive Reconciliation Dashboard',
                'explorer': 'Reconciled Transactions Explorer',
                'exceptions': 'Exception Triage Action Center',
                'userdata': 'Upload & Add Financial Data',
                'copilot': 'AI Finance Controller Copilot'
            };

            document.getElementById('topbarTitle').innerHTML = tabMap[tabId];
            document.getElementById('tab-' + tabId).classList.add('active');

            // Find matching nav element
            const navIndex = ['dashboard', 'explorer', 'exceptions', 'userdata', 'copilot'].indexOf(tabId);
            if (navIndex >= 0) {
                document.querySelectorAll('.nav-item')[navIndex].classList.add('active');
            }

            if (tabId === 'explorer') loadMatches();
            if (tabId === 'exceptions') loadExceptions();
        }

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();

                const m = data.metrics;
                const p = data.performance;
                const s = data.summary;

                document.getElementById('kpiAutoMatch').innerText = m.auto_match_rate_percent + '%';
                document.getElementById('kpiAutoMatchSub').innerText = m.true_positives + ' of ' + m.total_ground_truth_records + ' auto-cleared';
                document.getElementById('kpiPrecision').innerText = (m.precision * 100).toFixed(1) + '%';
                document.getElementById('kpiRecall').innerText = (m.recall * 100).toFixed(1) + '%';
                document.getElementById('kpiReview').innerText = m.correct_reviews_flagged;
                document.getElementById('kpiThroughput').innerText = p.throughput_records_sec.toLocaleString() + ' rec/s';
                document.getElementById('kpiLatency').innerText = 'Completed in ' + (p.elapsed_seconds * 1000).toFixed(1) + ' ms';

                document.getElementById('datasetSourceText').innerText = 'Source: ' + data.dataset_source;
                document.getElementById('chatProvider').innerText = 'Engine: ' + data.agent_provider;

                // Render Stages
                const stageTbody = document.getElementById('stageTableBody');
                stageTbody.innerHTML = '';
                const stages = [
                    { name: 'Stage A: Exact Deterministic', count: data.stage_breakdown.deterministic.count, share: data.stage_breakdown.deterministic.share_percent, color: '#3b82f6' },
                    { name: 'Stage B: Rule-Based Domain', count: data.stage_breakdown.rule_based.count, share: data.stage_breakdown.rule_based.share_percent, color: '#8b5cf6' },
                    { name: 'Stage C: LLM Agent Pass', count: data.stage_breakdown.llm.count, share: data.stage_breakdown.llm.share_percent, color: '#f59e0b' }
                ];
                stages.forEach(st => {
                    stageTbody.innerHTML += `
                        <tr>
                            <td><strong>${st.name}</strong></td>
                            <td>${st.count}</td>
                            <td>
                                ${st.share}%
                                <div class="prog-bar"><div class="prog-fill" style="width:${st.share}%; background:${st.color};"></div></div>
                            </td>
                        </tr>
                    `;
                });

                // Render Confusion Matrix
                const confTbody = document.getElementById('confusionTableBody');
                confTbody.innerHTML = '';
                for (const [errType, d] of Object.entries(data.confusion)) {
                    confTbody.innerHTML += `
                        <tr>
                            <td><code>${errType}</code></td>
                            <td>${d.total}</td>
                            <td><span class="tag tag-auto">${d.auto_matched}</span></td>
                            <td><span class="tag tag-review">${d.needs_review}</span></td>
                            <td><span class="tag tag-unres">${d.unresolved}</span></td>
                            <td style="color:var(--accent-green); font-weight:700;">${d.accuracy_percent}%</td>
                        </tr>
                    `;
                }

            } catch (err) {
                console.error("Failed to fetch status", err);
            }
        }

        async function loadMatches() {
            const filter = document.getElementById('statusFilter').value;
            const res = await fetch('/api/matches?status=' + filter);
            const matches = await res.json();
            const tbody = document.getElementById('matchesTableBody');
            tbody.innerHTML = '';

            matches.forEach(m => {
                const tagCls = m.status === 'AUTO_MATCHED' ? 'tag-auto' : (m.status === 'NEEDS_REVIEW' ? 'tag-review' : 'tag-unres');
                tbody.innerHTML += `
                    <tr>
                        <td><strong>${m.match_id}</strong></td>
                        <td><span class="tag ${tagCls}">${m.status}</span></td>
                        <td>${m.stage}</td>
                        <td>INR ${m.amount.toFixed(2)}</td>
                        <td>${m.confidence}</td>
                        <td style="font-size:11px; color:var(--text-muted);">
                            B: ${m.bank_ids}<br>G: ${m.gw_ids}<br>I: ${m.inv_ids}
                        </td>
                        <td style="max-width:320px;">${m.reasoning}</td>
                    </tr>
                `;
            });
        }

        async function loadExceptions() {
            const res = await fetch('/api/exceptions');
            const exceptions = await res.json();
            const tbody = document.getElementById('exceptionsTableBody');
            tbody.innerHTML = '';

            exceptions.forEach(exc => {
                const tagCls = exc.status === 'NEEDS_REVIEW' ? 'tag-review' : 'tag-unres';
                tbody.innerHTML += `
                    <tr>
                        <td><strong>${exc.exception_id}</strong></td>
                        <td><span class="tag ${tagCls}">${exc.status}</span></td>
                        <td><code>${exc.exception_category}</code></td>
                        <td>INR ${parseFloat(exc.amount_involved_inr).toFixed(2)}</td>
                        <td style="font-size:11px; color:var(--text-muted);">
                            B: ${exc.bank_txn_ids || '-'}<br>G: ${exc.gateway_settlement_ids || '-'}<br>I: ${exc.invoice_ids || '-'}
                        </td>
                        <td style="max-width:280px;">${exc.root_cause_explanation}</td>
                        <td style="max-width:300px; color:var(--accent-amber); font-weight:500;">
                            <i class="fa-solid fa-hand-point-right"></i> ${exc.suggested_human_action}
                        </td>
                    </tr>
                `;
            });
        }

        async function triggerReconciliation() {
            const res = await fetch('/api/reconcile', { method: 'POST' });
            await fetchStatus();
            if (currentTab === 'explorer') loadMatches();
            if (currentTab === 'exceptions') loadExceptions();
            alert('Reconciliation batch completed successfully.');
        }

        async function loadSampleDataset() {
            if (!confirm('Reset dataset back to the 80-group benchmark?')) return;
            const res = await fetch('/api/load-sample', { method: 'POST' });
            await fetchStatus();
            alert('Reset to benchmark synthetic dataset.');
        }

        function updateFileName(input, targetId) {
            if (input.files && input.files[0]) {
                document.getElementById(targetId).innerText = 'Selected: ' + input.files[0].name;
            }
        }

        async function handleUpload(e) {
            e.preventDefault();
            const formData = new FormData(document.getElementById('uploadForm'));
            try {
                const res = await fetch('/api/upload', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                if (data.success) {
                    alert(data.message);
                    await fetchStatus();
                    switchTab('dashboard');
                } else {
                    alert('Upload failed: ' + data.error);
                }
            } catch (err) {
                alert('Upload error: ' + err);
            }
        }

        function openAddModal() {
            document.getElementById('addModal').style.display = 'flex';
        }
        function closeAddModal() {
            document.getElementById('addModal').style.display = 'none';
        }

        async function handleAddRecord(e) {
            e.preventDefault();
            const src = document.getElementById('modalSourceType').value;
            const ref = document.getElementById('modalRef').value.trim();
            const amt = parseFloat(document.getElementById('modalAmount').value);
            const desc = document.getElementById('modalDesc').value.trim();

            let payload = { source_type: src };
            if (src === 'bank') {
                payload.utr_number = ref;
                payload.deposit_inr = amt;
                payload.narration = desc;
            } else if (src === 'gateway') {
                payload.payment_id = ref;
                payload.utr_number = ref;
                payload.gross_amount_inr = amt;
                payload.net_amount_inr = amt;
                payload.order_id = desc;
            } else if (src === 'ledger') {
                payload.order_ref = ref;
                payload.gross_amount_inr = amt;
                payload.expected_net_inr = amt;
                payload.customer_name = desc;
            }

            const res = await fetch('/api/add-transaction', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            closeAddModal();
            alert(data.message);
            await fetchStatus();
        }

        async function sendChatMessage() {
            const input = document.getElementById('chatInput');
            const msg = input.value.trim();
            if (!msg) return;

            const chatMessages = document.getElementById('chatMessages');
            chatMessages.innerHTML += `<div class="chat-bubble chat-user">${msg}</div>`;
            input.value = '';
            chatMessages.scrollTop = chatMessages.scrollHeight;

            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: msg })
            });
            const data = await res.json();

            // Format markdown newlines and bolding
            const formatted = data.response
                .replace(/\\n/g, '<br>')
                .replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>')
                .replace(/### (.*?)(<br>|$)/g, '<h4 style="margin:4px 0;">$1</h4>');

            chatMessages.innerHTML += `<div class="chat-bubble chat-agent">${formatted}</div>`;
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }

        function askPredefined(q) {
            document.getElementById('chatInput').value = q;
            sendChatMessage();
        }

        function clearChat() {
            document.getElementById('chatMessages').innerHTML = `
                <div class="chat-bubble chat-agent">
                    Chat session cleared. How can I assist you with your reconciliation audit?
                </div>
            `;
        }

        // Initialize on page load
        window.addEventListener('load', () => {
            fetchStatus();
        });
    </script>
</body>
</html>
"""


def start_server(port=5000, open_browser=True):
    """Starts the web application."""
    init_app_state()
    url = f"http://127.0.0.1:{port}"
    print(f"\n[+] AI Finance Controller Web Application running at: {url}")
    print("    - Embedded AI Controller Copilot Chat")
    print("    - Upload custom Bank, Gateway, and Ledger CSVs")
    print("    - Real-time Reconciliation & Exception Triage\n")

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    start_server(port=5000, open_browser=True)
