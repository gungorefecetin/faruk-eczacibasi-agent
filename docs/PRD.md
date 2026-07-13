# PRD — Multi-Model Answer Synthesizer (MVP)

**Status:** Draft
**Owner:** Güngör Efe Çetin
**Last updated:** 2026-07-09

---

## 1. Problem

A single LLM answering a question is a single sample from a single distribution. It carries that model's blind spots, training biases, and failure modes. When four frontier models are asked the same question, they frequently agree on a correct core and disagree at the edges — and that disagreement carries signal.

Today there is no cheap way to exploit this. A user who wants a better answer must manually query several models, read all outputs, and merge them by hand. This is slow, inconsistent, and does not scale.

## 2. Goal

Build an agent that accepts a single user question, queries four frontier models in parallel, selects the strongest answer via a judge model, and has the model that produced the winning answer synthesize all four candidates into one final answer.

**Success for the MVP is a working, observable pipeline — not a proven quality improvement.** Proving quality improvement is explicitly out of scope and deferred to the evaluation phase (see §8).

## 3. Non-goals (MVP)

The following are deliberately excluded. Each is a real need; none is needed to validate the core loop.

- Web UI or API surface (CLI only)
- Streaming responses
- Conversation history / multi-turn
- Retrieval, tools, or function calling
- Caching, rate-limit handling, retry with backoff
- Cost tracking and token accounting
- Quality evaluation harness
- Authentication, multi-tenancy, persistence

## 4. Users

**Primary (MVP):** the developer, running the pipeline locally to validate the loop.

**Eventual:** anyone asking a question where answer quality matters more than latency or cost — research questions, technical decisions, ambiguous factual queries.

## 5. Functional requirements

| ID | Requirement |
|----|-------------|
| FR-1 | Accept a single question as a CLI argument or stdin prompt. |
| FR-2 | Dispatch the question to four proposer models **in parallel**. |
| FR-3 | Isolate per-model failures. A timeout or API error on one model must not fail the request. |
| FR-4 | Proceed if at least `MIN_CANDIDATES` (default 2) proposers returned a non-empty answer; otherwise raise. |
| FR-5 | Shuffle candidate order and assign neutral labels (A, B, C, D) before showing them to the judge. |
| FR-6 | The judge model must never see model identities or brand names. |
| FR-7 | The judge returns a winning label and a one-sentence rationale as JSON. |
| FR-8 | Resolve the winning label back to its `model_id` via a label→candidate map held only by the orchestrator. |
| FR-9 | The winning model becomes the synthesizer for this request. |
| FR-10 | The synthesizer receives all candidates (same shuffled, anonymized block) and produces one final answer. |
| FR-11 | Return the final answer plus: winning model, judge rationale, per-candidate latency. |
| FR-12 | The final answer must be written in the same language as the question. |

## 6. Non-functional requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | Wall-clock latency ≈ `max(proposer latency) + judge + synthesis`, not the sum of proposer latencies. |
| NFR-2 | Per-proposer timeout: 60s, independently enforced. |
| NFR-3 | Adding or removing a model must require changes to `config.py` only — never to `pipeline.py`. |
| NFR-4 | Adding a new provider family must require changes to `providers.py` and `config.py` only. |
| NFR-5 | API keys are read from environment variables. No key is ever committed or logged. |
| NFR-6 | Candidate text must never be normalized, stripped, or Unicode-transformed before reaching the judge or synthesizer. |

> **On NFR-6:** any Unicode normalization applied to model output risks silently corrupting non-ASCII text. NFD normalization in particular decomposes and can drop characters such as the Turkish dotless `ı`. The MVP passes candidate text through verbatim. If normalization is ever introduced, it requires a dedicated test suite covering the target languages first.

## 7. Model pool

| `model_id` | Model | Transport | Key |
|---|---|---|---|
| `chatgpt` | `gpt-4o` | OpenAI SDK | `OPENAI_API_KEY` |
| `claude` | `claude-sonnet-4-5` | Anthropic SDK | `ANTHROPIC_API_KEY` |
| `gemini` | `gemini-3.5-flash` | OpenAI SDK, custom `base_url` | `GEMINI_API_KEY` |
| `grok` | `grok-4.3` | OpenAI SDK, custom `base_url` | `XAI_API_KEY` |
| judge | `claude-haiku-4-5` | Anthropic SDK | `ANTHROPIC_API_KEY` |

Model version strings drift. They are configuration, not architecture, and must be verified against each provider's current documentation before a deployment.

## 8. Known risks

These are properties of the chosen design, not bugs. They are documented here so that they are measured rather than discovered.

### R-1 — Silent degeneration to selection

The synthesizer is the model that produced the winning candidate. Two biases compound: **anchoring** (a model asked to improve on a draft tends to polish rather than rewrite) and **self-preference** (LLMs favor their own generations). The likely failure is that the synthesizer lightly edits its own answer and ignores the other three — meaning the system performs *selection*, not *synthesis*, while appearing to work.

*Detection:* compare the final answer against the winning candidate's raw text. High similarity across many queries indicates degeneration.

### R-2 — Judge as single point of failure

In a flat mixture-of-agents design, a bad candidate is diluted by the others. Here, a judge error propagates: everything downstream is built on the wrong draft. Errors are amplified rather than averaged out.

*Mitigation (post-MVP):* have the judge return a full ranking with scores; fall back to a fixed strong synthesizer when the top-1 and top-2 scores are near-tied.

### R-3 — Judge bias

LLM judges exhibit **position bias** (favoring the first or last candidate) and **verbosity bias** (mistaking length for quality). Both now sit on the critical path. Shuffling (FR-5) addresses position bias. Verbosity bias is addressed only by prompt instruction, which is weak.

*Mitigation (post-MVP):* pairwise comparison instead of listwise selection.

### R-4 — Judge family affinity

The judge is a Claude model and `claude` is in the pool. A judge may favor outputs from its own model family.

*Detection:* run the judge with an out-of-family model and compare the distribution of winners.

### R-5 — Unpredictable output character

The synthesizer changes per request, so tone and style vary between queries. Latency and cost are also unpredictable, since the synthesizer's identity is not known in advance.

## 9. Open questions

- Does dynamic-winner synthesis beat a fixed strong synthesizer? (Untested. This is the central assumption of the design.)
- Does synthesis beat selection alone? (Untested. This is the R-1 question.)
- Should the judge be part of the pool, or always external to it?
- What is the right `MIN_CANDIDATES` floor?

## 10. Milestones

| # | Milestone | Exit criterion |
|---|---|---|
| M0 | Skeleton | Code compiles; module boundaries fixed. **Done.** |
| M1 | First live run | One question end-to-end against all four providers. |
| M2 | Robustness | Judge JSON parsing tested against malformed output; killing one provider does not fail the request. |
| M3 | Instrumentation | Structured log per request: winner, latencies, similarity of final answer to winning candidate. |
| M4 | R-1 check | Enough data to state whether synthesis is occurring at all. |
| M5 | Evaluation | Compare `dynamic_winner` / `fixed_strongest` / `select_only` on a held-out question set. |

M5 is where the project stops being a demo and becomes a result. M1–M4 exist to make M5 trustworthy.

## 11. Acceptance criteria (MVP)

The MVP is complete when:

1. `python main.py "<question>"` returns a final answer.
2. Disabling any single provider's key still produces a final answer.
3. A malformed judge response does not crash the pipeline, and the fallback path is logged.
4. The winning model and per-candidate latencies are printed.
5. A Turkish question yields a Turkish final answer with no character corruption.
