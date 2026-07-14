"""Streamlit sohbet arayüzü — pipeline'ın üzerinde ince bir katman.

Bağımlılık yönü (CLAUDE.md #1): app.py → core.pipeline. core/ buradan
hiçbir şey import etmez. Bu, main.py ile paralel, yeni bir üst yüzeydir.

Kapsam notu (PRD §3): sohbet YALNIZCA görsel bir döküm. Her soru bağımsız,
durumsuz bir pipeline çağrısıdır — önceki turlar modellere beslenmez. Böylece
"çok turlu diyalog yok" kuralı çekirdek katmanda korunur.
"""

import asyncio
import hmac
import logging
import os
import re

import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # .env'i core import edilmeden önce os.environ'a yükle

# NOT: `core.pipeline` BİLEREK burada import edilmiyor. Demo giriş kapısı
# (require_demo_login) kimlik doğrulamadan ÖNCE hiçbir sağlayıcı/model kodunun
# yüklenmemesini şart koşuyor; ağır import _run_pipeline içine ertelendi.
from ui.theme import CSS  # noqa: E402 — load_dotenv sıralaması kasıtlı

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


# --- Demo giriş kapısı ---
#
# Bu, üretim kimlik doğrulaması DEĞİL — Streamlit Community Cloud'da herkese
# açık bir URL'nin arkasındaki demoyu, rastgele ziyaretçilerin API kredisi
# harcamasına karşı korumak içindir. Tek paylaşılan parola yeter.
#
# Streamlit Community Cloud gizli anahtarları (App → Settings → Secrets) TOML
# formatındadır. Aşağıdaki gibi yapılandırın (BU DEĞERLERİ REPO'YA COMMIT'LEMEYİN):
#
#     APP_PASSWORD = "your-demo-password"
#     OPENAI_API_KEY = "..."
#     ANTHROPIC_API_KEY = "..."
#     GEMINI_API_KEY = "..."
#     PERPLEXITY_RESPONSES_API_KEY = "..."   # opsiyonel: "Perplexity Sonar" proposer'ı (/v1/responses)
#     PERPLEXITY_SEARCH_API_KEY = "..."      # opsiyonel: web-kanıt arama katmanı (/search) — AYRI anahtar
#     # diğer sağlayıcı gizli anahtarları (Azure/Grok/Kimi vb.)...
#
# Streamlit gizli anahtarları os.environ'a da yansıtır, dolayısıyla core.config'in
# mevcut _has_key(...) mantığı bulut ortamında değişiklik gerektirmeden çalışır.
def require_demo_login() -> None:
    """Ana uygulamadan önce basit bir parola kapısı uygula.

    Kimlik doğrulanmışsa hemen döner ve uygulama normal şekilde render edilir.
    Değilse SADECE giriş ekranını çizer ve st.stop() ile scripti durdurur — bu
    noktadan sonra hiçbir model/sağlayıcı init'i, pipeline çağrısı ya da API
    isteği çalışmaz (ağır core.pipeline import'u da _run_pipeline içinde erteli).
    """
    if st.session_state.get("authenticated"):
        return

    # Giriş ekranı — mevcut koyu, minimal, teknik stille aynı dil.
    st.markdown(
        '<div class="app-title">◇ Multi-Model Synthesizer</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="app-sub">Private demo access</div>',
        unsafe_allow_html=True,
    )

    with st.form("demo_login", clear_on_submit=False):
        password = st.text_input(
            "Password", type="password", label_visibility="collapsed",
            placeholder="Password",
        )
        submitted = st.form_submit_button("Enter demo")

    if submitted:
        # APP_PASSWORD gizli anahtarı yoksa: yanlış parola gibi davran, hangi
        # kısmın eksik olduğunu SIZDIRMA. hmac.compare_digest sabit-zamanlı.
        expected = st.secrets.get("APP_PASSWORD", "")
        if expected and hmac.compare_digest(str(password), str(expected)):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            # Parolanın neresinin yanlış olduğunu gösterme; girilen parolayı
            # loglama/ekrana yazma. Sadece nazik, düşük vurgulu bir uyarı.
            st.markdown(
                '<div class="r1-flag r1-warn">Incorrect password.</div>',
                unsafe_allow_html=True,
            )

    # Giriş ekranı çizildi — script'i BURADA durdur. Auth geçene dek uygulamanın
    # geri kalanı (model init, pipeline, chat UI) hiç çalışmaz.
    st.stop()


# Streamlit Community Cloud'da iç içe (tablo) gizli anahtarların os.environ'a
# yansıtılması. core/ Streamlit'ten habersizdir ve config.json/config.grok.json/
# config.kimi.json dosyalarını bulutta bulamaz (gizli anahtarlar diske yazılmaz).
# Bu köprü, TOML tablolarını core.config'in beklediği düz env adlarına açar:
#
#   [azure_judge]  api_key/api_version/azure_endpoint/deployment_name
#       -> AZURE_JUDGE_API_KEY / _API_VERSION / _AZURE_ENDPOINT / _DEPLOYMENT_NAME
#   [foundry_grok] endpoint/api_key_env/model
#       -> FOUNDRY_GROK_ENDPOINT / _API_KEY_ENV / _MODEL
#   [foundry_kimi] endpoint/api_key_env/model
#       -> FOUNDRY_KIMI_ENDPOINT / _API_KEY_ENV / _MODEL
#
# Düz anahtarlar (OPENAI_API_KEY vb.) zaten Streamlit tarafından os.environ'a
# yansıtılır — onlara dokunmuyoruz. Yerel geliştirmede tablolar yoksa bu no-op'tur
# ve core, dosyaları okumaya devam eder.
_SECRET_TABLES = ("azure_judge", "foundry_grok", "foundry_kimi")


def _bridge_secrets_to_env() -> None:
    """İç içe st.secrets tablolarını {TABLO}_{ALAN} env adlarına aç (varsa)."""
    for table in _SECRET_TABLES:
        section = st.secrets.get(table)
        if not section:
            continue
        for field, value in section.items():
            # Mevcut env değerini EZME: yerelde .env/dosya öncelikli kalsın.
            env_name = f"{table.upper()}_{field.upper()}"
            os.environ.setdefault(env_name, str(value))


# Kimlik doğrulama kapısı: HER ŞEYDEN önce. Bundan sonrasına yalnızca
# doğrulanmış kullanıcı ulaşır — sağlayıcı/model init, config yükleme, pipeline
# ve chat UI dahil.
require_demo_login()

# Auth GEÇTİKTEN sonra, pipeline import edilmeden önce: bulut gizli anahtarlarını
# core'un göreceği env adlarına köprüle. Auth öncesi hiçbir sağlayıcı sırrı
# ortama sızmaz (kapı st.stop() ile burayı çalıştırmaz).
_bridge_secrets_to_env()


def _logout() -> None:
    """Oturumu kapat: auth bayrağını temizle ve scripti yeniden çalıştır."""
    st.session_state.pop("authenticated", None)
    st.rerun()


def _run_pipeline(question: str, on_stage=None):
    """Async pipeline'ı senkron Streamlit thread'inden çağır.

    Her çağrı için taze bir event loop — paylaşılan durum yok, temiz.
    Kritik detay (D-028): asyncio.run event loop'u BU thread'de çalıştırır,
    yani on_stage callback'i Streamlit script thread'inde koşar ve st.*
    elemanlarını güvenle güncelleyebilir — thread/queue makinesine gerek yok.

    `run` import'u BİLEREK burada, fonksiyon içinde: core.pipeline (ve zincirdeki
    provider/config kodu) yalnızca kimlik doğrulama geçtikten ve gerçek bir soru
    geldikten sonra yüklenir. Demo giriş kapısının "önce hiçbir model kodu" şartı.
    """
    from core.pipeline import run  # noqa: PLC0415 — auth öncesi yükleme yapılmasın diye erteli

    return asyncio.run(run(question, on_stage=on_stage))


# Aşama -> kullanıcıya gösterilen satır (D-028). Zengin yük gerçek veridir:
# model sayısı, hayatta kalan aday sayısı, kazananın adı. Kazananın sentez
# sırasında görünmesi kasıtlı — en uzun bekleyiş en ilginç hale gelir.
_STAGE_LABELS = {
    "querying": "querying {models} models…",
    "judging": "judging {candidates} candidates…",
    "synthesizing": "{winner} won — synthesizing…",
}


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
    # Arama kanıtı kullanıldıysa küçük, düşük vurgulu bir "web evidence used"
    # rozeti eklenir (req #9) — UI'ı kalabalıklaştırmadan; ham sonuç gösterilmez.
    evidence_badge = ""
    if getattr(result, "evidence_used", False):
        evidence_badge = (
            '<span class="meta-dot">·</span>'
            '<span class="web-evidence">web evidence used</span>'
        )
    st.markdown(
        f'<div class="meta-line">via <span class="win">{winner}</span>'
        f'<span class="meta-dot">·</span>{win_ms/1000:.1f}s'
        f'<span class="meta-dot">·</span>{len(result.candidates)} models'
        f'{evidence_badge}</div>',
        unsafe_allow_html=True,
    )

    # İç organlar: adaylar, judge gerekçesi, sentez gerekçesi, R-1 sinyali.
    # Gerekçelerdeki anonim etiketler (A/B/...) kullanıcıya model adı olarak
    # gösterilir (D-023) — modeller etiket gördü, kullanıcı isim görür.
    labels = getattr(result, "labels", {}) or {}

    # st.expander DURUMSUZDUR (D-029): içindeki bir widget'a (drafts toggle)
    # dokunmak script'i yeniden çalıştırır ve expander sessizce KAPANIR — bu da
    # "details'e hiç tıklamamışım gibi" hatasını yaratır. Expander'ın açık/kapalı
    # durumunu kendimiz session_state'te tutup expanded=... ile besliyoruz.
    # key tur başına kararlıdır (canlı render ve loop aynı değeri verir, teyit
    # edildi), o yüzden güvenli. Toggle'ın on_change'i bu bayrağı True yapar:
    # expander'ı kapatan etkileşim, artık onu açık TUTAN etkileşim olur.
    open_key = f"details_open_{key}"
    st.session_state.setdefault(open_key, False)
    with st.expander("details", expanded=st.session_state[open_key]):
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
        # on_change (D-029): toggle'a dokununca, rerun expander'ı yeniden
        # boyamadan ÖNCE açık-bayrağını pinle. Böylece details kapanmaz.
        if st.toggle("show the answers behind the synthesis",
                     key=f"drafts-{key}",
                     on_change=lambda k=open_key: st.session_state.__setitem__(k, True)):
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
    '<div class="app-sub">Five models answer. A blind judge picks the strongest. '
    'The winner <span class="accent">synthesizes all five</span> into one.</div>',
    unsafe_allow_html=True,
)

# Küçük çıkış düğmesi (demo). Sağa yaslı, sessiz — layout'u bozmadan.
_, _logout_col = st.columns([6, 1])
with _logout_col:
    st.button("Log out", on_click=_logout, use_container_width=True)

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
        # Canlı aşama satırı (D-028): statik spinner yerine, pipeline'ın
        # gerçekte hangi aşamada olduğunu gösteren tek satır. Callback aynı
        # thread'de koştuğu için st.empty() içeriğini doğrudan güncelleyebilir.
        stage_box = st.empty()
        stage_box.markdown(
            '<div class="stage-line"><span class="stage-spin">⟳</span> starting…</div>',
            unsafe_allow_html=True,
        )

        def _on_stage(stage: str, info: dict) -> None:
            label = _STAGE_LABELS.get(stage, stage).format(**info)
            stage_box.markdown(
                f'<div class="stage-line"><span class="stage-spin">⟳</span> {label}</div>',
                unsafe_allow_html=True,
            )

        try:
            result = _run_pipeline(question, _on_stage)
        except Exception as exc:
            msg = f"Pipeline failed: {exc}"
            st.error(msg)
            st.session_state.turns.append({"q": question, "result": None, "error": msg})
        else:
            _render_answer(result, key=str(len(st.session_state.turns)))
            st.session_state.turns.append({"q": question, "result": result, "error": None})
        finally:
            # Hata dahil her yolda aşama satırı temizlenir — öksüz spinner yok.
            stage_box.empty()
