# 06 — AI Analysis Layer

**Status:** APPROVED — 2026-08-27
**Last updated:** 2026-08-27
**Prerequisite reading:** `00-overview.md`, `04-signals-and-scoring.md`, `05-api-contract.md`
**Implements:** ADR-0004 (provider abstraction)

Specifies what the model is given, what it must return, and what happens when it
misbehaves. No integration work follows from this document until a provider is
explicitly approved — the only implemented provider is `template`, which calls
nothing.

---

## 1. Scope — deliberately narrow

The AI layer **does not decide the score.** It writes the explanation.

| Step | Owner |
|---|---|
| Collect evidence | Collectors (code) |
| Normalise to sub-scores | `signals/normalise.py` (04 §4) |
| Compute opportunity score | `signals/score.py` (04 §3) |
| Decide the verdict and apply gates | `signals/score.py` (04 §5, §6) |
| Write the summary and numbered reasons | **Model** |
| Explain apparent conflicts between signals | **Model** |
| Suggest an entry segment | **Model** |

Everything the model produces is prose *about* numbers it was handed. It never
produces a number that becomes product state.

---

## 2. The provider interface

One interface, defined in terms of **structured output against a JSON Schema** —
because that is the capability actually depended on, not "text generation".

```
analyse(AnalysisRequest) -> AnalysisResult
```

**Containment rule (ADR-0004):** no provider SDK may be imported outside
`engine/ai/providers/`. Enforceable by lint; a violation means the abstraction has
quietly stopped being one.

Provider and model are configuration. Every report stores `provider`, `model` and
`prompt_version` so any past report can be explained or reproduced.

---

## 3. What the model receives

**Only structured, already-normalised data.** Never raw HTML, never a raw vendor
payload, never an unbounded document.

```
market_display_name   "Plumbing — Brisbane, QLD"
opportunity_score     68.19
verdict               "watch"
confidence            0.725
signals[]             signal, score, band, confidence, headline
missing_signals[]     signals with no usable evidence
gates_applied[]       gate identifiers that capped the verdict (04 §6)
```

### 3.1 What must never enter a prompt

- Raw collector responses or scraped page content.
- Any personally identifying information. Business names in the density sample are
  transient under `02 §6` and have no role in the written analysis.
- Account identifiers, emails, API keys, internal IDs.
- Any instruction text originating from collected data. Evidence is **data**, not
  instruction — a vendor payload containing something that reads like a directive is
  quoted, never obeyed.

### 3.2 Why the payload is small

A bounded, structured prompt of roughly 2–4k tokens is cheap, fast, reproducible,
and impossible to poison with retrieved content. It also means prompt cost is
predictable per run (07 §8 budgets ~$0.05).

---

## 4. Required output schema

Strict. Additional properties rejected.

| Field | Type | Constraint |
|---|---|---|
| `summary` | string | 40–90 words, plain language, no markdown |
| `reasons` | array | **3–5** items, each `{n, title, body}`; `title` ≤ 60 chars |
| `recommended_action` | string | one sentence, must be consistent with `verdict` |
| `caveats` | array | 0–6 strings |

The report renders these directly (`05 §6`). The shape mirrors the four numbered
reasons in the approved product design.

---

## 5. Grounding rules

These are the difference between an explainable product and a plausible one.

1. **No invented numbers.** Every numeric token in the output must appear in the
   input payload. A post-generation check parses numbers out of the generated text
   and rejects any that are not present. This is a hard gate, not a warning.
2. **Missing signals are named.** Each entry in `missing_signals` must be
   acknowledged in `caveats`. Silence about a gap is a defect (`00 §7`).
3. **Gates are explained.** Each entry in `gates_applied` must be reflected in
   `caveats` in plain language — the reader must be able to see why a good score did
   not become a "pursue".
4. **The verdict is not re-litigated.** The model explains the verdict it was given.
   Output that argues for a different verdict fails validation.
5. **Estimates are labelled.** Customer value is a proxy (`04 §4.5`); any sentence
   built on it says so.
6. **No live-product or partnership claims** (`00 §7`).

### 5.1 Consistency checks applied after generation

| Check | On failure |
|---|---|
| Schema valid | retry once, then fallback |
| Every number present in input | retry once, then fallback |
| All `missing_signals` covered in caveats | append generated caveat |
| All `gates_applied` covered in caveats | append generated caveat |
| `recommended_action` matches verdict | retry once, then fallback |

---

## 6. Failure handling

```
generate ─▶ validate ─┬─ pass ─────────────▶ store, generator="llm"
                      └─ fail ─▶ retry ×1 ─┬─ pass ─▶ store, generator="llm"
                                           └─ fail ─▶ template provider,
                                                      generator="template"
```

`generator="template"` is a **first-class success state**, not an error. Clients
render it identically (`05 §6.1` rule 5). A run never fails because a model did.

Provider timeout, rate limit or outage takes the same path: the report ships,
generated deterministically, and says so in its caveats.

---

## 7. Prompts

- Version-controlled files under `engine/ai/prompts/`, named by version.
- `prompt_version` is stored on every report.
- A prompt is never edited in place once it has produced a stored report — a change
  means a new version.
- The system prompt states the grounding rules in §5; the user message carries only
  the §3 payload as JSON.

---

## 8. Evaluation set

A provider or prompt change is not shippable until the eval suite passes. Evals run
against **fixed evidence payloads**, so they are deterministic and free of vendor
dependence.

| Case | Asserts |
|---|---|
| Complete high-scoring market | 3–5 reasons; no invented numbers; action matches `pursue` |
| Partial run, one signal absent | absent signal named in caveats |
| Gated verdict (G4 declining) | caveat explains the cap; no argument for a higher verdict |
| Low confidence | hedged language; no assertive recommendation |
| All-weak market | action consistent with `pass`; no false encouragement |
| Adversarial payload — evidence field containing instruction-like text | text quoted or ignored, never followed |
| Numeric fidelity | every number in output traceable to input |

Eval cases live beside the fixtures already used by the walking skeleton, and run
in CI with the template provider as the control.

---

## 9. Model selection criteria

When a provider is approved, choose on:

1. **Reliable structured output** against a schema — the primary requirement.
2. **Instruction adherence** on the grounding rules, measured by §8, not by vibes.
3. **Cost per run** at ~3k in / ~700 out tokens.
4. **Latency** within the run's wall-clock budget.

A mid-tier model is the expected fit: the task is summarising structured data that
has already been analysed, not open-ended reasoning. Multi-model routing is out of
scope — every provider added doubles the eval surface.

---

## 10. Open questions

1. **Reason ordering.** Should reasons be ordered by signal weight, by sub-score, or
   by what the model judges most decision-relevant? Currently the template provider
   orders by sub-score.
2. **Locale.** Reports are written in English with Australian spelling. Confirm when
   markets outside AU are supported.
3. **Regeneration.** If a prompt version improves, may an existing report's analysis
   be regenerated in place, or does that require a new run? Recommended: a new
   `reports` row is not possible under the current one-row-per-run schema
   (`02 §3.11`), so regeneration overwrites and must bump `prompt_version` — decide
   before the first model-generated report is stored.
