#!/usr/bin/env python3
"""Generate a 50-document test dataset using Nemotron 3 Super 120B via OpenRouter.

Usage:
    python scripts/generate_dataset.py
"""

import json
import os
import sys
import time
from pathlib import Path

import httpx

OPENROUTER_API_KEY = os.environ.get(
    "OPENROUTER_API_KEY",
    "OPENROUTER_API_KEY_HERE",
)
MODEL = "nvidia/nemotron-3-super-120b-a12b"
BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
OUTPUT_DIR = Path(__file__).parent.parent / "tests" / "test_dataset"

DOCUMENTS = [
    # Technical (10)
    ("tech-api-design-guidelines.md", "technical", "REST API design standards and best practices document for NovaTech's engineering team"),
    ("tech-database-migration-plan.md", "technical", "PostgreSQL 14 to 16 upgrade plan for NovaPlatform, including pgvector migration"),
    ("tech-incident-postmortem-2024-03.md", "technical", "Production outage postmortem from March 2024 - API gateway failure affecting Quantum Edge"),
    ("tech-microservices-architecture.md", "technical", "NovaPlatform microservices architecture overview with service mesh design"),
    ("tech-security-audit-findings.md", "technical", "Security assessment results from Q4 2024 audit led by James Okafor"),
    ("tech-performance-benchmark-q4.md", "technical", "Q4 performance benchmarks for NovaPlatform search and processing pipeline"),
    ("tech-ci-cd-pipeline-setup.md", "technical", "CI/CD pipeline configuration guide using GitHub Actions and ArgoCD on Kubernetes"),
    ("tech-data-pipeline-architecture.md", "technical", "ETL/ELT data pipeline architecture for ingesting data from AcmeConnect into NovaPlatform"),
    ("tech-kubernetes-runbook.md", "technical", "Kubernetes operations runbook for NovaPlatform production clusters"),
    ("tech-ml-model-training-report.md", "technical", "ML model training results for document classification using fine-tuned LLMs, led by Lisa Park"),
    # Business (10)
    ("biz-q4-2024-quarterly-review.md", "business", "Q4 2024 quarterly business review with revenue metrics, customer growth, and KPIs presented by David Kim"),
    ("biz-partnership-agreement-acme.md", "business", "Strategic partnership agreement between NovaTech and Acme Corp for AcmeConnect integration"),
    ("biz-market-analysis-ai-sector.md", "business", "AI/ML market analysis covering enterprise data management sector and competitors like Zenith Systems"),
    ("biz-product-roadmap-2025.md", "business", "2025 product roadmap for NovaPlatform with feature priorities from Priya Sharma"),
    ("biz-customer-feedback-summary.md", "business", "Customer feedback synthesis from Q4 surveys including Quantum Edge and other enterprise clients"),
    ("biz-pricing-strategy-proposal.md", "business", "New pricing model proposal for NovaPlatform tiers by Rachel Foster"),
    ("biz-competitive-landscape-q1.md", "business", "Q1 2025 competitive analysis: NovaTech vs Zenith Systems vs Atlas AI"),
    ("biz-sales-pipeline-report.md", "business", "March 2025 sales pipeline report with deal stages and revenue forecast by Rachel Foster"),
    ("biz-board-meeting-minutes-jan.md", "business", "January 2025 board meeting minutes covering Series B funding and growth strategy"),
    ("biz-investor-update-march.md", "business", "March 2025 investor update letter from David Kim on ARR growth and product milestones"),
    # Operational (8)
    ("ops-employee-onboarding-guide.md", "operational", "New employee onboarding guide for NovaTech engineering team"),
    ("ops-disaster-recovery-plan.md", "operational", "Disaster recovery procedures for NovaPlatform infrastructure"),
    ("ops-vendor-evaluation-cloud.md", "operational", "Cloud vendor comparison: AWS vs GCP vs Azure for NovaPlatform hosting"),
    ("ops-budget-allocation-2025.md", "operational", "2025 department budget allocations across engineering, sales, and research"),
    ("ops-team-restructuring-memo.md", "operational", "Organization restructuring memo from Sarah Chen about new Platform Engineering team"),
    ("ops-office-relocation-plan.md", "operational", "Office relocation plan from downtown to new tech campus Q3 2025"),
    ("ops-it-procurement-policy.md", "operational", "IT procurement policy and approval workflows"),
    ("ops-quarterly-okrs-q2.md", "operational", "Q2 2025 OKR tracking for engineering, product, and sales teams"),
    # Research (8)
    ("research-llm-fine-tuning-results.md", "research", "LLM fine-tuning experiment results for domain-specific document summarization by Lisa Park and Meridian Labs"),
    ("research-vector-db-comparison.md", "research", "Vector database benchmark comparing pgvector, Pinecone, Weaviate, and MeridianDB"),
    ("research-rag-architecture-study.md", "research", "RAG architecture patterns study: naive vs advanced retrieval strategies"),
    ("research-user-behavior-analysis.md", "research", "User behavior analytics study on NovaPlatform search patterns"),
    ("research-energy-efficiency-ai.md", "research", "Energy efficiency analysis of LLM inference workloads on different hardware"),
    ("research-synthetic-data-generation.md", "research", "Synthetic data generation techniques for training document classifiers"),
    ("research-multimodal-embeddings.md", "research", "Multimodal embedding model comparison for document + image retrieval"),
    ("research-agent-orchestration-patterns.md", "research", "AI agent orchestration patterns for multi-step document processing"),
    # Communication (7)
    ("comms-all-hands-meeting-march.md", "communication", "March 2025 all-hands meeting notes with company updates from David Kim and Sarah Chen"),
    ("comms-engineering-weekly-w12.md", "communication", "Engineering weekly standup notes week 12 - sprint progress and blockers"),
    ("comms-customer-escalation-zenith.md", "communication", "Customer escalation from Quantum Edge about search latency issues"),
    ("comms-product-launch-announcement.md", "communication", "NovaPlatform v2.0 launch announcement with new AI-powered search features"),
    ("comms-team-retrospective-sprint-24.md", "communication", "Sprint 24 retrospective notes from Marcus Rivera's platform team"),
    ("comms-conference-trip-report-neurips.md", "communication", "NeurIPS 2024 conference trip report by Lisa Park covering RAG and agent papers"),
    ("comms-cross-team-sync-platform.md", "communication", "Cross-team sync notes between platform engineering and AI research teams"),
    # Reference (7)
    ("ref-company-glossary.md", "reference", "NovaTech company glossary of terms, acronyms, and product names"),
    ("ref-coding-standards-python.md", "reference", "Python coding standards and style guide for NovaTech engineering"),
    ("ref-data-classification-policy.md", "reference", "Data classification and handling policy (public, internal, confidential, restricted)"),
    ("ref-api-versioning-guide.md", "reference", "API versioning strategy and deprecation policy for NovaPlatform"),
    ("ref-incident-severity-levels.md", "reference", "Incident severity classification guide (P0-P4) with response SLAs"),
    ("ref-meeting-cadence-guide.md", "reference", "Meeting structure and cadence guide for engineering teams"),
    ("ref-technology-radar-2025.md", "reference", "2025 Technology Radar: adopt, trial, assess, hold recommendations"),
]

SYSTEM_PROMPT = """You are generating realistic corporate documents for a test dataset. The company is NovaTech, a Series B startup building an AI-powered enterprise data management platform called NovaPlatform.

Key people:
- David Kim (CEO)
- Sarah Chen (CTO)
- Marcus Rivera (VP Engineering)
- Lisa Park (Head of AI Research)
- James Okafor (Security Lead)
- Priya Sharma (Head of Product)
- Rachel Foster (VP Sales)

Key organizations:
- NovaTech (our company)
- Acme Corp (strategic partner, builds AcmeConnect)
- Zenith Systems (main competitor, offers ZenithCloud)
- Meridian Labs (research partner, built MeridianDB)
- Atlas AI (LLM vendor/partner)
- Quantum Edge (largest enterprise customer)

Key technologies: Kubernetes, PostgreSQL, pgvector, Redis, FastAPI, React, LLMs, RAG, Vector databases, Apache AGE

Write the document in markdown format. Include:
- 400-700 words of realistic content
- Proper markdown formatting (headings, lists, bold, code blocks where relevant)
- Specific dates, metrics, and details
- References to the people and organizations above where natural
- Cross-references to other documents where relevant

Output ONLY the markdown document content, nothing else. No commentary."""


def generate_document(filename: str, category: str, description: str, client: httpx.Client) -> str:
    """Generate a single document using Nemotron 3 Super 120B."""
    user_prompt = f"""Generate a {category} document for the file "{filename}".

Description: {description}

Write it as a realistic corporate document with proper markdown formatting."""

    response = client.post(
        BASE_URL,
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 2048,
            "temperature": 0.8,
        },
        timeout=120.0,
    )
    response.raise_for_status()
    data = response.json()

    content = data["choices"][0]["message"].get("content", "")
    # Some models put content in reasoning — handle that
    if not content:
        reasoning = data["choices"][0]["message"].get("reasoning", "")
        if reasoning:
            content = reasoning

    tokens = data.get("usage", {})
    cost = tokens.get("cost", 0)
    return content, cost


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://agentlake.dev",
        "X-Title": "AgentLake Test Dataset Generator",
    }

    total_cost = 0.0
    generated = 0
    failed = 0

    with httpx.Client(headers=headers) as client:
        for i, (filename, category, description) in enumerate(DOCUMENTS):
            filepath = OUTPUT_DIR / filename
            if filepath.exists():
                print(f"  [{i+1:2d}/50] SKIP {filename} (already exists)")
                generated += 1
                continue

            print(f"  [{i+1:2d}/50] Generating {filename}...", end=" ", flush=True)
            try:
                content, cost = generate_document(filename, category, description, client)
                total_cost += cost

                if not content or len(content.strip()) < 50:
                    print(f"WARN: short response ({len(content)} chars), retrying...")
                    time.sleep(2)
                    content, cost = generate_document(filename, category, description, client)
                    total_cost += cost

                filepath.write_text(content)
                generated += 1
                print(f"OK ({len(content)} chars, ${cost:.4f})")

                # Rate limit: ~2 req/sec to be safe
                time.sleep(0.5)

            except Exception as e:
                failed += 1
                print(f"FAILED: {e}")
                # Write a fallback document
                fallback = f"""# {filename.replace('.md', '').replace('-', ' ').title()}

**Category:** {category}
**Date:** 2025-03-15
**Author:** NovaTech Team

## Overview

{description}

This document is pending content generation. Please rerun the generator.

## Status

- Generated: Failed
- Retry needed: Yes
"""
                filepath.write_text(fallback)
                time.sleep(2)

    print(f"\n{'='*60}")
    print(f"Dataset generation complete!")
    print(f"  Generated: {generated}/50")
    print(f"  Failed:    {failed}/50")
    print(f"  Total cost: ${total_cost:.4f}")
    print(f"  Output dir: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
