# Decision Log

Append-only. Each entry records what was decided, why, and what would overturn it.

---

## D-001 — Single-layer pipeline, not layered MoA

**Date:** 2026-07-09
**Status:** Accepted

Classic Mixture-of-Agents stacks multiple layers, each layer's agents receiving all outputs from the previous layer. We use one layer: N proposers → judge → synthesizer.

**Why:** each additional layer multiplies wall-clock latency and cost. The marginal quality gain is dataset-dependent and unproven for our use case. Establish the single-layer baseline first.

**Overturned if:** evaluation shows a second layer produces a quality gain that justifies roughly doubled latency.

---

## D-002 — The winning model becomes the synthesizer

**Date:** 2026-07-09
**Status:** Accepted (externally mandated)

The judge selects the best candidate; the model that produced it is routed into the synthesizer role for that request.

**Why:** direction from project stakeholders. There is a coherent argument for it: anchoring on a strong draft resists the homogenization that flat synthesis-from-scratch tends to produce, and preserves a single consistent voice.

**Argument against:** answer generation and answer synthesis are different capabilities. A model that produced the best single answer is not necessarily the best at merging four texts. The design also compounds anchoring bias with self-preference bias, since the synthesizer is fed its own output as one of the candidates. See PRD R-1.

**Overturned if:** evaluation shows `fixed_strongest` (judge selects, fixed strong model synthesizes) beats `dynamic_winner` on quality. This is a config-flag experiment, not a rewrite.

---

## D-003 — Anonymize and shuffle candidates before the judge

**Date:** 2026-07-09
**Status:** Accepted

Candidates are shuffled per request and labeled A/B/C/D. The judge never sees model identity. The orchestrator retains `label_map` to resolve the winner.

**Why:** brand priors and position bias are both documented LLM judge failure modes. Shuffling costs one line and removes a fixed-slot advantage. Anonymization costs nothing and removes brand priors.

**Overturned if:** never, for the judge. If model identity ever proves useful for routing, it belongs in the orchestrator, not in the prompt.

---

## D-004 — System prompts in English, answers in the user's language

**Date:** 2026-07-09
**Status:** Accepted

All three system prompts are English. Each carries an explicit rule: answer in the language of the question.

**Why:** three reasons. Instruction-following on format constraints (the judge's strict JSON) is more reliable in English. The pool is heterogeneous and must be designed for its weakest link. English system prompts consume fewer tokens per request, and system prompts are sent on every call.

**Note:** this is a reasoned guess, not a measured result. It is cheap to test: run the same question set with Turkish and English prompt variants, compare judge JSON parse success rate and final-answer language consistency.

**Overturned if:** that test shows no difference, in which case prompt language becomes a free choice.

---

## D-005 — Candidate text is never normalized

**Date:** 2026-07-09
**Status:** Accepted

Provider output flows to the judge and synthesizer verbatim. No `strip()`, no Unicode normalization, no encoding transformation.

**Why:** Unicode normalization silently corrupts non-ASCII text. NFD decomposition can drop characters such as the Turkish dotless `ı`, and the failure is invisible in casual testing — the text looks almost right. Since the system must handle Turkish, this class of bug is unacceptable and easiest to avoid by not introducing the step at all.

**Overturned if:** a text-processing step becomes necessary, in which case it ships with a Unicode test suite covering every target language *before* it is wired into the path.

---

## D-006 — OpenAI SDK as the transport for three of four models

**Date:** 2026-07-09
**Status:** Accepted

Gemini (`generativelanguage.googleapis.com/v1beta/openai/`) and Grok (`api.x.ai/v1`) both expose OpenAI-compatible chat-completions endpoints. Only Anthropic needs its own client.

**Why:** one `OpenAIProvider` class covers three vendors. Less code, fewer SDK version conflicts.

**Cost:** the compatibility layer is a subset. Provider-specific features (Gemini thinking config, Grok reasoning effort) are unreachable without `extra_body`. Acceptable for the MVP, which uses none of them.

**Overturned if:** a provider-specific capability becomes necessary, in which case that vendor gets a dedicated `Provider` subclass. The abstraction already supports this.

---

## D-007 — Judge is a small, cheap model

**Date:** 2026-07-09
**Status:** Accepted, with a known flaw

`claude-haiku-4-5` judges. It is not generating; it is discriminating.

**Why:** discrimination is cheaper than generation. A large judge would roughly double the cost of every request for a task that returns fifteen tokens of JSON.

**Known flaw:** the judge is from the same model family as one of the four proposers. Family affinity may bias selection toward `claude`. See PRD R-4.

**Overturned if:** the distribution of winners shows a statistically implausible skew toward `claude`. The fix is to move the judge out of family, not to make it larger.

---

## D-008 — Fail-open on partial proposer results

**Date:** 2026-07-09
**Status:** Accepted

If a proposer times out or errors, its candidate is dropped. The pipeline proceeds with the survivors as long as at least `MIN_CANDIDATES` (2) remain.

**Why:** the premise of the system is redundancy across providers. Failing the whole request because one vendor is down inverts that premise.

**Open:** 2 is a guess. With two candidates the judge's task degenerates to a coin flip on ties, and the synthesizer has little to merge. 3 may be the right floor.

---

## D-009 — Judge JSON parse fallback selects the first label

**Date:** 2026-07-09
**Status:** Accepted provisionally — **flagged**

When the judge's output cannot be parsed, `_parse_judge` returns the first label with an explanatory reason string.

**Why:** it keeps the pipeline running.

**Why this is dangerous:** the first label belongs to a randomly shuffled candidate. The fallback therefore converts the judge into a uniform random selector, silently. A judge that never returns valid JSON would produce a system that appears to work and is in fact choosing at random.

**Required before M2:** this path must emit a warning-level log. Without it, the failure is undetectable. It is the highest-priority correctness gap in the MVP.

**Resolved 2026-07-09:** `_parse_judge` now emits a `logger.warning` (including a truncated dump of the raw judge output) whenever it falls back to the first label. The fallback behavior is unchanged; it is now observable. See D-012.

---

## D-010 — Missing provider keys skip the model instead of crashing

**Date:** 2026-07-09
**Status:** Accepted

`build_pool()` and `build_judge()` previously read `os.environ[key]` eagerly, so an absent key raised `KeyError` at construction time — before any fail-open logic. A model with no key now simply does not enter the pool; the judge falls back Anthropic → OpenAI → Gemini.

**Why:** this is D-008 (fail-open on partial results) extended to construction time. A system whose premise is redundancy across providers should run on whatever providers are configured, not demand all four. It also makes local testing with a subset of keys possible without editing `config.py`.

**Note:** `MIN_CANDIDATES` (2) still governs whether the run proceeds. With only OpenAI + Gemini configured the pool is exactly 2 — at the floor, and the judge's task degenerates toward a coin flip (see D-008 "Open"). This is acceptable for testing, not a claim about production quality.

**Overturned if:** a deployment needs to *require* a specific provider be present (e.g. a fixed strong synthesizer). Then presence becomes a validated precondition, not a silent skip.

---

## D-011 — `python-dotenv` for `.env` loading

**Date:** 2026-07-09
**Status:** Accepted

`main.py` calls `load_dotenv()` before importing `core`, so keys in a local `.env` reach `os.environ`. Adds one dependency (`python-dotenv>=1.0`).

**Why:** the README already instructed `cp .env.example .env`, but nothing loaded that file — keys had to be `export`ed manually. This closes the gap between the documented setup and actual behavior. `.env` is gitignored; `.env.example` holds only empty placeholders.

**Overturned if:** the project moves to a secret manager or container-injected env, where a `.env` file is no longer the delivery mechanism.

---

## D-012 — Timeouts and fallbacks on the judge/synthesis critical path

**Date:** 2026-07-09
**Status:** Accepted

Three changes, all on the previously-unguarded critical path after fan-out:

1. **Judge and synthesizer calls are wrapped in `asyncio.wait_for(TIMEOUT_S)`.** Proposers were already time-bounded (`_call_one`); the judge and synthesizer were not, so either could hang a request indefinitely.
2. **Synthesizer failure falls back to the winning candidate's raw text**, as ARCHITECTURE.md's failure-mode table already prescribed. It previously propagated and crashed the request.
3. **One structured `logger.info` line per completed request** records winner, per-candidate latencies, and whether the final answer is byte-identical to the winning candidate. The last field is the first cheap signal for R-1 (selection-vs-synthesis) — verbatim equality means synthesis did nothing.

**Why:** CLAUDE.md's definition of "done" requires surviving a dead provider, surviving a malformed judge, and emitting enough to tell whether synthesis is occurring. These three changes cover the second and third; D-010 covers the first.

**Overturned if:** structured logging moves to a real emitter (JSON lines / OpenTelemetry). The verbatim-equality check is a placeholder; true R-1 measurement wants a similarity metric, not exact match. That is M3/M4 work, not this change.

---

## D-013 — Streamlit chat UI as a second top-level surface

**Date:** 2026-07-09
**Status:** Accepted (externally mandated)

`app.py` adds a Streamlit chat interface over the pipeline, alongside `main.py`. New dependency: `streamlit>=1.40`. Styling is isolated in `ui/theme.py`.

**Why:** direct stakeholder request. PRD §3 lists "Web UI or API surface" as an MVP non-goal, so this is an explicit, authorized expansion of scope — recorded here rather than left to silently contradict the PRD.

**How the invariants are held:**
- **Dependency direction (CLAUDE.md #1):** `app.py → core.pipeline`, exactly as `main.py` does. `core/` and `ui/` import nothing from each other; `core/` has no knowledge of either UI. The dependency graph gains a second root, not an upward edge.
- **No multi-turn (PRD §3):** the chat transcript is *display-only*, held in `st.session_state`. Each submission is an independent, stateless `run(question)` call — prior turns are never fed to the models. The "no conversation history" non-goal is preserved at the core layer; only the presentation is conversational.
- **Observability is surfaced, not hidden:** winner, per-candidate latencies, judge rationale, and the R-1 verbatim-equality signal are all rendered (subtly by default, in full behind a "details" expander). The UI is a window onto the pipeline's instrumentation, not a cover over it.

**Overturned if:** the project needs a real multi-user/API surface (FastAPI + a JS frontend), at which point Streamlit's single-session model becomes the constraint and this becomes a prototype to replace. True multi-turn would additionally require changing `run()`'s signature and a separate decision — it is explicitly *not* enabled here.

---

## D-014 — `st.chat_message` avatar must be an emoji/image, not an arbitrary glyph

**Date:** 2026-07-09
**Status:** Accepted

The assistant avatar is `🔹` (a real emoji), not the `◇` glyph used in the header markdown.

**Why:** `st.chat_message(avatar=...)` routes its argument through image-loading; a bare geometric character like `◇` raises `StreamlitAPIException: Failed to load the provided avatar value as an image`. Emojis are a supported avatar type; arbitrary Unicode symbols are not. `◇` remains fine in `st.markdown` (the header), which does not go through avatar processing.

**Overturned if:** the UI moves to a custom-rendered message component that does not use `st.chat_message`, in which case any glyph can be drawn directly.

---

## D-015 — Azure OpenAI as a provider family; Azure GPT as the judge

**Date:** 2026-07-09
**Status:** Accepted

A new `AzureOpenAIProvider` (in `providers.py`) reaches Azure-hosted OpenAI models via `AsyncAzureOpenAI`. `build_judge()` now prefers Azure when a `config.json` is present, ahead of the Anthropic → OpenAI → Gemini chain. Configuration is read from a gitignored `config.json` at repo root (`api_key`, `api_version`, `azure_endpoint`, `deployment_name`); `config.example.json` is the committed template.

**Why (family, per NFR-4):** Azure OpenAI is OpenAI-compatible at the call level but differs at client construction — it needs `azure_endpoint`, `api_version`, and a *deployment name* (distinct from the model name). That justifies a dedicated `Provider` subclass rather than reusing `OpenAIProvider` with a `base_url`. The change touches `providers.py` + `config.py` only; the pipeline is untouched.

**gpt-5.x parameter note:** `AzureOpenAIProvider.complete()` sends `max_completion_tokens`, not `max_tokens`. The gpt-5.x generation rejects `max_tokens` with a 400 (`Unsupported parameter: 'max_tokens' ... Use 'max_completion_tokens' instead`). Verified live against a gpt-5.1 deployment: with `max_tokens` the judge 400'd and fell through to the D-009 random fallback (no crash, but no real judgment); with `max_completion_tokens` the judge returned a substantive verdict. Note this diverges from `OpenAIProvider`, which still sends `max_tokens` for the gpt-4o-class proposers — a second reason the Azure family is its own subclass, not a `base_url` variant.

**Why (judge choice):** routing an Azure GPT model into the judge seat moves the judge *out of the proposer pool's family*. The default judge is Claude and `claude` is a proposer (D-007's known flaw, PRD R-4: family affinity). An out-of-family judge both mitigates and lets us measure R-4 by comparing the winner distribution against the in-family baseline.

**Why (config.json, not .env):** the user's Azure credentials already arrive as a 4-field JSON. Reading it directly avoids reshaping their input. It carries a key, so it is gitignored exactly like `.env`. A missing/malformed/incomplete `config.json` returns `None` and the judge falls back to the existing chain — fail-open (D-008/D-010) preserved.

**Overturned if:** proposers also need Azure (then the pool gains Azure entries the same way), or Azure credentials move to a secret manager (then `config.json` reading is replaced, not the provider). If evaluation shows the out-of-family judge changes winner distribution materially, that is the R-4 signal the design was waiting for — a result, not a reason to revert.

---

## D-016 — Per-provider `max_retries` control on `OpenAIProvider`

**Date:** 2026-07-09
**Status:** Accepted (parameter retained, not currently applied)

`OpenAIProvider` accepts an optional `max_retries`; when set, it is passed to `AsyncOpenAI`. Default behavior (SDK's 2 retries) is unchanged when the parameter is omitted.

**Why:** the SDK auto-retries 429/503 with backoff. On a quota-exhausted free-tier key (Gemini, daily limit 20) this adds pointless delay — the quota won't recover within the request. We measured `max_retries=0` on Gemini and confirmed the 429 retry spam disappeared.

**But — and this is the finding:** disabling retries did *not* reduce wall-clock latency. With retries off, Gemini still hung ~49s (a quota-blocked connection stays open toward `TIMEOUT_S`, not just the retry loop). This proved the real bottleneck was fanout waiting on the slowest proposer, not retries — which motivated D-017. The `max_retries` hook is kept for future use but Gemini currently runs with default retries, because D-017 makes retry behavior irrelevant to latency.

**Overturned if:** a provider's retries prove harmful in a way D-017 does not already neutralize.

---

## D-017 — Adaptive fanout: proceed on enough candidates, don't wait for the slowest

**Date:** 2026-07-09
**Status:** Accepted

`fanout` no longer uses a plain `asyncio.gather` (which blocks on the slowest proposer). Instead: (1) wait until `MIN_CANDIDATES` successful candidates arrive, (2) allow a short `FANOUT_GRACE_S` (3s) window for additional healthy candidates, (3) cancel whatever is still pending. Wall-clock ≈ (MIN-th fastest proposer + grace), not max(all proposers).

**Why:** measured, not assumed. A quota-blocked Gemini hung ~49s and dragged total latency to ~69s even though chatgpt (8.8s) and claude (10.6s) had long finished. `gather` waits for the slowest; one dead-but-slow provider locked the whole pipeline. After this change, the same class of request completes in ~20s.

**Quality guard (the reason for the grace period, not a bare "first-N"):** cutting off the instant `MIN_CANDIDATES` arrive would discard a candidate that was only slightly slower, shrinking the synthesis input and worsening R-1 risk. The grace window captures late-but-healthy proposers while refusing to wait on the genuinely dead. This trades a bounded few seconds against keeping more candidates — deliberately favoring quality where it is cheap. The grace is a *ceiling*, not a fixed wait: `asyncio.wait(timeout=...)` returns the instant all pending tasks finish, so when every model is fast the fanout returns at the slowest healthy proposer with zero grace penalty (verified: 5 sub-second models return in ~0.5s, not grace-time).

**`FANOUT_GRACE_S` tuning — 3s → 5s, from measured data:**
- At 3s: a request where claude arrived at ~10s had claude *cancelled*, synthesizing from 2 candidates (chatgpt + gemini). A healthy model was dropped for the sake of the ceiling.
- Raised to 5s. Next live request: chatgpt (4.4s) + gemini (5.2s) filled `MIN_CANDIDATES`, then claude arrived at 8.5s and *was* caught inside the 5s grace window — synthesis ran on all 3, R-1 similarity 0.341. Wall-clock was ~15.5s, and the grace cost was only ~0.5s because claude landed mid-window and `asyncio.wait` returned immediately on completion rather than waiting out the full 5s.
- Net: 5s catches the common ~5–8s stragglers without the "always pay 5s" cost the ceiling semantics prevent. 10s+ models (occasionally claude) still miss — acceptable, since MIN_CANDIDATES is met and the alternative is unbounded latency.

**Second tuning — 5s → 8s, after adding the Azure Foundry proposers (D-020):** Grok and Kimi consistently arrive at ~11–13s (Foundry endpoint is slower than the direct APIs). At 5s grace they were cancelled almost every request — the pool said "5 models" but synthesis ran on 3. Measured 3 rounds at 8s: 2 of 3 caught all 5 candidates (Grok at 11.1s and 12.4s, both inside the window; one round dropped Grok when chatgpt returned unusually fast at 3.7s, closing the window early). Round 2 Grok even *won* and synthesized. R-1 similarity fell to 0.10–0.30 with 5 candidates (vs ~0.34 with 3) — more candidates measurably increased how much the synthesizer rewrote, confirming "more candidates = more synthesis." Cost: wall-clock rose to ~20–30s. Deliberate quality-for-latency trade, chosen from measurement not guess.

**Interaction with adaptive winner (D-002):** fewer candidates raises anchoring/self-preference risk, so this change makes the R-1 metric (D-018) more important, not less — hence both shipped together.

**Overturned if:** `FANOUT_GRACE_S` proves mistuned (too short drops good candidates; too long reintroduces the latency it removed), or evaluation shows dropping the slowest proposer measurably degrades answer quality. Both are tunable, not structural. Current value (5s) is set from a handful of live runs, not a rigorous sweep — revisit once there is a question set to measure the candidate-count / latency tradeoff across.

---

## D-018 — R-1 signal is a real similarity ratio, not verbatim equality

**Date:** 2026-07-09
**Status:** Accepted

The per-request log and `FinalAnswer` now carry `winner_similarity` — `difflib.SequenceMatcher(final, winning_candidate).ratio()`, 0.0–1.0 — replacing the previous `final_matches_winner_verbatim` boolean. The UI flags ≥0.95 as likely selection-not-synthesis.

**Why:** the boolean was too weak. A synthesizer that changed one token scored `False` ("synthesis occurred") while having done nothing but polish — exactly the R-1 degeneration it was meant to catch. A continuous ratio distinguishes "lightly polished own answer" (~0.95+) from "genuinely rewritten/merged" (measured 0.574 on a live run). Zero new dependency (`difflib` is stdlib), zero network cost (local string op).

**Why now, and why this over R-2/prompt work:** D-017 sometimes synthesizes from fewer candidates, raising R-1 risk — so the signal that detects R-1 had to get sharper first. This metric is also the prerequisite for the deferred quality work (judge ranking / fixed-strongest fallback for R-2, prompt tuning): all of it needs a numeric "did synthesis actually happen?" to be judged against. Measurement precedes correction — the same lesson as D-009.

**Overturned if:** `difflib` ratio proves a poor proxy for semantic synthesis (e.g. a full paraphrase scores low similarity yet adds nothing) — then it is replaced by an embedding-based similarity, which *is* a new dependency and its own decision. The 0.95 threshold is a starting guess pending evaluation data.

---

## D-019 — Synthesizer emits its merge rationale; UI reveals it on demand

**Date:** 2026-07-09
**Status:** Accepted

The synthesizer now returns two parts — a short synthesis rationale (which candidates it leaned on, what it merged/dropped, how it resolved conflicts, referring to candidates by letter) and the final answer — separated by a sentinel line `===ANSWER===`. `pipeline._split_synthesis` parses them; `FinalAnswer.synthesis_reasoning` carries the rationale; the UI shows it in the `details` expander under a "synthesis · how it was merged" label, distinct from the judge's "why this won".

**Why structured single-call over alternatives:** native reasoning/thinking tokens aren't uniformly exposed across the pool and would force a per-vendor change to the plain-string `Provider` interface; a second explain-it call doubles synthesis latency and yields a post-hoc rationalization rather than the actual merge. One call with a delimited output is reliable, always present, and keeps parsing in the pipeline (where judge parsing already lives) — the `Provider` interface is untouched.

**Why a sentinel delimiter, not JSON:** the answer is long-form markdown (headers, lists, newlines). JSON-escaping it is fragile and a single malformed escape would lose the answer. Splitting on a sentinel line is robust to arbitrary answer content.

**Fail-safe (same philosophy as D-009):** if the delimiter is absent, `_split_synthesis` returns the entire response as the answer with empty reasoning — a formatting hiccup never costs the user their answer. The UI simply omits the reasoning section when it is empty (also the case when synthesis fell back to the winning candidate verbatim).

**NFR-6 preserved:** only the *reasoning* is stripped for display; the answer body is passed through verbatim — no strip, no normalization. Unit-tested that a dotless `ı` and trailing whitespace in the answer survive the split byte-for-byte.

**Refinement — self-header stripping:** in practice the synthesizer sometimes prefixed its rationale with its own title (e.g. `**Sentez Gerekçesi:**`), which is redundant with the UI's section label and leaked literal `**` markdown. `_strip_reasoning_header` removes a leading label — but only conservatively: the prefix must be ≤4 words *and* either bold or Title-Case. A first attempt used a ≤6-word guard and would have eaten the opening clause of genuine reasoning like *"I chose A for one reason: ..."*; the unit test caught it before it shipped, and the guard was tightened. This applies only to the reasoning (display text), never the answer body.

**Overturned if:** the two-part instruction measurably degrades answer quality (a model spending effort on rationale may shorten the answer), or a deployment's native reasoning trace becomes worth exposing directly. The rationale is currently a self-report and may not perfectly reflect the true merge — treat it as explanatory, not audit-grade.

---

## D-020 — Azure AI Foundry inference as a provider family; Grok + Kimi as proposers

**Date:** 2026-07-09
**Status:** Accepted

A new `AzureInferenceProvider` (in `providers.py`) reaches Azure AI Foundry-hosted models via the `azure.ai.inference` SDK's async `ChatCompletionsClient`. Grok (`grok-4.3`) and Kimi (`Kimi-K2.6`) join `build_pool()` as proposers, read from gitignored `config.grok.json` / `config.kimi.json` (fields: `endpoint`, `api_key_env`, `model`). `config.foundry.example.json` is the committed template. Pool is now 5 proposers; Azure gpt-5.1 stays the judge. New dependencies: `azure-ai-inference>=1.0.0b9`, `aiohttp>=3.9`.

**Why a distinct family (not `AzureOpenAIProvider`, per NFR-4):** despite the superficial "Azure" overlap, this is a different service. `AzureOpenAIProvider` uses the OpenAI SDK against `*.openai.azure.com` (the gpt-5.1 judge). Foundry inference uses a *different SDK* (`azure.ai.inference`), a *different endpoint type* (`*.services.ai.azure.com`), and *different auth* (`AzureKeyCredential`, not a bare key string). Reusing `AzureOpenAIProvider` was tested and returns 401/404 — they are genuinely separate. Change touches `providers.py` + `config.py` only.

**Endpoint shape — the non-obvious part (found empirically):** the config's `endpoint` is a Foundry *project* URL (`.../api/projects/<project>`), but chat/completions is **not** served there. The working route is `{host-root}/models` — the provider strips everything from `/api/` onward and appends `/models`. Every other combination tried (project path, project path + `/models`, bare root) returned 404. Verified live against both grok-4.3 and Kimi-K2.6.

**`api_version` is omitted deliberately:** every explicit version we tried (2024-05-01-preview through 2025-06-01, plus "1", "2026-04-20") returned `400 API version not supported`; the SDK's built-in default is the one the endpoint accepts. So the provider passes no `api_version`.

**aiohttp session leak (fixed):** the async `ChatCompletionsClient` holds its own aiohttp session; constructing it once per provider and never closing it produced "Unclosed client session" errors every request. Fixed by constructing the client per call inside `async with`, guaranteeing cleanup. (The OpenAI/Anthropic clients manage this internally; this SDK does not.) This is why `aiohttp` is a direct dependency now.

**Kimi token note:** Kimi burns completion tokens on internal reasoning before emitting content; with a low `max_tokens` (e.g. 48) it returned an empty `content`. The default 2048 is comfortable; no per-model special-casing needed at current limits.

**Grok routing:** the pool previously had a `grok` entry via xAI-direct (`XAI_API_KEY`, `api.x.ai`). That branch is removed — Grok now comes through Azure Foundry. The `x-xai-model-address` response header confirms Azure proxies to xAI's backend.

**Overturned if:** Foundry exposes an OpenAI-compatible `/v1` route that lets `OpenAIProvider` reach these models (then the extra SDK is droppable), or a future SDK version changes the endpoint/version handling. If Grok needs to go back to xAI-direct (cost, latency, feature access), the old branch is a config edit to restore.

---

## D-021 — Per-provider proposer token budgets

**Date:** 2026-07-10
**Status:** Accepted

`Provider` gains a `proposer_max_tokens` attribute (default 2048). `config.PROPOSER_TOKEN_BUDGETS` sets it per model at construction; `_call_one` passes `provider.proposer_max_tokens` on proposer calls. Synthesizer calls are untouched (explicit 4096) — the final answer is never shortened by this. Current budgets: `grok=1024`, `claude=1024`, `kimi=4096`, others default.

**Why per-model, not a uniform cap:** measurement showed the models need *opposite* treatments.
- **grok** generates at ~30 tok/s roughly constantly, so its token budget is a direct latency dial: 300 tok ≈ 12s, 1024 ≈ 15-18s, uncapped ≈ 27-36s. Capping it is the right lever (adaptive fanout alone just kept cancelling it).
- **claude** is verbose but honors caps: measured 43s uncapped → ~22-24s at 1024.
- **kimi** is a *reasoning* model: it burns completion tokens on hidden thinking before emitting content (`finish_reason=TOKEN_LIMIT_REACHED` with `content=0` at caps ≤512, flaky at 1024). A low budget doesn't shorten its answer — it **deletes** it. Kimi generates fast (~90 tok/s) so it doesn't need a latency cap; it needs headroom, hence 4096. Tradeoff accepted: when Kimi thinks long it can still miss the fanout grace window and get cancelled — but it can no longer inject empty candidates.

**Correction to the record:** an earlier session conclusion that "grok ignores `max_tokens` on Foundry" was **wrong** — a chars-vs-tokens confusion. Turkish costs Grok's tokenizer ~4 chars/token, so cap=1024 producing ~4000 chars was the cap being *honored exactly* (verified: cap=300 → `completion_tokens=300`, `TOKEN_LIMIT_REACHED`). Also verified that `max_completion_tokens` via `model_extras` behaves identically to `max_tokens` on Foundry — no magic parameter; both are enforced.

**Invariant check (NFR-3, pipeline vendor-blindness):** the pipeline reads an attribute off the `Provider` abstraction; it never learns which model wants which budget or why. All per-model knowledge lives in `config.py`, where model choices already live. Adding a model still touches config only.

**Verified live:** claude 24.0s (from 43s), grok 18.2s and won a round (previously near-always cancelled), no empty candidates.

**Overturned if:** Foundry generation speeds change materially, Kimi exposes a reasoning-budget/effort control (then cap its thinking instead of raising its budget), or evaluation shows 1024-token drafts degrade final-answer quality versus full drafts. Budgets are config data — retuning is not a design change.

---

## D-022 — Synthesis gets its own, larger timeout (120s)

**Date:** 2026-07-10
**Status:** Accepted

`synthesize()` now uses `SYNTH_TIMEOUT_S = 120` instead of the shared `TIMEOUT_S = 60`. Proposer and judge timeouts are unchanged.

**Triggering incident (live, via the UI):** a long structured prompt (8 mandated sections) produced: a final answer cut off mid-sentence, R-1 flag `100% similar — selection not synthesis`, ~2-minute wall clock, and only 2 candidates. The log showed the full chain: claude's draft was truncated at its 1024-token budget (D-021) and took 42.5s (~24 tok/s that day); the judge picked the truncated draft; claude-as-synthesizer then needed ~80-100s to regenerate the full answer and was killed by the 60s timeout (`sentezleyici (claude) başarısız ()` — the empty message is `asyncio.TimeoutError`'s signature); the fallback served the truncated 1024-token draft verbatim. Every user-visible symptom traced to this one chain. Notably, the R-1 instrumentation (D-018) and the fallback logging (D-012) are what made the chain reconstructable — the observability investment paid for itself.

**Why synthesis deserves a bigger budget than proposers:** by the time synthesis runs, every draft and the judge verdict are already paid for. A proposer that times out costs one candidate (fail-open absorbs it); a synthesis that times out throws away the *entire request's* value and serves the winner's raw draft — which, under D-021 budgets, may itself be truncated. Killing the most valuable call at second 60 to "save time," then delivering damaged goods after ~115s anyway, is strictly worse than waiting up to 60 more seconds for the real answer. The two timeouts protect different things: `TIMEOUT_S` bounds fan-out stragglers (cheap, redundant), `SYNTH_TIMEOUT_S` bounds the one irreplaceable call.

**Known residual risks (accepted, diagnosis-only per stakeholder):** claude's 1024 draft budget still truncates long-form drafts (misleading the judge and poisoning the fallback path on the now-rarer occasions it fires); gemini's re-enabled key is still quota-dead and 429s every request until the daily reset. Both were offered as fixes and deliberately deferred.

**Overturned if:** slow-generator synthesizers routinely exceed even 120s (then the fix is a fixed fast synthesizer — the D-002 experiment — not a bigger timeout), or streaming synthesis ships (timeout semantics change entirely).

---

## D-023 — UI de-anonymizes rationales and exposes candidate drafts; prompts stay anonymous

**Date:** 2026-07-10
**Status:** Accepted

Two display-layer features: (1) the judge rationale and synthesis reasoning shown in the UI have their anonymous labels (A, B, …) replaced with real model names; (2) a toggle inside the `details` expander reveals every candidate draft that survived fan-out — the actual texts the judge and synthesizer worked from — as one tab per model, winner marked.

**The invariant is untouched, and the boundary is precise:** the judge and synthesizer still see only anonymous labels in their prompts — `label_map` still never reaches a prompt (CLAUDE.md #4, D-003). What changed is that `FinalAnswer` now carries a `labels: dict[str, str]` (label → model_id) so the *display layer* can translate after the verdict. Identity was always resolved post-verdict in the orchestrator (that's how winner routing works); this only forwards the mapping one layer further, to the user. Anonymity is a property of what *models* see, not of what *users* see.

**Substitution mechanics:** a word-boundary regex over only the labels actually in play. Verified against real rationale samples from live runs: Turkish apostrophe suffixes (`B'nin` → `grok'nin`), bare pairs (`A ve B`), parenthesized (`(B)`), English (`Answer B provides`), and the critical non-matches — `AI` is never touched, unused labels are never touched. Known accepted cosmetic edge: an English article "A" at the start of a noun phrase can rarely false-match; harmless and documented in the helper. Turkish suffix agreement can go slightly off (`grok'nin` vs `grok'un`) — readable, not worth morphology handling.

**Why drafts-behind-a-toggle, not always visible:** the drafts are raw material (possibly truncated by D-021 budgets — the caption says so) and would dwarf the final answer if always rendered. Streamlit forbids nested expanders, so the reveal is a keyed `st.toggle` + `st.tabs` inside the existing `details` expander. Widget keys are per-turn — without them the second question crashes with `DuplicateWidgetID`.

**Overturned if:** users are confused by de-anonymized rationales that praise "grok" while the judge never knew it was grok (then show a legend `A = grok` instead of in-text replacement), or draft texts need redaction in a multi-user deployment.

---

## D-025 — Distinctive synthesis delimiter + tolerant splitter

**Date:** 2026-07-10
**Status:** Accepted

Two changes to the synthesis reasoning/answer split (D-019): the delimiter is now `<<<FINAL_ANSWER>>>` (was `===ANSWER===`), and `_split_synthesis` gained a fallback for when the model omits the delimiter entirely.

**Triggering bug (seen live):** the hero answer displayed the synthesizer's *reasoning* — "1. I leaned primarily on Candidate A… I merged in B's emphasis… Conflicts were resolved by adopting A's logic…" — followed by `=== AI Program Review: … ===` and the real answer. Root cause: the model never emitted `===ANSWER===`; it wrote its own markdown-style `=== <title> ===` heading instead. The old delimiter *looks like a markdown heading*, which invited exactly this drift. With no delimiter match, `_split_synthesis` fell to its "whole text is the answer" branch and leaked the reasoning into the user-facing output.

**Fix 1 — delimiter (reduce failure rate):** `<<<FINAL_ANSWER>>>` doesn't resemble markdown, so the model is less likely to improvise over it. But no prompt/delimiter is 100% obeyed, so:

**Fix 2 — tolerant splitter (the actual safety net):** three-tier priority — (1) exact delimiter; (2) if absent, split at the first standalone `=== … ===` heading line in the first ~1200 chars, treating the text before it as reasoning; (3) else the whole text is the answer (unchanged safe default). Tier 2 fires **only if** the extracted reasoning actually looks like reasoning (contains a candidate reference: `A`–`D`, "candidate", or "aday") — otherwise a real answer that merely contains a `=== Summary ===` heading is left whole. Unit-tested: the screenshot case now peels the reasoning off; a heading-containing answer with no candidate-reference is not mis-split; happy path and plain text both correct.

**NFR-6 intact:** only the reasoning is stripped for display; the answer (including its own `=== heading ===`, which is real content) is never cut.

**Overturned if:** models still drift past `<<<FINAL_ANSWER>>>` frequently (then structured/tool output for the two parts, not a sentinel), or the heading-fallback proves too eager on some language's answer structure (tighten the candidate-reference guard).

---

## D-026 — Synthesis rationale forced to past-tense retrospective

**Date:** 2026-07-10
**Status:** Accepted

The synthesizer prompt now demands the rationale be written in **past tense, describing an already-performed merge**, with a good example (`"I took A's phased rollout and B's job-security policy, and dropped C's vague metrics"`) and explicit bans on the preamble/summary forms (`"I will synthesize these candidates…"`, `"These three answers all emphasize…"`).

**Not a regression — per-model variance made visible (R-5, D-002).** A user noticed the rationale had changed from concrete "I took X from A, Y from B" (earlier runs) to a vague future-tense preamble "I will synthesize these three… I'll combine their strongest elements." Investigation: the prompt wording was unchanged (D-025 only swapped the delimiter string). The difference was **which model won and thus synthesized** — earlier good rationales came from kimi/gemini synthesizers; the preamble came from a claude-won round. The old prompt asked for the rationale *first* (before the answer exists) with soft past-tense verbs ("merged/dropped"); models that read it literally can't describe a merge not yet done, so some default to announcing intent. This is exactly R-5 ("synthesizer changes per request, so tone and style vary") surfacing in the rationale field.

**Why reword, not reorder:** reordering (answer first, then rationale) would guarantee past-tense structurally but flips which side of the delimiter is the answer — more moving parts in the just-hardened splitter (D-025). The reword is contained to the prompt. Verified live: the *same* claude synthesizer that produced the preamble now writes "I combined A's phased rollout strategy … with B's trust-building mechanisms … then added pulse surveys from B to complement A's time-saved metrics" — concrete, past-tense, per-candidate, zero preamble markers.

**Overturned if:** a model still preambles despite the explicit example+ban (then reorder to answer-first, D-002-style), or the added prompt length measurably crowds out answer quality on tight token budgets.

---

## D-027 — Per-provider synthesis token budgets; app.py logging restored

**Date:** 2026-07-10
**Status:** Accepted

`Provider` gains `synth_max_tokens` (default 4096, the previous hardcoded value); `synthesize()` reads it off the winning provider. `config.SYNTH_TOKEN_BUDGETS` currently sets only `kimi: 12000`.

**Triggering bug (live, via UI):** a long structured answer synthesized by kimi cut off mid-table-row. No synthesis-failure warning in the log → synthesis *completed*; the answer was **token-truncated**. Probe confirmed the mechanism: on a synthesis-like task, kimi at cap 4096 → `TOKEN_LIMIT_REACHED` (truncated); at cap 12000 → `STOPPED`, natural finish at 9,061 tokens. This is D-021's lesson (reasoning models burn budget on hidden thinking; a tight cap deletes visible content) recurring at the *synthesis* stage, which D-021 never touched — the flat 4096 was latent until kimi won a long-form question.

**Why grok deliberately stays at 4096:** at ~30 tok/s, a 12k budget implies ~400s of generation — far past `SYNTH_TIMEOUT_S` (120s). Raising grok's budget would convert "occasionally shorter answer" into "timeout → fallback serves a draft," strictly worse. Budget and timeout must be sized together per model's generation rate.

**Known residual:** kimi at 12k tokens ≈ ~100-130s worst case, brushing the 120s synthesis timeout; if kimi-timeouts appear in logs, the pair (budget, timeout) needs joint retuning. Also, truncation is still *invisible* to the pipeline — the `Provider` interface returns a bare string with no `finish_reason`; surfacing truncation as a flag would need an interface change (deferred).

**Second fix bundled here:** `app.py` never called `logging.basicConfig`, so the pipeline's structured INFO line (M3: winner, latencies, R-1 similarity) was **silently discarded in Streamlit mode** — discovered when the diagnostic grep of the UI log came back empty. `app.py` now mirrors `main.py`'s logging setup (INFO + azure/httpx quieted). UI runs are observable again.

**Overturned if:** kimi synthesis timeouts appear (retune budget/timeout jointly, or fixed-fast-synthesizer per D-002's experiment), or the `Provider` interface grows structured responses (then use `finish_reason` to detect and surface truncation instead of over-budgeting).
