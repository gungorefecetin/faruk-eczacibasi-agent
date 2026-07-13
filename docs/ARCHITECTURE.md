# Architecture

## Pipeline

```
question
   │
   ├──► chatgpt  ─┐
   ├──► claude   ─┤  asyncio.gather, independent timeouts
   ├──► gemini   ─┤  failures isolated per model
   └──► grok     ─┘
                  │
                  ▼
         [Candidate, Candidate, ...]          fanout()
                  │
                  ▼
         shuffle + label A/B/C/D              anonymize()
         label_map: {A: Candidate, ...}       ◄── stays in orchestrator
                  │
                  ▼
         judge model → {"winner": "B"}        judge()
                  │
                  ▼
         label_map["B"].model_id → "grok"     ◄── identity resolved here
         synthesizer = pool["grok"]
                  │
                  ▼
         synthesize all 4 candidates          synthesize()
                  │
                  ▼
              FinalAnswer
```

## Module boundaries

Dependencies flow in one direction only:

```
main.py → pipeline.py → config.py → providers.py → models.py
```

| Module | Responsibility | Must not |
|---|---|---|
| `models.py` | Data shapes: `Candidate`, `JudgeResult`, `FinalAnswer` | Import anything from the project |
| `providers.py` | One async `complete()` interface over heterogeneous SDKs | Know about the pipeline or prompts |
| `config.py` | Model pool, judge, system prompts, constants | Contain control flow |
| `pipeline.py` | The six-step flow | Know which vendor a `model_id` maps to |
| `main.py` | CLI, printing | Contain logic |

This is what makes NFR-3 and NFR-4 hold. `pipeline.py` operates on `model_id` strings and the `Provider` interface; it has no vendor knowledge. Swapping Grok for Mistral is a `config.py` edit.

## Key design decisions

### Anonymization is load-bearing, not cosmetic

The judge sees `--- Cevap A ---` blocks in shuffled order. It never sees a model name. The orchestrator holds `label_map: dict[str, Candidate]`, so it can resolve `"B"` back to `"grok"` after the verdict.

Two properties fall out of this:

- **Brand bias removed.** A judge told "this is from GPT-4" carries a prior. Anonymous labels remove it.
- **Position bias reduced.** `random.sample()` reshuffles on every request, so no model occupies a fixed slot.

The label→model mapping must never leave the orchestrator. If it reaches a prompt, both properties are lost.

### Failure isolation over transactional correctness

`asyncio.gather` collects results from `_call_one`, which catches every exception and returns a `Candidate` with `error` set. Failed candidates are filtered by `.ok`. The pipeline proceeds on partial results as long as `len(candidates) >= MIN_CANDIDATES`.

The alternative — failing the whole request when one provider is down — is worse for a system whose entire premise is redundancy across providers.

### Provider abstraction over vendor SDKs

Three of the four models are reached through the OpenAI SDK with a custom `base_url`. Only Anthropic requires its own client, because its message and content-block shapes differ.

`Provider.complete(system, prompt, max_tokens) -> str` is the whole surface. It returns a plain string. Streaming, tool calls, and structured output are all absent by design — the MVP does not need them, and adding them to the interface now would constrain the pipeline unnecessarily.

### The synthesizer is chosen at runtime

`pool[winner.model_id]` is the entire routing mechanism. The synthesizer is not a distinct object; it is a proposer that has been handed a different system prompt.

This is the design's most consequential choice and its least tested assumption. See PRD §8, R-1 and R-2.

## Failure modes and handling

| Failure | Handling | Where |
|---|---|---|
| Proposer timeout | Candidate marked with `error`, filtered out | `_call_one` |
| Proposer API error | Same | `_call_one` |
| Fewer than 2 candidates | `RuntimeError` | `run` |
| Judge returns malformed JSON | Regex-extract first `{...}`; on failure select first label | `_parse_judge` |
| Judge returns an invalid label | Same fallback | `_parse_judge` |
| Synthesizer fails | **Unhandled — propagates.** | — |

The last row is a known MVP gap. A synthesizer failure should fall back to returning the winning candidate verbatim; it currently raises.

The `_parse_judge` fallback deserves scrutiny. Selecting the first label when parsing fails is *not* a neutral default — the first label is a random model, so the fallback silently converts the judge into a coin flip. It must be logged, or a judge that never returns valid JSON will look like a working system.

## Concurrency

Proposers run in parallel; judge and synthesis are strictly sequential and depend on all prior stages.

```
wall_clock ≈ max(proposer_latency) + judge_latency + synthesis_latency
```

Not `sum(proposer_latency)`. This is the point of `asyncio.gather`. The p99 is bound by the slowest proposer plus the synthesis time of whichever model happened to win — which is unpredictable, since the synthesizer is chosen at runtime.

## Data flow of candidate text

Candidate text is passed through **verbatim** from provider response to judge prompt to synthesizer prompt. No stripping, no normalization, no encoding transformation.

This is deliberate (PRD NFR-6). Unicode normalization on model output is a known source of silent corruption in non-ASCII text — NFD decomposition in particular can drop characters such as the Turkish dotless `ı`. Any future text-processing step needs its own test suite before it touches this path.

## What is not here

No caching, no retries, no backoff, no token accounting, no cost tracking, no persistence, no tracing. Each is a deliberate omission for the MVP. The one that will hurt first is the absence of structured logging — without it, R-1 (silent degeneration to selection) cannot be detected.
