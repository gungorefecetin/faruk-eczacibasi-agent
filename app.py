"""Streamlit sohbet arayüzü — pipeline'ın üzerinde ince bir katman.

Bağımlılık yönü (CLAUDE.md #1): app.py → core.pipeline. core/ buradan
hiçbir şey import etmez. Bu, main.py ile paralel, yeni bir üst yüzeydir.

Kapsam notu (PRD §3): sohbet YALNIZCA görsel bir döküm. Her soru bağımsız,
durumsuz bir pipeline çağrısıdır — önceki turlar modellere beslenmez. Böylece
"çok turlu diyalog yok" kuralı çekirdek katmanda korunur.
"""

import asyncio
import logging
import re

import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # .env'i core import edilmeden önce os.environ'a yükle

from core.pipeline import run  # noqa: E402 — load_dotenv sıralaması kasıtlı
from ui.theme import CSS

# Pipeline'ın yapılandırılmış INFO logu (M3 gözlemlenebilirlik: winner,
# gecikmeler, R-1 benzerliği) basicConfig olmadan SESSİZCE kayboluyordu —
# UI modunda enstrümantasyonsuz uçuyorduk (D-027'de fark edildi).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

st.set_page_config(page_title="Synthesizer", page_icon="◇", layout="centered")
st.markdown(CSS, unsafe_allow_html=True)


def _run_pipeline(question: str):
    """Async pipeline'ı senkron Streamlit thread'inden çağır.

    Her çağrı için taze bir event loop — paylaşılan durum yok, temiz.
    """
    return asyncio.run(run(question))


def _display_names(text: str, labels: dict[str, str]) -> str:
    """Anonim etiketleri (A, B, ...) model adlarıyla değiştir — SADECE görüntü (D-023).

    Anonimlik invariant'ı burada bozulmaz: judge/sentezleyici prompt'ları etiket
    gördü; bu fonksiyon verdikten SONRA, kullanıcıya gösterim için çalışır.
    Yalnızca gerçekten kullanılan etiketleri, tek başına duran (word-boundary)
    büyük harf olarak yakalar: "Cevap B'nin", "(C)", "A ve B" ✓, "AI" ✗.
    Bilinen kozmetik kenar: İngilizce artikel "A" ("A more complete...") nadiren
    yanlış eşleşebilir — kabul edilmiş, zararsız bir takas.
    """
    if not text or not labels:
        return text
    pattern = re.compile(r"\b(" + "|".join(sorted(labels)) + r")\b")
    return pattern.sub(
        lambda m: f'<span class="model-ref">{labels[m.group(1)]}</span>', text
    )


def _render_answer(result, key: str) -> None:
    """Cevap kahraman; meta sessiz caption; iç organlar expander'da."""
    st.markdown(
        f'<div class="answer-body">{result.answer}</div>',
        unsafe_allow_html=True,
    )

    winner = result.winner_model
    win_cand = next((c for c in result.candidates if c.model_id == winner), None)
    win_ms = win_cand.latency_ms if win_cand else 0

    # Sessiz meta satırı: kazanan + gecikme. Detay istemeyene yeter.
    st.markdown(
        f'<div class="meta-line">via <span class="win">{winner}</span>'
        f'<span class="meta-dot">·</span>{win_ms/1000:.1f}s'
        f'<span class="meta-dot">·</span>{len(result.candidates)} models</div>',
        unsafe_allow_html=True,
    )

    # İç organlar: adaylar, judge gerekçesi, sentez gerekçesi, R-1 sinyali.
    # Gerekçelerdeki anonim etiketler (A/B/...) kullanıcıya model adı olarak
    # gösterilir (D-023) — modeller etiket gördü, kullanıcı isim görür.
    labels = getattr(result, "labels", {}) or {}
    with st.expander("details"):
        st.markdown('<div class="section-label">judge · why this won</div>',
                    unsafe_allow_html=True)
        st.markdown(
            f'<div class="judge-reason">{_display_names(result.judge_reason, labels)}</div>',
            unsafe_allow_html=True,
        )

        # Sentez gerekçesi: kullanıcı isterse görür. Boşsa (ayraç gelmedi ya da
        # sentez fallback'e düştü) bölümü hiç gösterme.
        if result.synthesis_reasoning:
            st.markdown('<div class="section-label">synthesis · how it was merged</div>',
                        unsafe_allow_html=True)
            st.markdown(
                f'<div class="synth-reason">{_display_names(result.synthesis_reasoning, labels)}</div>',
                unsafe_allow_html=True,
            )

        st.markdown('<div class="section-label">candidates</div>',
                    unsafe_allow_html=True)
        for c in result.candidates:
            cls = "cand-row winner" if c.model_id == winner else "cand-row"
            marker = "◆" if c.model_id == winner else "◇"
            # Gerçek model dizesi ana etiket (ör. gpt-4o); dostça havuz adı
            # küçük ikincil etiket. model_name boşsa (eski session) id'ye düş.
            name = c.model_name or c.model_id
            st.markdown(
                f'<div class="{cls}"><span class="cand-name">{marker} {name}'
                f'<span class="cand-slot">{c.model_id}</span></span>'
                f'<span>{c.latency_ms} ms</span></div>',
                unsafe_allow_html=True,
            )

        # Senteze giren TÜM aday cevaplar, istenirse (D-023). Not: expander
        # içine expander koymak Streamlit'te yasak — toggle + sekme kullanılır.
        # key zorunlu: her tur kendi widget kimliğini taşımalı, yoksa ikinci
        # soruda DuplicateWidgetID hatası.
        if st.toggle("show the answers behind the synthesis",
                     key=f"drafts-{key}"):
            tabs = st.tabs([
                f"{'◆' if c.model_id == winner else '◇'} {c.model_name or c.model_id}"
                for c in result.candidates
            ])
            for tab, c in zip(tabs, result.candidates):
                with tab:
                    st.caption(
                        f"{c.latency_ms} ms · {len(c.text)} chars · raw draft "
                        "(may be truncated by its token budget)"
                    )
                    st.markdown(c.text)

        # R-1 sinyali (PRD §8): nihai cevabın kazanan adaya benzerlik oranı.
        # Yüksek benzerlik = sentezleyici kendi cevabını cilaladı, sentez değil
        # seçim yaptı. Birebir-eşitlik yerine gerçek oran (D-018).
        sim = result.winner_similarity
        if sim >= 0.95:
            st.markdown(
                f'<div class="r1-flag r1-warn">⚠ final ≈ winning candidate '
                f'({sim:.0%} similar — likely selection, not synthesis · R-1)</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="r1-flag r1-ok">✓ final differs from winning '
                f'candidate ({sim:.0%} similar — synthesis occurred)</div>',
                unsafe_allow_html=True,
            )


# --- Başlık ---
st.markdown('<div class="app-title">◇ Multi-Model Synthesizer</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="app-sub">Four models answer. A blind judge picks the strongest. '
    'The winner <span class="accent">synthesizes all four</span> into one.</div>',
    unsafe_allow_html=True,
)

# --- Görsel transkript (yalnızca session, kalıcı değil) ---
if "turns" not in st.session_state:
    st.session_state.turns = []  # list[dict]: {"q": str, "result": FinalAnswer | None, "error": str | None}

for i, turn in enumerate(st.session_state.turns):
    with st.chat_message("user"):
        st.markdown(
            f'<div class="user-bubble">{turn["q"]}</div>', unsafe_allow_html=True
        )
    with st.chat_message("assistant", avatar="🔹"):
        if turn["error"]:
            st.error(turn["error"])
        else:
            _render_answer(turn["result"], key=str(i))

# --- Girdi ---
question = st.chat_input("Ask anything…")
if question:
    with st.chat_message("user"):
        st.markdown(f'<div class="user-bubble">{question}</div>', unsafe_allow_html=True)

    with st.chat_message("assistant", avatar="🔹"):
        try:
            with st.spinner("querying models · judging · synthesizing"):
                result = _run_pipeline(question)
            _render_answer(result, key=str(len(st.session_state.turns)))
            st.session_state.turns.append({"q": question, "result": result, "error": None})
        except Exception as exc:
            msg = f"Pipeline failed: {exc}"
            st.error(msg)
            st.session_state.turns.append({"q": question, "result": None, "error": msg})
