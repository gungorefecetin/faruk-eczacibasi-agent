"""Görsel katman. app.py'nin davranışından ayrı tutulur.

core/ buradan hiçbir şey import etmez — bağımlılık yönü tek yönlü kalır
(CLAUDE.md #1). Bu modül yalnızca app.py tarafından kullanılır.
"""

# Tek vurgu rengi, editoryal bir palet. Klasik "AI mor gradyanı" bilinçli
# olarak kullanılmadı — sakin, koyu, enstrüman-göstergesi hissi.
ACCENT = "#7dd3c0"          # yumuşak teal — tek vurgu
INK = "#e8e8e6"             # ana metin
MUTED = "#8a8a85"           # ikincil metin, caption'lar
SURFACE = "#141414"         # panel yüzeyi
BG = "#0d0d0d"              # arka plan

CSS = f"""
<style>
/* --- Streamlit chrome'unu sadeleştir --- */
#MainMenu, header, footer {{ visibility: hidden; }}
.stApp {{ background: {BG}; }}
.block-container {{ max-width: 780px; padding-top: 3.5rem; padding-bottom: 8rem; }}

/* --- Tipografi --- */
html, body, [class*="css"] {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
    color: {INK};
}}

/* Başlık: küçük, letter-spacing'li, iddiasız */
.app-title {{
    font-size: 0.82rem;
    font-weight: 600;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: {MUTED};
    margin-bottom: 0.15rem;
}}
.app-sub {{
    font-size: 0.9rem;
    color: {MUTED};
    margin-bottom: 2.5rem;
    line-height: 1.5;
}}
.app-sub .accent {{ color: {ACCENT}; }}

/* --- Sohbet balonları --- */
[data-testid="stChatMessage"] {{
    background: transparent;
    border: none;
    padding: 0.2rem 0;
}}
/* Kullanıcı mesajı: sağ hizalı, hafif yüzeyli kutu */
.user-bubble {{
    background: {SURFACE};
    border: 1px solid #222;
    border-radius: 14px 14px 4px 14px;
    padding: 0.7rem 1rem;
    display: inline-block;
    max-width: 80%;
    line-height: 1.55;
}}
/* Cevap: kutu yok, metnin kendisi kahraman */
.answer-body {{
    line-height: 1.7;
    font-size: 1.02rem;
}}
.answer-body p {{ margin-bottom: 0.9rem; }}

/* --- Meta caption: sessiz, monospace, enstrüman göstergesi --- */
.meta-line {{
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 0.74rem;
    color: {MUTED};
    margin-top: 0.6rem;
    letter-spacing: 0.02em;
}}
.meta-line .win {{ color: {ACCENT}; font-weight: 600; }}
.meta-dot {{ color: #333; margin: 0 0.5rem; }}

/* --- Details expander: iç organları saklı ama erişilebilir --- */
[data-testid="stExpander"] {{
    border: none;
    background: transparent;
}}
[data-testid="stExpander"] summary {{
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 0.72rem;
    color: {MUTED};
    padding: 0.3rem 0;
}}
[data-testid="stExpander"] summary:hover {{ color: {ACCENT}; }}

.cand-row {{
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 0.76rem;
    color: {MUTED};
    padding: 0.25rem 0;
    border-bottom: 1px solid #1c1c1c;
    display: flex;
    justify-content: space-between;
}}
.cand-row.winner {{ color: {ACCENT}; }}
.cand-name {{ font-weight: 600; }}
/* Havuz slot adı (chatgpt) — gerçek model adının yanında küçük, soluk etiket */
.cand-slot {{
    font-weight: 400;
    color: #55554f;
    font-size: 0.82em;
    margin-left: 0.5rem;
}}
.judge-reason {{
    font-size: 0.85rem;
    color: {INK};
    font-style: italic;
    border-left: 2px solid {ACCENT};
    padding-left: 0.9rem;
    margin: 0.7rem 0;
    line-height: 1.5;
}}
/* Bölüm etiketi: küçük, letter-spacing'li, sessiz başlık */
.section-label {{
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 0.68rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: {MUTED};
    margin: 1rem 0 0.35rem 0;
}}
/* Sentez gerekçesi: judge'dan ayrı, düz (italik değil) — bir düşünce, alıntı değil */
.synth-reason {{
    font-size: 0.85rem;
    color: {INK};
    border-left: 2px solid {MUTED};
    padding-left: 0.9rem;
    margin: 0.3rem 0 0.7rem 0;
    line-height: 1.55;
}}
/* Gerekçe metni içinde etiket yerine geçen model adı (D-023): düzyazıdan
   ayrışsın diye monospace + vurgu rengi — "enstrüman verisi" hissi */
.model-ref {{
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 0.8em;
    color: {ACCENT};
    font-weight: 600;
}}
.r1-flag {{
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 0.72rem;
    margin-top: 0.5rem;
}}
.r1-ok {{ color: {ACCENT}; }}
.r1-warn {{ color: #e0a35c; }}

/* --- Girdi kutusu --- */
[data-testid="stChatInput"] {{
    background: {BG};
}}
[data-testid="stChatInput"] textarea {{
    background: {SURFACE};
    border: 1px solid #2a2a2a;
    color: {INK};
}}
[data-testid="stChatInput"] textarea:focus {{
    border-color: {ACCENT};
    box-shadow: none;
}}
</style>
"""
