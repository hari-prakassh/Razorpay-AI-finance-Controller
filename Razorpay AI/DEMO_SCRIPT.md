# 3-Minute Hackathon Demo Script: AI Finance Controller

**Presenter Persona:** Senior FinTech Engineer / Finance Ops Lead  
**Audience:** Hackathon Judges & Engineering Leads  
**Target Duration:** Exactly 3 Minutes (180 Seconds)

---

## ⏱️ [0:00 – 0:45] The Hook: "One Match Proves Nothing"

> **Speaker:**
> *"Good morning judges. If you ask any CFO or finance operations lead at a high-growth company what keeps them awake at month-end, it's not fundraising—it's **reconciliation**.*
>
> *Every day, transactions flow across three disparate worlds:*
> 1. *Messy Indian bank statements with truncated UTRs,*
> 2. *Payment gateway dumps like Razorpay deducting MDR fees and GST, and*
> 3. *Internal ERP ledgers deducting 10% statutory TDS.*
>
> *Today, LLM demos often show one cherry-picked match. But in finance ops, **one match proves nothing**. A false match cross-contaminates the general ledger and fails statutory audit.*
>
> *What matters is: **Throughput, Measured Accuracy against Ground Truth, and an Honest Exception List**. Let's run our AI Finance Controller live."*

---

## ⏱️ [0:45 – 1:30] The Live Execution & Hybrid Architecture

> **Action:** In terminal, run:
> ```bash
> python run.py
> ```
> *(Or `py run.py` / `run.bat`)*

> **Speaker:**
> *(Pointing to the terminal output as it finishes in ~0.01 seconds)*
> *"Notice what just happened. In less than 15 milliseconds, the agent reconciled **243 records across 80 ground-truth groups**.*
>
> *Notice our hybrid architecture:*
> - *We did not blindly throw 240 records into an expensive LLM context.*
> - *First, **Stage A (Deterministic)** handles 77.5% of clean transactions with mathematical certainty.*
> - *Second, **Stage B (Rule-Based)** recovers 18.8% using Indian financial domain logic: reverse-calculating Razorpay's 2% MDR fee plus 18% GST, statutory TDS under Section 194J and 194C, and resolving 1-to-many batch settlement payouts.*
> - *Finally, **Stage C (LLM Pass)** is invoked **strictly on leftover residuals**—saving 95% in token costs, running at under $0.001 per batch."*

---

## ⏱️ [1:30 – 2:20] The Honest Numbers: Zero False Positives

> **Action:** Highlight the Metrics Table and Confusion Matrix in the CLI output.

> **Speaker:**
> *"Now let's look at the metrics that actually matter to an auditor:*
> - *Our **Auto-Match Rate is 91.2%**.*
> - *Our **Precision is 100.0%**. That means **Zero False Positives**. In finance ops, a miss is an exception, but a false match is an audit failure.*
> - *Look at our **Confusion Matrix across 7 injected real-world error classes**: 100% accuracy on clean records, fuzzy truncated narrations, date drift across bank holiday weekends, and batch payout splits.*
>
> *And most importantly: **The agent knows when to say 'I don't know'**."*

---

## ⏱️ [2:20 – 3:00] The Exception Report & Interactive Dashboard

> **Action:** Open `results/reconciliation_dashboard.html` in the browser or show the Exception preview in CLI.

> **Speaker:**
> *"Look at `results/exceptions.csv`. The system identified 7 specific anomalies and provided actionable operational steps:*
> 1. *A **Double Bank Credit** anomaly on UTR `423687000801`—flagged immediately for bank clawback before funds are lost.*
> 2. *A **Webhook Replay Duplicate** from the gateway—flagged to prevent double settlement in the ERP.*
> 3. *An **Unauthorized Short Payment** of ₹500 on a Flipkart invoice—flagged as an AR dispute.*
> 4. *An **Orphan Direct Bank Credit** of ₹18,500—routed into a Suspense Account pending treasury remitter lookup.*
>
> *No hallucinations. No forced matches. 24,000 records per second throughput.*
>
> *This is how AI actually enters corporate finance operations. Thank you, and I welcome your questions."*

---

## 💡 Quick Q&A Cheat-Sheet for Judges

- **Q: What if the Claude API is down or the user is offline?**
  - **A:** The system has an intelligent fallback reasoning engine implementing the exact same prompt, evidence schema, and financial audit logic. It runs 100% reproducibly with zero external downtime risk.
- **Q: Why not use an LLM for all records?**
  - **A:** Deterministic operations on 12-digit UTRs and mathematical decimal subtraction are 100,000x faster, zero cost, and 100% deterministic. LLMs should only be applied where ambiguity demands semantic reasoning.
- **Q: How does it prevent false matches?**
  - **A:** Strict confidence gating: $\ge 0.85$ auto-match, $0.50 - 0.85$ routed to human review, $< 0.50$ marked unresolved.
