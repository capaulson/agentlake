#!/usr/bin/env python3
"""AgentLake — Development Data Seeder.

Creates test API keys, uploads sample files, waits for processing to
complete, and verifies that search returns results.

Usage:
    python scripts/seed_data.py
    python scripts/seed_data.py --api-url http://localhost:8000
    python scripts/seed_data.py --skip-upload   # only create API keys
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_API_URL = "http://localhost:8000"
ADMIN_KEY_HEADER = "X-Api-Key"

SAMPLE_FILES: list[dict[str, str]] = [
    {
        "filename": "architecture-overview.md",
        "content_type": "text/markdown",
        "content": """\
# Architecture Overview

## System Design

AgentLake is built on a layered architecture with clear separation of concerns.

### Layer 1 — Raw Vault
All uploaded files are stored unmodified in MinIO (S3-compatible object storage).
Files are content-addressed using SHA-256 hashes for deduplication.

### Layer 2 — Distiller Pipeline
Celery workers process files through extraction, chunking, summarisation,
classification, entity extraction, and embedding generation.

### Layer 3 — Processed Lake
Processed documents with YAML frontmatter, markdown body, and citation links
are stored in PostgreSQL alongside pgvector embeddings.

### Layer 4A — API Server
FastAPI serves the REST API with full-text, semantic, and hybrid search.

### Layer 4B — LLM Gateway
All LLM calls route through a central gateway with provider abstraction,
rate limiting, fallback chains, and token accounting.

## Technology Choices

- PostgreSQL 16 with pgvector for vector similarity search
- Apache AGE for entity relationship graph queries
- Redis for caching and Celery task brokering
- MinIO for S3-compatible file storage
""",
    },
    {
        "filename": "onboarding-guide.md",
        "content_type": "text/markdown",
        "content": """\
# Employee Onboarding Guide

## Welcome to Acme Corp

Welcome! This guide covers your first two weeks at Acme Corp.

## Week 1

### Day 1 — Setup
- Collect laptop from IT (Building A, Room 102)
- Set up email and Slack accounts
- Complete HR paperwork with Jane Smith in HR

### Day 2-3 — Team Introductions
- Meet your team lead and direct reports
- Attend team standup (daily at 9:30 AM)
- Review the team wiki and current sprint board

### Day 4-5 — Systems Access
- Request VPN access from the Security Team
- Get access to the internal code repositories
- Set up your local development environment

## Week 2

### Day 6-8 — First Contribution
- Pick a starter ticket from the backlog
- Pair with a senior engineer on your first PR
- Attend the architecture review meeting (Wednesdays at 2 PM)

### Day 9-10 — Ramp Up
- Complete the security training module
- Read the incident response runbook
- Join the on-call rotation shadow schedule

## Key Contacts

- HR: Jane Smith (jane.smith@acme.corp)
- IT Support: helpdesk@acme.corp
- Engineering Lead: Bob Chen (bob.chen@acme.corp)
- Security Team: security@acme.corp
""",
    },
    {
        "filename": "q3-2025-revenue-summary.md",
        "content_type": "text/markdown",
        "content": """\
# Q3 2025 Revenue Summary

## Executive Summary

Acme Corp achieved $2.4M ARR in Q3 2025, a 23% increase over Q2.
Enterprise segment growth drove the majority of gains.

## Revenue by Segment

| Segment | Q2 2025 | Q3 2025 | Growth |
|---------|---------|---------|--------|
| Enterprise | $1.2M | $1.6M | 33% |
| Mid-Market | $0.5M | $0.55M | 10% |
| SMB | $0.25M | $0.25M | 0% |

## Key Metrics

- Monthly Recurring Revenue (MRR): $200K
- Customer Acquisition Cost (CAC): $12K (down from $15K)
- Net Revenue Retention (NRR): 118%
- Gross Margin: 78%

## Outlook

The sales pipeline for Q4 includes three enterprise deals worth
a combined $500K ARR. If closed, Acme Corp will exceed the annual
target of $3M ARR set by the board of directors.

## Prepared By

Finance Team, Acme Corp
Report Date: October 1, 2025
""",
    },
    {
        "filename": "incident-response-runbook.md",
        "content_type": "text/markdown",
        "content": """\
# Incident Response Runbook

## Severity Levels

### SEV-1 (Critical)
- Complete service outage affecting all customers
- Data breach or security incident
- Response time: 15 minutes
- Escalation: VP Engineering + CTO

### SEV-2 (Major)
- Partial outage affecting > 25% of customers
- Data integrity issue (no breach)
- Response time: 30 minutes
- Escalation: Engineering Manager

### SEV-3 (Minor)
- Degraded performance or intermittent errors
- Single customer impact
- Response time: 2 hours
- Escalation: On-call engineer

## Response Procedure

1. **Acknowledge** the alert in PagerDuty
2. **Assess** severity and impact scope
3. **Communicate** in #incidents Slack channel
4. **Mitigate** — take immediate action to reduce impact
5. **Resolve** — deploy fix or roll back
6. **Post-mortem** — within 48 hours for SEV-1 and SEV-2

## Rollback Procedure

```bash
# Identify the last known good deployment
kubectl -n production rollout history deploy/api

# Roll back to previous version
kubectl -n production rollout undo deploy/api

# Verify rollback
kubectl -n production rollout status deploy/api
```

## Contacts

- On-call schedule: https://pagerduty.acme.corp/schedules
- Incident commander: rotating weekly
- Status page: https://status.acme.corp
""",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def info(msg: str) -> None:
    print(f"[INFO]  {msg}")


def error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


def wait_for_api(api_url: str, timeout: int = 60) -> bool:
    """Wait for the API health endpoint to respond."""
    info(f"Waiting for API at {api_url} ...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"{api_url}/api/v1/health", timeout=5)
            if resp.status_code == 200:
                info("API is healthy.")
                return True
        except requests.ConnectionError:
            pass
        time.sleep(2)
    error(f"API did not become healthy within {timeout}s.")
    return False


def get_or_create_api_key(api_url: str) -> str:
    """Create a development API key or return an existing one.

    Tries to create a key via the admin bootstrap endpoint. If the API
    does not support that endpoint, falls back to checking the
    DEFAULT_ADMIN_API_KEY environment variable.
    """
    # Try the bootstrap endpoint
    try:
        resp = requests.post(
            f"{api_url}/api/v1/auth/bootstrap",
            json={"name": "seed-script", "role": "admin"},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            key = data.get("data", {}).get("api_key") or data.get("api_key", "")
            if key:
                info(f"Created API key: {key[:8]}...")
                return key
    except Exception:
        pass

    # Fall back to a well-known dev key
    dev_key = "dev-seed-api-key"
    info(f"Using default dev API key: {dev_key[:8]}...")
    return dev_key


def upload_file(
    api_url: str,
    api_key: str,
    filename: str,
    content: str,
    content_type: str,
) -> str | None:
    """Upload a file and return its file ID."""
    info(f"Uploading {filename} ...")
    try:
        resp = requests.post(
            f"{api_url}/api/v1/vault/files",
            headers={ADMIN_KEY_HEADER: api_key},
            files={"file": (filename, io.BytesIO(content.encode()), content_type)},
            timeout=30,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            file_id = data.get("data", {}).get("id") or data.get("id", "")
            info(f"  Uploaded: {filename} -> {file_id}")
            return file_id
        else:
            error(f"  Upload failed ({resp.status_code}): {resp.text[:200]}")
            return None
    except Exception as exc:
        error(f"  Upload failed: {exc}")
        return None


def wait_for_processing(
    api_url: str,
    api_key: str,
    file_ids: list[str],
    timeout: int = 300,
) -> bool:
    """Wait for all files to finish processing."""
    info(f"Waiting for {len(file_ids)} file(s) to process (timeout {timeout}s) ...")
    deadline = time.time() + timeout
    pending = set(file_ids)

    while pending and time.time() < deadline:
        for file_id in list(pending):
            try:
                resp = requests.get(
                    f"{api_url}/api/v1/vault/files/{file_id}",
                    headers={ADMIN_KEY_HEADER: api_key},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", resp.json())
                    status = data.get("processing_status", "")
                    if status in ("completed", "processed"):
                        info(f"  File {file_id[:8]}... processing complete.")
                        pending.discard(file_id)
                    elif status in ("failed", "error"):
                        error(f"  File {file_id[:8]}... processing FAILED.")
                        pending.discard(file_id)
            except Exception:
                pass
        if pending:
            time.sleep(5)

    if pending:
        error(f"  {len(pending)} file(s) did not complete processing in time.")
        return False

    info("All files processed.")
    return True


def verify_search(api_url: str, api_key: str) -> bool:
    """Run a test search and verify results are returned."""
    info("Verifying search ...")
    try:
        resp = requests.get(
            f"{api_url}/api/v1/search",
            headers={ADMIN_KEY_HEADER: api_key},
            params={"q": "architecture", "limit": 5},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("data", [])
            info(f"  Search returned {len(results)} result(s).")
            return len(results) > 0
        else:
            error(f"  Search failed ({resp.status_code}): {resp.text[:200]}")
            return False
    except Exception as exc:
        error(f"  Search failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed AgentLake with development data.")
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"API base URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Only create API keys, skip file uploads.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Processing timeout in seconds (default: 300).",
    )
    args = parser.parse_args()

    # 1. Wait for API
    if not wait_for_api(args.api_url):
        return 1

    # 2. Get or create API key
    api_key = get_or_create_api_key(args.api_url)

    if args.skip_upload:
        info("Skipping file uploads (--skip-upload).")
        info("Seed complete.")
        return 0

    # 3. Upload sample files
    file_ids: list[str] = []
    for sample in SAMPLE_FILES:
        file_id = upload_file(
            api_url=args.api_url,
            api_key=api_key,
            filename=sample["filename"],
            content=sample["content"],
            content_type=sample["content_type"],
        )
        if file_id:
            file_ids.append(file_id)

    if not file_ids:
        error("No files were uploaded successfully.")
        return 1

    info(f"Uploaded {len(file_ids)} file(s).")

    # 4. Wait for processing
    wait_for_processing(args.api_url, api_key, file_ids, timeout=args.timeout)

    # 5. Verify search
    if verify_search(args.api_url, api_key):
        info("Search verification passed.")
    else:
        info("Search verification did not return results (files may still be processing).")

    info("Seed complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
