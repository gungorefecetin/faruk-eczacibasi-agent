# Multi-Model Answer Synthesizer

Ask one question. Four frontier models answer it in parallel. A judge picks the best answer. The model that produced it then synthesizes all four candidates into a single final answer.

```
question ──┬──► chatgpt ──┐
           ├──► claude  ──┤
           ├──► gemini  ──┤──► judge ──► winner's model ──► final answer
           └──► grok    ──┘             (synthesizes all 4)
```

## Status

MVP. The pipeline runs. Whether the combined answer is actually *better* than any single model's answer is **not yet measured** — see `docs/PRD.md` §8 and §10.

## Setup

Requires Python 3.11+.

```bash
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:

```
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
XAI_API_KEY=
```

Model version strings in `core/config.py` drift as providers update their catalogs. Verify them against current provider documentation if you get a 404.

## Usage

```bash
python main.py "Why is the sky blue?"
```

Or without arguments, for an interactive prompt:

```bash
python main.py
```

Output:

```
--- Adaylar (4) ---
  chatgpt     2140 ms
  claude      1890 ms
  gemini       980 ms
  grok        2310 ms

Kazanan / sentezleyici: claude
Judge gerekçesi: Most complete explanation with correct physics.

--- Nihai cevap ---
...
```

### Web UI

A Streamlit chat interface sits over the same pipeline:

```bash
streamlit run app.py
```

The answer is shown as the hero; the winning model and latency appear as a
quiet caption, with the full breakdown — every candidate, the judge's rationale,
and the R-1 synthesis-vs-selection signal — behind a **details** expander.

The chat transcript is display-only. Each question is an independent, stateless
pipeline run; prior turns are **not** fed back to the models (multi-turn remains
a non-goal — see `docs/PRD.md` §3 and `docs/DECISION-LOG.md` D-013).

> ⚠️ **Restart Streamlit after editing anything under `core/`.** Streamlit
> re-executes `app.py` on every interaction, but Python caches imported modules:
> changes to `core/pipeline.py`, `core/config.py`, or `core/providers.py` do
> **not** reach a running process. Only `app.py`/`ui/` edits apply live. A stale
> process silently runs old code — pool, timeouts, budgets, all of it (this bit
> us: a day of UI tests ran a pre-Grok/Kimi pool). When in doubt:
> `pkill -f "streamlit run app.py" && streamlit run app.py`

## How it works

1. **Fan-out.** The question goes to all four models concurrently via `asyncio.gather`. Wall-clock latency is bounded by the slowest model, not the sum. A model that times out or errors is dropped; the pipeline continues with the survivors.

2. **Anonymize.** Candidates are shuffled and relabeled A/B/C/D. The judge never learns which model wrote which answer — this removes brand priors, and reshuffling per request removes any fixed-position advantage.

3. **Judge.** A small, cheap model reads the question and the four anonymous answers, and returns the winning label as JSON.

4. **Route.** The orchestrator maps the winning label back to its `model_id` using a table it never exposed to the judge.

5. **Synthesize.** That model receives all four candidates and merges them into one coherent answer.

## Configuration

Everything tunable lives in `core/config.py`: the model pool, the judge, the three system prompts, the per-proposer timeout, and `MIN_CANDIDATES` (the floor below which the request fails).

Adding or removing a model is a `config.py` edit. Adding a new provider family means one new `Provider` subclass in `providers.py`. The pipeline never changes.

## Documentation

| File | Contents |
|---|---|
| `docs/PRD.md` | Scope, requirements, known risks, milestones |
| `docs/ARCHITECTURE.md` | Module boundaries, design rationale, failure modes |
| `docs/DECISION-LOG.md` | Every decision, its reasoning, and what would overturn it |
| `CLAUDE.md` | Invariants and conventions for AI-assisted development |

## Known limitations

The design has real open questions, documented rather than hidden:

- **The synthesizer may not be synthesizing.** It is anchored on its own winning answer and may simply polish it while ignoring the other three. This has not been measured.
- **The judge is a single point of failure.** Unlike a flat ensemble, a bad selection here propagates into everything downstream.
- **A malformed judge response silently selects a random candidate.** This path needs logging before it can be trusted.
- **Output character varies per query,** since the synthesizer changes with the winner.

See `docs/PRD.md` §8 for the full list and the detection strategy for each.
