# gov-aware-memory — Version 1 platform scaffold

**Governance-Aware Compact Memory for Frozen LLMs: Version 1 prototype (Phase 1 of the plan).**
A frozen LLM sits next to an **external** adaptive pattern memory and an **external, authoritative**
deterministic policy engine. Experience changes memory scores only. It never changes model weights,
and it never silently rewrites policy.

> Status: engineering scaffold. **No experimental results are claimed.** No LLM is fine-tuned.
> The demo data is synthetic and exists to exercise the code paths.

## Quick start

```bash
# Docker (API :8000, dashboard :8080, SQLite on a named volume)
docker compose up --build
open http://localhost:8080/dashboard/        # or http://localhost:8000/dashboard/

# Optional real frozen LLM via vLLM (GPU): set GOVMEM_LLM_BACKEND=http on the api service, then
docker compose --profile llm up --build

# Local, no Docker
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q                                    # fully offline
python -m govmem.db                          # init ./data/govmem.db + seed default policies
uvicorn --factory govmem.api.app:create_app --port 8000
python scripts/simulate.py --url http://localhost:8000   # synthetic demo traffic
```

## Configuration (env)

| Var | Default | Meaning |
|---|---|---|
| `GOVMEM_DB_PATH` | `data/govmem.db` | SQLite file (`:memory:` for tests) |
| `GOVMEM_ENCODING` | `full` | `full` (96 B) or `compact64` (64 B) records |
| `GOVMEM_BYTE_BUDGET` | `4096` | hard byte budget B for active pattern records |
| `GOVMEM_LLM_BACKEND` | `mock` | `mock` (deterministic JSON) or `http` (OpenAI-compatible) |
| `GOVMEM_LLM_URL` / `GOVMEM_LLM_MODEL` / `GOVMEM_LLM_API_KEY` | — | for `http`: vLLM, llama.cpp server, Ollama `/v1`, serving Llama/Qwen |
| `GOVMEM_EMBEDDER` | `hash` | `hash` (32-d signed feature hashing) or `st` (sentence-transformers, `pip install .[st]`) |

Discovery thresholds (min support / windows / sources, similarity, promote threshold) are in
`src/govmem/config.py`.

## API overview

| Method | Path | Purpose |
|---|---|---|
| GET | `/health`, `/api/health` | liveness + active LLM/embedder/encoding |
| POST | `/api/decide` | G(u,a,r,c,p) → allow / deny / review, with policy refs, memory signal, advisory LLM note |
| GET | `/api/decisions` | recent decisions |
| POST | `/api/observe` | feed events into the discovery pipeline |
| POST | `/api/discover` | re-evaluate quarantined candidates |
| POST | `/api/consolidate` | merge, then forget under budget |
| POST | `/api/feedback` | harmful/benign outcome on a pattern or a decision (Beta/EMA update) |
| POST | `/api/memory/retrieve` | top-k active patterns for a request |
| GET | `/api/memory/stats` | pattern count, record bytes, budget utilization, index overhead, DB bytes |
| GET | `/api/patterns?status=` | list patterns; `/api/patterns/{id}/snapshots` lists versions |
| GET | `/api/quarantine` | candidate queue; `POST /api/quarantine/{id}/review` approves or rejects |
| GET/POST | `/api/policies` | list / propose (inert until approved) |
| POST | `/api/policies/{id}/approve` | human approval with `approved: true` |
| DELETE | `/api/policies/{key}?approver=` | retire |
| POST | `/api/rollback` | roll back a pattern or policy to a version |
| POST | `/api/rollback/source` | purge a poisoned source: trust 0, re-quarantine patterns it dominates |
| GET/POST | `/api/sources/trust` | source trust registry |
| GET | `/api/reviewers`; POST `/api/reviewers/{id}/calibrate` | reviewer reliability (gold-case hook) |
| GET | `/api/audit`, `/api/audit/verify` | hash-chained audit log and integrity check |
| POST | `/api/demo/seed` | synthetic demo traffic, including a single-source poisoning burst |

Interactive docs: `http://localhost:8000/docs`.

## What is real vs stubbed

Works fully offline and is covered by `pytest`:
- discovery, coincidence filter, quarantine, promotion
- compact binary encoding and byte accounting
- merge/forget under budget
- deterministic governance
- Beta/EMA feedback with reviewer reliability
- audit chain, snapshots, rollback, source purge
- REST API and dashboard

The **MockLLM** is the default. It returns deterministic JSON advisories.

Needs a real model: `GOVMEM_LLM_BACKEND=http` against a served Llama/Qwen. The client exists, but no
model was run against it here. LLM output is **advisory only** and never feeds the decision.

Intentional stubs and simplifications (see ARCHITECTURE.md):
- **Embedder:** 32-d hash embedder, not 384-d / product quantization.
- **Coincidence test:** a lift ≥ 1 test stands in for a significance test, and there is no held-out replay before promotion.
- **Reviewers:** SyntheticReviewer stands in for human review.
- **Window counting:** approximate.
- **Purge rule:** source dominance is a majority-share heuristic.
- **Retrieval:** no entitlement-filtered retrieval (P4) and no retention expiry.
- **Access control:** no auth or multi-tenancy.
- **Policy language:** a small JSON match language, not OPA/Cedar.

## Research framing

Phase 1 is a platform for the Phase 2 study, *Governance-Constrained Continual Memory Formation for
Frozen Large Language Models*. That study will compare frozen LLM, RAG, and static-governance + RAG
baselines. The primary contribution under study is **pattern discovery**: deciding when recurring
events are the same pattern rather than coincidence, encoding them compactly, gating them through
trust and quarantine, and using them only under authoritative external policy. This repo provides
the mechanisms and their tests. It reports no measured results.
