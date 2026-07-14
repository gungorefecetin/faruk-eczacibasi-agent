"""Arama (search) kanıt katmanı — heuristik + biçimlendirme (vendor-neutral).

Bu modül SAĞLAYICI BİLMEZ (CLAUDE.md #2): saf string fonksiyonları. Perplexity
Search istemcisi core/providers.py'de; onu KURMAK config.build_search()'ün işi;
onu ÇAĞIRMAK pipeline'ın işi. Burada yalnızca "arama gerekli mi?" kararı ve ham
sonuçları bir <search_evidence> bloğuna dönüştürme mantığı yaşar.

Kanıt bir ADAY DEĞİLDİR (kullanıcı isteği #2): yalnızca proposer girdisini
zenginleştirir ve sentez promptuna bağlam olarak eklenebilir. Judge onu aday
olarak görmez; Search istemcisi asla judge/synthesizer olamaz.
"""

import re

# Arama tetikleyici anahtar kelimeler (req #3). Türkçe + İngilizce; güncel/taze/
# web-grounded bilgi imleyen terimler. Kelime-sınırıyla eşleşir ki "prices" gibi
# türevler de yakalansın ama "recentralize" içindeki "recent" yanlış tetiklemesin.
# Not: "2025"/"2026" gibi yıllar ve çok kelimeli Türkçe ifadeler ("yeni çıkan",
# "API docs") ayrı ele alınır.
_TRIGGER_WORDS = {
    # İngilizce
    "latest", "current", "today", "recent", "news", "price", "prices",
    "benchmark", "benchmarks", "release", "released", "documentation", "docs",
    # Türkçe
    "güncel", "son", "bugün", "haber", "fiyat", "dokümantasyon", "sürüm",
}

# Çok kelimeli / özel kalıplar: basit kelime kümesiyle yakalanamayanlar.
_TRIGGER_PHRASES = (
    "api docs",
    "yeni çıkan",
)

# Yıl imleyicileri: güncel bilgi sorularının güçlü sinyali (req #3).
_YEAR_RE = re.compile(r"\b(202[5-9])\b")

# Kelimelere ayırma: Unicode harf/rakam dizileri. Türkçe karakterleri (ı, ş, ğ,
# ç, ö, ü ve büyükleri) KORUR — \w bunları zaten kapsar. NFD normalizasyonu YOK
# (invariant #5): sadece küçük harfe çeviriyoruz, casefold Türkçe 'İ'->'i̇' gibi
# sürprizler yapabildiği için düz lower() yeterli ve güvenli.
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def should_use_search(question: str) -> bool:
    """Soru taze/güncel/web-grounded bilgi gerektiriyor mu? (req #3)

    True: tetikleyici terim, çok kelimeli kalıp veya 2025+ yıl içerenler.
    False: selamlaşma, saf kavramsal/kodlama açıklamaları, basit promptlar —
    bunlar tetikleyici içermez, dolayısıyla doğal olarak False döner.

    Muhafazakâr yanlış-pozitif duruşu: arama fail-open, yani gereksiz tetikleme
    en fazla küçük bir gecikme + atlanabilir kanıttır; kaçırılan tetikleme ise
    modelleri güncel veriden yoksun bırakır. Yine de gürültüyü düşük tutmak için
    yalnızca net sinyallerde tetikliyoruz.
    """
    if not question or not question.strip():
        return False
    low = question.lower()

    # Çok kelimeli kalıplar (kelimeye ayırmadan önce, boşluk içerdikleri için).
    for phrase in _TRIGGER_PHRASES:
        if phrase in low:
            return True

    # Yıl sinyali.
    if _YEAR_RE.search(question):
        return True

    # Tek kelimelik tetikleyiciler (kelime-sınırı: türevler token olarak eşleşir).
    tokens = set(_WORD_RE.findall(low))
    return bool(tokens & _TRIGGER_WORDS)


def format_evidence(results: list[dict]) -> str:
    """Ham arama sonuçlarını <search_evidence> bloğuna biçimlendir (req #4).

    Boş/sonuçsuz liste -> boş string (çağıran taraf hiç kanıt eklememeli).
    Her sonuç: Title / URL / Snippet. Kanıtın DİLİ zenginleştirmede kullanılır
    ama nihai cevabın dilini ASLA belirlemez — bu kural proposer/synth
    promptlarında açıkça yazılıdır (invariant #6, req #5).
    """
    if not results:
        return ""
    blocks: list[str] = []
    for i, r in enumerate(results, start=1):
        lines = [f"Result {i}:"]
        if r.get("title"):
            lines.append(f"Title: {r['title']}")
        if r.get("url"):
            lines.append(f"URL: {r['url']}")
        if r.get("snippet"):
            lines.append(f"Snippet: {r['snippet']}")
        blocks.append("\n".join(lines))
    inner = "\n\n".join(blocks)
    return f"<search_evidence>\n{inner}\n</search_evidence>"


# Proposer/synth girdisine kanıt eklerken kullanılan yönerge metni (req #4).
# İngilizce (invariant #6: promptlar İngilizce, cevap sorunun dilinde).
EVIDENCE_INSTRUCTIONS = (
    "Use the search evidence only if relevant. "
    "Do not invent facts beyond the evidence. "
    "If the evidence is insufficient or conflicting, say so. "
    "The search evidence is background context only; it does NOT change the "
    "required answer language, which follows the original user question."
)


def augment_question(question: str, evidence_block: str) -> str:
    """Orijinal soruyu kanıt bloğuyla sararak proposer girdisi üret (req #4, #5).

    Orijinal soru <original_user_question> içinde AYNEN korunur (dil tespiti /
    dil kuralı / UI için). Kanıt bloğu ayrı bir bölümde; wrapper dili nihai
    cevabın dilini geçersiz kılmasın diye yönerge açıkça bunu söyler.

    evidence_block boşsa soruyu OLDUĞU GİBİ döndür — sarmalama yok, davranış
    aramasız yolla birebir aynı (minimal değişiklik).
    """
    if not evidence_block:
        return question
    return (
        "<original_user_question>\n"
        f"{question}\n"
        "</original_user_question>\n\n"
        f"{evidence_block}\n\n"
        f"{EVIDENCE_INSTRUCTIONS}"
    )
