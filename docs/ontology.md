# Common Data Ontology

Every processed document in AgentLake carries YAML frontmatter that conforms to this ontology. The frontmatter provides structured metadata enabling consistent search, filtering, and cross-document linking.

## Frontmatter Schema

Every `ProcessedDocument.frontmatter` field is a JSON object (stored as JSONB) with the following structure:

```yaml
---
# Required fields
title: "Quarterly Revenue Analysis Q3 2025"
category: business                          # one of the defined categories
source_file_id: "a1b2c3d4-..."             # UUID of the raw file in the vault
processing_version: 1                       # pipeline version that produced this document

# Classification
subcategory: "financial-analysis"           # free-text, more specific than category
tags:
  - revenue
  - quarterly
  - finance
confidence: 0.92                            # LLM classification confidence (0.0-1.0)

# Entities (denormalized from the entity graph)
entities:
  - name: "Acme Corp"
    type: organization
  - name: "Jane Smith"
    type: person
  - name: "Q3 2025"
    type: time_period

# Provenance
author: "Jane Smith"                        # extracted or inferred author
date_created: "2025-10-01"                  # document creation date (if extractable)
date_processed: "2025-10-15T08:30:00Z"      # when AgentLake processed this file
chunk_count: 12                             # number of chunks produced
citation_count: 12                          # number of citation links

# Optional metadata (adapter-specific)
page_count: 8                               # for PDFs
language: "en"
---
```

## Categories

Every document is classified into exactly one top-level category. The `category` field on `ProcessedDocument` uses these values:

| Category | Description | Typical file types |
|----------|-------------|--------------------|
| `technical` | Engineering docs, code, architecture decisions, specs | `.md`, `.py`, `.yaml`, `.json` |
| `business` | Financial reports, strategy docs, contracts, proposals | `.pdf`, `.docx`, `.xlsx` |
| `operational` | Runbooks, SOPs, deployment guides, incident reports | `.md`, `.pdf`, `.txt` |
| `research` | Academic papers, market research, whitepapers | `.pdf`, `.docx` |
| `communication` | Emails, meeting notes, chat transcripts, memos | `.eml`, `.txt`, `.md` |
| `reference` | Glossaries, API docs, configuration references, manuals | `.md`, `.pdf`, `.html` |

The LLM classifies documents using the `classify_ontology` task. Classification confidence below 0.7 triggers a `low_confidence` flag in the frontmatter so operators can review.

## Entity Types

Entities extracted from documents use these standardized types:

| Type | Description | Examples |
|------|-------------|----------|
| `person` | Named individuals | "Jane Smith", "Dr. Lee" |
| `organization` | Companies, teams, departments | "Acme Corp", "Engineering Team" |
| `location` | Physical or virtual places | "New York", "us-east-1" |
| `technology` | Software, hardware, protocols | "PostgreSQL", "Kubernetes", "HTTP/2" |
| `concept` | Abstract ideas, methodologies | "microservices", "zero trust" |
| `time_period` | Dates, quarters, fiscal years | "Q3 2025", "FY2024" |
| `metric` | Measurable quantities | "99.9% uptime", "$2.4M ARR" |
| `document_ref` | References to other documents | "RFC 7807", "SOC2 Report" |

Entity relationships are stored in the Apache AGE graph (`agentlake_graph`). The graph is a derived index: it can be fully rebuilt from the `entities` fields in processed documents.

### Entity Relationship Types

Edges in the entity graph use these relationship labels:

| Relationship | Direction | Example |
|-------------|-----------|---------|
| `WORKS_AT` | person -> organization | Jane Smith WORKS_AT Acme Corp |
| `LOCATED_IN` | organization -> location | Acme Corp LOCATED_IN New York |
| `USES` | organization -> technology | Acme Corp USES PostgreSQL |
| `MENTIONS` | document -> entity | Doc123 MENTIONS Kubernetes |
| `RELATED_TO` | entity -> entity | PostgreSQL RELATED_TO pgvector |
| `PART_OF` | entity -> entity | Engineering Team PART_OF Acme Corp |
| `AUTHORED_BY` | document -> person | Doc123 AUTHORED_BY Jane Smith |

## Example: Full Processed Document

Below is a complete example showing how a raw PDF becomes a processed document with ontology-conforming frontmatter, citation links, and entity extraction.

### Raw Input

File: `q3-2025-revenue.pdf` (8 pages, uploaded to vault)

### Processed Output

```markdown
---
title: "Quarterly Revenue Analysis Q3 2025"
category: business
subcategory: "financial-analysis"
source_file_id: "f47ac10b-58cc-4372-a567-0e02b2c3d479"
processing_version: 1
tags:
  - revenue
  - quarterly
  - finance
  - growth
confidence: 0.95
entities:
  - name: "Acme Corp"
    type: organization
  - name: "Jane Smith"
    type: person
  - name: "Q3 2025"
    type: time_period
  - name: "$2.4M ARR"
    type: metric
author: "Jane Smith"
date_created: "2025-10-01"
date_processed: "2025-10-15T08:30:00Z"
chunk_count: 12
citation_count: 12
page_count: 8
language: "en"
---

# Quarterly Revenue Analysis Q3 2025

## Summary

Acme Corp achieved $2.4M ARR in Q3 2025, representing a 23% quarter-over-quarter
increase driven primarily by enterprise customer expansion [1](/api/v1/vault/files/f47ac10b-58cc-4372-a567-0e02b2c3d479/download#chunk=0).

## Revenue Breakdown

The enterprise segment contributed 68% of total revenue [2](/api/v1/vault/files/f47ac10b-58cc-4372-a567-0e02b2c3d479/download#chunk=1), while
the SMB segment showed steady growth at 15% QoQ [3](/api/v1/vault/files/f47ac10b-58cc-4372-a567-0e02b2c3d479/download#chunk=2).

...
```

### Citation Format

Every citation follows this exact pattern:

```
[N](/api/v1/vault/files/{file_id}/download#chunk={chunk_index})
```

Where:
- `N` is the 1-based citation index within the document
- `file_id` is the UUID of the source file in the vault
- `chunk_index` is the 0-based index of the source chunk

Citations are clickable links that download the raw source file. The `#chunk=` fragment allows frontends to highlight or scroll to the relevant section.

## Validation

The `ProcessedDocument` model enforces:

1. `category` must be one of the six defined values
2. `frontmatter` must be a valid JSON object
3. `entities` must be a JSON array of objects with `name` and `type` fields
4. Every citation in `body_markdown` must have a corresponding `Citation` record
5. `processing_version` must match the current pipeline version

Documents failing validation are flagged for manual review rather than silently dropped.
