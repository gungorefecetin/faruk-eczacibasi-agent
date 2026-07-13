# CLAUDE.md

Instructions for AI assistants working in this repository.

## What this project is

A CLI agent that answers a question by querying four frontier LLMs in parallel, having a judge model pick the best answer, then routing the *winning model* into a synthesizer role to merge all four candidates into one final answer.

Read `docs/PRD.md` for scope and `docs/ARCHITECTURE.md` for structure before making changes.

## Repository layout

```
main.py              CLI entry point
core/
  models.py          Candidate, JudgeResult, FinalAnswer
  providers.py       Provider ABC, OpenAIProvider, AnthropicProvider
  config.py          Model pool, judge, system prompts, constants
  pipeline.py        fanout → anonymize → judge → route → synthesize
docs/
  PRD.md             Scope, requirements, known risks
  ARCHITECTURE.md    Module boundaries, design decisions, failure modes
  DECISION-LOG.md    Append-only record of decisions and their triggers
```

## Invariants — do not break these

1. **Dependency direction is one-way:** `main → pipeline → config → providers → models`. Never import upward.
2. **`pipeline.py` has no vendor knowledge.** It operates on `model_id` strings and the `Provider` interface. If you find yourself writing `if model_id == "gemini"` in the pipeline, the abstraction is wrong.
3. **Adding a model touches `config.py` only.** Adding a provider family touches `providers.py` and `config.py` only.
4. **The judge never sees model identity.** `label_map` stays in the orchestrator. If a model name reaches a prompt, that is a bug.
5. **Candidate text is never normalized.** No `strip()`, no `unicodedata.normalize()`, no re-encoding. See DECISION-LOG D-005. This is non-negotiable — NFD normalization drops the Turkish dotless `ı` silently.
6. **Prompts are English; answers follow the question's language.** See D-004.

## Conventions

- Python 3.11+, `async`/`await` throughout the pipeline.
- Type hints on all function signatures. `dict[str, X]`, not `Dict[str, X]`.
- Dataclasses for data, ABC for the provider interface. No Pydantic in `core/` — nothing here is parsing untrusted input.
- Comments in Turkish are fine in code; all documentation is English.
- No new dependencies without an entry in DECISION-LOG.md.

## Working on this repo

**Before changing behavior,** check whether the change is already contemplated in PRD §8 (Known risks) or the Decision Log. Several apparent bugs are documented, deliberate MVP tradeoffs.

**When a decision is made,** append to `docs/DECISION-LOG.md`. Record what would overturn it, not just what was chosen. An entry without a falsification condition is not a decision, it is a preference.

**Do not add to the MVP scope.** PRD §3 lists explicit non-goals: web UI, streaming, caching, retries, cost tracking, evaluation harness. These are deferred, not forgotten. If a task seems to require one, say so rather than building it.

## Known gaps, in priority order

These are documented in DECISION-LOG and PRD. Do not silently fix them; they need to be done properly.

1. **D-009** — `_parse_judge` falls back to the first label without logging. The first label is a random candidate, so a judge that always returns malformed JSON produces a system that looks functional and is choosing at random. This needs a warning log before anything else ships.
2. **R-1** — the system may be performing selection rather than synthesis, because the synthesizer is anchored on its own output. Detect by comparing the final answer to the winning candidate's raw text.
3. **Synthesizer failure is unhandled** and propagates. It should fall back to returning the winning candidate verbatim.
4. **No structured logging.** Nothing above can be measured without it.

## What "done" means here

The MVP is not done when it produces an answer. It is done when it produces an answer, survives a dead provider, survives a malformed judge response, and emits enough information to tell whether synthesis is actually occurring.

An answer that looks good tells you nothing. The interesting question is always whether the pipeline did what it claims to do.
