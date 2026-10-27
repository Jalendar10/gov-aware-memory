# Architecture (Version 1)

Design source: the "Governance-Aware Compact Memory for Frozen LLMs" page
(https://governance-aware-compact-memory-for-thc7.pages.grok.bot/), Version 1 =
frozen LLM + external adaptive memory + external authoritative policy.

```
request ─► api/routes_governance ─► platform.decide
                                    ├─ governance/service.memory_signal ◄─ memory/store (active patterns only)
                                    ├─ governance/decide.decide  (pure, deterministic G)
                                    ├─ llm/* (advisory note only)
                                    └─ audit/log.append
events ──► discovery/pipeline.observe ─► matcher ─► reinforce (existing)  | quarantine (new) ─► coincidence ─► trust ─► promote ─► consolidate
feedback ► feedback/updates.apply_outcome (Beta + EMA, reviewer-weighted) ─► snapshot + audit
```

## Design principles → code

| Page principle | Where |
|---|---|
| P1 The LLM never authorizes | `llm/base.py` (`ADVISORY_SYSTEM`); `governance/service.py` ignores the LLM output for the decision |
| P2 Experience updates external state only | `feedback/updates.py`, `discovery/reinforce.py`; no model training code exists |
| P3 Policy changes require humans | `governance/policy_store.py`: memory/discovery/feedback/llm actors are refused; proposals stay inert until `approved=true` |
| P4 Retrieval is governed | **Partial.** Only promoted, active patterns are returned; entitlement/purpose filters are a stub |
| P5 Compression never replaces evidence | `evidence_refs` + `episodic_memory` tables; `audit/log.py` is hash-chained |
| P6 Model-agnostic | `llm/factory.py` (`mock` / `http` OpenAI-compatible) |
| P7 Fixed storage budget | `discovery/consolidate.py` (merge pass, then forget lowest utility until bytes ≤ B) |

## Discovery pipeline (page steps 1–6)

1. **Observe:** `discovery/pipeline.observe` logs an episode. `matcher.best_pattern` routes it to an
   existing pattern (cos ≥ 0.95). Otherwise it goes to a quarantined candidate.
2. **Same pattern vs coincidence:** `discovery/coincidence.py` requires support ≥ 3, distinct
   windows ≥ 2, distinct sources ≥ 2, and lift(action, context) ≥ 1. This is a stand-in for the
   page's significance test.
3. **Compact representation:** `memory/encode.py`.
4. **Trust and quarantine:** `discovery/trust.py` sets flags (`burst_source` when one source has
   ≥ 80 % share, `untrusted_source` when trust < 0.3). `quarantine.py` holds the candidate, and
   `reviewer.py` provides the synthetic or human verdict.
5. **Use under governance:** `governance/service.memory_signal`. Memory can only escalate
   Allow → Review, and only with risk ≥ threshold and evidence ≥ 2. It never relaxes Deny or Review.
6. **Merge/forget under budget:** `discovery/consolidate.py` and `discovery/utility.py`.

Score updates for **existing** patterns (`reinforce.py`, `feedback/updates.py`) are deliberately
separate from **new** pattern discovery (`quarantine.py`, `promote.py`).

## Record layouts (`memory/encode.py`, little-endian)

**FULL, 96 B** — `<8sIIIIfffffIIHBB8s32b`

| Field | Bytes |
|---|---|
| sig | 8 |
| support, windows, first_seen, last_seen (u32 each) | 16 |
| alpha, beta, ema_risk, reliability, usefulness (f32 each) | 20 |
| action_h, ctx_h (u32 each, tamper mirror) | 8 |
| version (u16) | 2 |
| flags (u8), resource_h8 (u8) | 2 |
| provenance hash | 8 |
| int8 centroid | 32 |

**COMPACT64, 64 B** — `<8sIIIHeeBBBBIIHBB4s16s2x`

| Field | Bytes |
|---|---|
| sig | 8 |
| support, first_seen, last_seen (u32 each) | 12 |
| windows (u16) | 2 |
| alpha, beta (f16 each) | 4 |
| ema_risk, reliability, usefulness, trust (u8 each) | 4 |
| mirrors | 8 |
| version (u16) | 2 |
| flags, resource_h8 (u8 each) | 2 |
| provenance | 4 |
| int4×32 centroid | 16 |
| pad | 2 |

Both sizes fall in the page's 80–128 B band and its 64 B compact target. The budget counts these
record bytes only. String index columns are reported separately as `index_overhead_bytes`.

## Governance G(u,a,r,c,p) — `governance/decide.py`

Policies are versioned. Active policies are evaluated in (−priority, key, version) order:
deny-overrides → review → allow → default `review`. Memory supplies c (risk, evidence) and can only
escalate. The function is pure, so the same inputs and policy set always give the same decision.

## Feedback (`feedback/`)

- **Pattern risk:** Beta(α, β) with prior (1, 3). Each update adds w·y to α and w·(1−y) to β, where
  w is the reviewer reliability.
- **EMA:** EMA(λ = 0.2) over risk, reliability and usefulness.
- **Reviewer reliability:** Beta with prior (4, 1). It is updated by gold-case calibration
  (`/api/reviewers/{id}/calibrate`) and a consensus hook. Reviewers below 0.2 are ignored.

## Poisoning protection

- **Provenance:** each pattern records the hash of its evidence.
- **Quarantine:** candidates are never consulted in decisions.
- **Source concentration and trust:** single-source and untrusted-source candidates are flagged.
- **Snapshots and rollback:** every pattern change is snapshotted, and patterns can be rolled back to
  any snapshot (`audit/rollback.py`).
- **Source purge:** sets the source's trust to 0 and re-quarantines patterns that source dominates.

## Not in Version 1 (deliberate)

- Phase 2 algorithm and evaluation harness
- 384-d embeddings and PQ codebooks
- Entitlement-filtered retrieval and retention expiry
- Auth and tenancy
- OPA/Cedar
- Version 2 runtime (Nested-Learning-inspired) memory
