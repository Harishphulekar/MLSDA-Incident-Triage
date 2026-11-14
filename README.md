# Production Incident Triage and Runbook Assistant

**Course**: ML System Design and AgentOps (UE24AM342AA5) — Mini Project 08  
**Team**: Team 04  

## Overview
The Production Incident Triage and Runbook Assistant is an AI-powered system designed to triage production infrastructure alerts (e.g. database disk saturation, replication lag, connection spikes), retrieve authoritative documentation and runbooks, perform multi-agent verification of evidence, and deliver cited, safe remediation recommendations to human on-call engineers.

## Team Architecture & Module Ownership
1. **Module 1: Backend and API** — FastAPI application, request validation, task queue, and client endpoints.
2. **Module 2: Corpus and RAG** — PostgreSQL documentation, incident runbooks, vector embeddings, and retrieval.
3. **Module 3: Multi-Agent & ML** — Triage Agent, Retrieval Agent, Verification Agent, and LangGraph workflow orchestration.
4. **Module 4: AgentOps, DevOps, Observability & Evaluation** — Production deployment, OpenTelemetry tracing, Prometheus metrics, Grafana dashboards, security guardrails, evaluation framework, LLM cost tracking, and load testing.
