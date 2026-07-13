# Çok-Modelli Cevap Sentezleyici — Proje Özeti

> Bu doküman projenin ne amaçladığını, ne yaptığımızı, neyi neden seçtiğimizi ve
> hangi kritik noktaları ele aldığımızı Türkçe olarak özetler. Teknik referans
> dokümanları (`docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/DECISION-LOG.md`)
> İngilizcedir; bu dosya onların üstüne bir okuma kılavuzu değil, bağımsız bir
> anlatıdır.

---

## 1. Proje Ne Amaçlıyor?

**Temel fikir:** Tek bir dil modeline soru sormak, tek bir dağılımdan tek bir
örnek almaktır. O modelin kör noktalarını, eğitim yanlılıklarını ve hata
biçimlerini de beraberinde taşırsınız. Aynı soru dört farklı sınır (frontier)
modele sorulduğunda, modeller çoğu zaman **doğru bir çekirdek üzerinde
anlaşır, kenarlarda ayrışır** — ve bu ayrışma bir sinyal taşır.

Bugün bu sinyalden ucuza faydalanmanın bir yolu yok. Daha iyi bir cevap isteyen
kullanıcı, birden fazla modeli elle sorgulamak, tüm çıktıları okumak ve onları
zihninde birleştirmek zorunda. Bu yavaş, tutarsız ve ölçeklenmiyor.

**Amaç:** Tek bir soruyu alan, onu dört modele **paralel** soran, bir hakem
(judge) modeliyle en güçlü cevabı seçen ve **kazanan cevabı üreten modeli**
sentezleyici koltuğuna oturtarak dört adayı tek bir nihai cevaba birleştiren
bir ajan inşa etmek.

**MVP için başarı, çalışan ve gözlemlenebilir bir hattır — kanıtlanmış bir
kalite artışı değil.** Kalitenin gerçekten arttığını kanıtlamak bilinçli olarak
kapsam dışıdır ve değerlendirme aşamasına ertelenmiştir. Bu ayrım önemlidir:
sistem bir cevap ürettiğinde "bitmiş" sayılmaz; bir cevap ürettiğinde, ölü bir
sağlayıcıdan sağ çıktığında, bozuk bir hakem yanıtından sağ çıktığında **ve
sentezin gerçekten olup olmadığını söyleyecek kadar bilgi yaydığında** bitmiş
sayılır.

---

## 2. Ne Yaptık? (Bu Oturumda)

Proje bize olgun bir dokümantasyon ve temiz bir iskeletle geldi; ama birkaç
kritik açık ve bir güvenlik sorunu taşıyordu. Yaptıklarımız:

### 2.1. Güvenlik
- **`.env.example` içinde gerçek, canlı API anahtarları vardı** (OpenAI ve
  Gemini). Bu, projenin kendi kuralını (NFR-5: "hiçbir anahtar commit edilmez
  veya loglanmaz") ihlal ediyordu. Dosyayı boş placeholder'lara indirdik.
- Gerçek anahtarların gittiği bir `.env` dosyası oluşturduk ve bir `.gitignore`
  ile `.env`'in asla commit edilmemesini garantiledik.
- **Not:** Sızan iki anahtar (OpenAI, Gemini) düz metin olarak paylaşılabilir
  bir dosyada durduğu için "ele geçmiş" kabul edilmeli ve döndürülmeli
  (rotate edilmeli).

### 2.2. Düzeltilen Hatalar
- **Eksik anahtar çökmesi:** Bir sağlayıcının anahtarı yoksa, kod inşa anında
  `KeyError` fırlatıyordu — üstelik fail-open (hata toleransı) mantığı devreye
  girmeden önce. Artık anahtarı olmayan model sessizce havuza girmiyor; hakem de
  Anthropic → OpenAI → Gemini sırasıyla mevcut bir modele düşüyor. (D-010)
- **Hakem/sentez için timeout yoktu:** Proposer çağrıları zaten süre sınırlıydı,
  ama hakem ve sentezleyici çağrıları değildi — biri takılırsa tüm istek süresiz
  askıda kalabilirdi. İkisini de `asyncio.wait_for` ile sardık. (D-012)
- **Sentezleyici hatası ele alınmıyordu ve çöküyordu:** Artık sentez başarısız
  olursa, kazanan adayın metni aynen döndürülüyor (dokümanın failure-mode
  tablosunun zaten söylediği davranış). (D-012)
- **D-009 sessiz rastgele seçim:** Hakem çıktısı ayrıştırılamadığında sistem ilk
  etikete düşüyor — ama ilk etiket rastgele karıştırılmış bir aday olduğu için bu
  fallback hakemi sessizce yazı-tura'ya çeviriyordu. Artık bu yola girildiğinde
  **gürültülü bir uyarı logu** basılıyor. (Bu, dokümanın "her şeyden önce
  yapılmalı" dediği 1 numaralı öncelikti.)
- **Düşen proposer'lar sessizce kayboluyordu:** Fanout, başarısız adayları
  loglamadan filtreliyordu — bir model her istekte düşebilir ve loglardan fark
  edilmezdi. Artık her düşen proposer nedeniyle birlikte loglanıyor.
- **Yapılandırılmış log yoktu:** Her tamamlanan istek için tek satırlık bir
  `logger.info` eklendi — kazanan, model başına gecikmeler, ve nihai cevabın
  kazanan adayla birebir aynı olup olmadığı (R-1 sinyali). (D-012)

### 2.3. Kurulum ve Bağımlılık
- **`python-dotenv`** eklendi; `main.py` artık `core` import edilmeden önce
  `.env`'i yüklüyor. (README zaten `cp .env.example .env` diyordu ama hiçbir şey
  o dosyayı yüklemiyordu — bu boşluğu kapattık.) (D-011)

### 2.4. Streamlit Sohbet Arayüzü
- Pipeline'ın üzerine, `main.py` ile paralel ikinci bir üst yüzey olarak zarif
  bir sohbet arayüzü (`app.py` + `ui/theme.py`) ekledik. (D-013)

---

## 3. Ne Kullandık?

| Katman | Teknoloji | Neden |
|---|---|---|
| Dil | Python 3.11+ | `dict[str, X]`, `str \| None` gibi modern tip söz dizimi; `async`/`await` |
| Eşzamanlılık | `asyncio` | Dört modeli paralel çağırmak; duvar-saati = en yavaş model, toplam değil |
| OpenAI ailesi | `openai` SDK | ChatGPT + Gemini + Grok, hepsi OpenAI-uyumlu endpoint (custom `base_url`) |
| Anthropic | `anthropic` SDK | Mesaj/içerik-blok şekli farklı olduğu için ayrı istemci |
| Ortam değişkenleri | `python-dotenv` | `.env`'i `os.environ`'a yüklemek |
| Arayüz | `streamlit` | Hızlı, tek dosyalık sohbet arayüzü |

**Model havuzu** (`core/config.py` içinde yapılandırma — mimari değil):

| `model_id` | Model | Taşıma | Anahtar |
|---|---|---|---|
| `chatgpt` | `gpt-4o` | OpenAI SDK | `OPENAI_API_KEY` |
| `claude` | `claude-sonnet-4-5` | Anthropic SDK | `ANTHROPIC_API_KEY` |
| `gemini` | `gemini-3.5-flash` | OpenAI SDK, custom `base_url` | `GEMINI_API_KEY` |
| `grok` | `grok-4.3` | OpenAI SDK, custom `base_url` | `XAI_API_KEY` |
| hakem | `claude-haiku-4-5` | Anthropic SDK | `ANTHROPIC_API_KEY` |

---

## 4. Mimari ve Akış

```
soru
   │
   ├──► chatgpt  ─┐
   ├──► claude   ─┤  asyncio.gather, bağımsız timeout'lar
   ├──► gemini   ─┤  hatalar model başına izole
   └──► grok     ─┘
                  │
                  ▼
         [Candidate, Candidate, ...]          fanout()
                  │
                  ▼
         karıştır + A/B/C/D etiketle          anonymize()
         label_map: {A: Candidate, ...}       ◄── orkestratorda kalır
                  │
                  ▼
         hakem modeli → {"winner": "B"}       judge()
                  │
                  ▼
         label_map["B"].model_id → "grok"     ◄── kimlik burada çözülür
         synthesizer = pool["grok"]
                  │
                  ▼
         4 adayı sentezle                     synthesize()
                  │
                  ▼
              FinalAnswer
```

**Bağımlılık yönü tek yönlüdür:**
`main.py / app.py → pipeline.py → config.py → providers.py → models.py`

- `models.py` — veri şekilleri (`Candidate`, `JudgeResult`, `FinalAnswer`)
- `providers.py` — heterojen SDK'ların üstünde tek bir `complete()` arayüzü
- `config.py` — model havuzu, hakem, sistem promptları, sabitler
- `pipeline.py` — altı adımlık akış; **hangi model_id'nin hangi sağlayıcıya
  ait olduğunu bilmez**
- `main.py` / `app.py` — CLI ve arayüz; mantık içermez

---

## 5. Tasarım Seçimleri ve Ardındaki Mantık

### 5.1. Kazanan model sentezleyici olur (D-002)
Hakem en iyi adayı seçer; o adayı üreten model, o istek için sentezleyici
rolüne yönlendirilir.

- **Lehine mantık:** Güçlü bir taslağa demir atmak (anchoring), sıfırdan
  sentezin getirdiği homojenleşmeye direnir ve tek tutarlı bir ses korur.
- **Aleyhine mantık:** Cevap üretmek ile cevap sentezlemek farklı yeteneklerdir.
  En iyi tek cevabı üreten model, dört metni birleştirmede en iyi olmayabilir.
  Ayrıca sentezleyici kendi çıktısını adaylardan biri olarak gördüğü için,
  anchoring yanlılığı ile öz-tercih (self-preference) yanlılığı birleşir.
- **Karar:** Dışarıdan (paydaşlar tarafından) verilmiş bir yön. Bu, tasarımın en
  sonuçlu ve en az test edilmiş varsayımı. Değerlendirme, sabit güçlü bir
  sentezleyicinin bunu geçtiğini gösterirse karar tersine döner — bu bir
  config-flag deneyi, yeniden yazım değil.

### 5.2. Adayları hakemden önce anonimleştir ve karıştır (D-003)
Hakem `--- Cevap A ---` bloklarını **karıştırılmış** sırada görür ve **model
adını asla** görmez. `label_map` orkestratorda kalır; hakem "B" dedikten sonra
kimlik orada çözülür.

- **Neden:** LLM hakemlerinin iki belgelenmiş hata biçimi — marka önyargısı
  ("bu GPT-4'ten" bilgisi bir prior taşır) ve pozisyon yanlılığı (ilk/son adayı
  kayırma). Anonimleştirme markayı, her istekte yeniden karıştırma sabit-slot
  avantajını kaldırır. İkisi de neredeyse bedava.
- **Yük taşıyan (load-bearing), kozmetik değil:** Bu eşleme prompt'a sızarsa her
  iki özellik de kaybolur.

### 5.3. Sistem promptları İngilizce, cevaplar sorunun dilinde (D-004)
Üç sistem promptu da İngilizce; her biri "cevabı sorunun dilinde yaz" kuralını
taşır.

- **Neden:** Format kısıtlarına (hakemin katı JSON'u) uyum İngilizcede daha
  güvenilir; havuz heterojen olduğu için en zayıf halkaya göre tasarlanmalı;
  İngilizce promptlar her çağrıda daha az token tüketir.

### 5.4. Aday metni asla normalize edilmez (D-005) — **pazarlık dışı**
Sağlayıcı çıktısı hakeme ve sentezleyiciye **birebir (verbatim)** akar. `strip()`
yok, Unicode normalizasyonu yok, yeniden kodlama yok.

- **Neden:** Unicode normalizasyonu ASCII-dışı metni sessizce bozar. Özellikle
  NFD ayrıştırması **Türkçe noktasız `ı`** gibi karakterleri düşürebilir ve hata
  gözle fark edilmez — metin neredeyse doğru görünür. Sistem Türkçe'yi
  desteklemek zorunda olduğu için bu hata sınıfı kabul edilemez; en kolay
  önlemi bu adımı hiç eklememek.
- **Test edildi:** Türkçe soruya Türkçe cevap alındı ve noktasız `ı` (Işık,
  yıldızların, salgılanmasını, kayıplar) tüm hat boyunca bozulmadan korundu.

### 5.5. Üç modelde OpenAI SDK taşıma (D-006)
Gemini ve Grok da OpenAI-uyumlu chat-completions endpoint'i sunar. Tek bir
`OpenAIProvider` sınıfı üç sağlayıcıyı kapsar; yalnızca Anthropic kendi
istemcisini gerektirir.

- **Bedeli:** Uyumluluk katmanı bir alt kümedir; sağlayıcıya özel özellikler
  (Gemini thinking config, Grok reasoning effort) `extra_body` olmadan
  erişilemez. MVP hiçbirini kullanmadığı için kabul edilebilir.

### 5.6. Hakem küçük ve ucuz bir model (D-007)
`claude-haiku-4-5` hakemlik yapar — üretmiyor, ayırt ediyor.

- **Neden:** Ayırt etmek üretmekten ucuzdur. On beş token'lık JSON döndüren bir
  görev için büyük bir hakem, her isteğin maliyetini kabaca ikiye katlar.
- **Bilinen kusur:** Hakem, dört proposer'dan biriyle (`claude`) aynı model
  ailesinden. Aile yakınlığı seçimi `claude` lehine yanlılaştırabilir (R-4).

### 5.7. Kısmi sonuçlarda fail-open (D-008)
Bir proposer timeout olur veya hata verirse adayı düşer; pipeline en az
`MIN_CANDIDATES` (2) hayatta kaldıkça devam eder.

- **Neden:** Sistemin öncülü sağlayıcılar arası artıklıktır (redundancy). Bir
  satıcı düştü diye tüm isteği düşürmek bu öncülü tersine çevirir.

### 5.8. Streamlit arayüzü, çekirdeği kirletmeden (D-013)
Sohbet transkripti **yalnızca görseldir**, `st.session_state`'te tutulur. Her
soru bağımsız, durumsuz bir `run(question)` çağrısıdır — önceki turlar modellere
beslenmez.

- **Neden:** Böylece "çok turlu diyalog yok" (PRD §3) kuralı çekirdek katmanda
  korunur; yalnızca sunum konuşma gibi hisseder. Bağımlılık grafiği yukarı doğru
  bir kenar değil, ikinci bir kök kazanır.
- **Gözlemlenebilirlik saklanmıyor, öne çıkarılıyor:** Kazanan + gecikme sessiz
  bir alt-yazı; tüm adaylar, hakem gerekçesi ve R-1 sinyali bir "details"
  açılırında. Cevap kahraman, meta enstrüman göstergesi.

---

## 6. Ele Aldığımız Kritik Noktalar ve Mantıkları

Bu proje "cevap üretiyor" ile "bitmiş" arasındaki farkı ciddiye alır. Ele
alınan kritik noktalar, öncelik sırasıyla:

### 6.1. D-009 — Sessiz rastgele seçim (en yüksek öncelik)
**Sorun:** Hakem geçerli JSON döndürmediğinde sistem ilk etikete düşüyordu. Ama
adaylar karıştırıldığı için ilk etiket **rastgele bir model**. Yani hiç geçerli
JSON döndürmeyen bir hakem, çalışıyormuş gibi görünen ama aslında rastgele seçen
bir sistem üretir — ve bu görünmez.
**Ele alış:** Bu yola girildiğinde artık ham çıktının bir kısmını içeren
`WARNING` seviyesinde bir log basılıyor. Davranış aynı, ama **gözlemlenebilir**.
**Mantık:** Bir hatayı düzeltmeden önce onu *görebilmen* gerekir. Log olmadan bu
hata ölçülemez.

### 6.2. R-1 — Sessizce seçime dejenerasyon
**Risk:** Sentezleyici, kazanan kendi cevabına demir atmış olabilir; diğer üçünü
yok sayıp yalnızca kendi cevabını cilalayabilir. Bu durumda sistem **sentez
değil seçim** yapar, ama çalışıyor gibi görünür.
**Ele alış:** Her istekte nihai cevabın kazanan adayla birebir aynı olup
olmadığını logluyoruz (`final_matches_winner_verbatim`) ve arayüzde açıkça
gösteriyoruz (✓ sentez oldu / ⚠ sentez olmadı).
**Mantık:** Bu, R-1'i ölçmenin **ilk ucuz sinyali**. Gerçek ölçüm birebir eşitlik
değil bir benzerlik metriği ister — bu M3/M4 işi, ama sinyal şimdiden orada.

### 6.3. Hakem tek hata noktası (R-2)
**Risk:** Düz bir karışım (mixture-of-agents) tasarımında kötü bir aday
diğerlerince seyreltilir. Burada ise hakem hatası aşağıya yayılır — her şey yanlış
taslağın üstüne kurulur.
**Ele alış (kısmen):** Hakem çağrısı başarısız olursa loglanır ve fallback'e
düşülür; pipeline çökmez. Tam çözüm (hakemin skorlu sıralama döndürmesi, üst-iki
skor yakınsa sabit güçlü sentezleyiciye düşmek) MVP sonrasına ertelenmiştir.

### 6.4. Aile yakınlığı × kazanan-yönlendirme birleşimi (R-4)
**Risk:** Hakem Claude ailesinden ve `claude` havuzda. Hakem `claude`'u kayırırsa
(R-4), ve kazanan sentezleyici olursa (D-002), hakem yanlılığı sadece bir kazanan
seçmez — **tüm nihai cevabın hangi modelin sesine demir atacağını** belirler. İki
risk toplanmaz, çarpılır.
**Ele alış:** Kazanan dağılımı loglandığı için bu skew ölçülebilir hale geldi.
Ayrıca Anthropic anahtarı yokken hakem OpenAI'ye düşüyor — bu, aile-dışı bir
hakemle R-4'ü test etme fırsatı da veriyor.

### 6.5. Kritik yolda timeout ve fallback (D-012)
**Sorun:** Fanout sonrası hakem ve sentez çağrıları süre sınırsızdı; biri
takılırsa istek süresiz askıda kalırdı. Sentez hatası ise çökerek yayılıyordu.
**Ele alış:** İkisi de `asyncio.wait_for(TIMEOUT_S)` ile sarıldı; sentez hatası
kazanan adayın metnine düşüyor. Bu davranış **gerçek bir 503 arıza altında test
edildi** — Gemini sentez sırasında "high demand" verince, sistem çökmek yerine
kazanan adayın metnini aynen döndürdü ve `final_matches_winner_verbatim=True`
ile bunu dürüstçe raporladı.

### 6.6. Güvenlik — sızan anahtarlar
**Sorun:** `.env.example` gerçek anahtarlar içeriyordu (NFR-5 ihlali).
**Ele alış:** Dosya boş placeholder'lara indirildi, gerçek `.env` gitignore'landı.
**Mantık:** Paylaşılabilir bir dosyada düz metin anahtar, sızmış anahtardır —
temizlemek yetmez, döndürmek (rotate) gerekir.

---

## 7. Bilinçli Olarak Yapmadıklarımız (Kapsam Dışı)

Bunlar unutulmuş değil, ertelenmiş kararlardır (PRD §3):
- Retry/backoff — *ancak:* OpenAI SDK varsayılan olarak retry yapıyor; bu, tek
  bir aksayan sağlayıcının timeout'u aşıp gecikmeyi şişirmesine yol açabiliyor.
  İstenirse `max_retries=0` ile kapatılabilir.
- Streaming (token akışı), önbellek, maliyet takibi, değerlendirme (evaluation)
  harness'ı, çok turlu diyalog, kalıcılık, kimlik doğrulama.

---

## 8. Şu Anki Durum

Çekirdek pipeline, üç canlı sağlayıcıyla (OpenAI, Anthropic, Gemini) uçtan uca
çalışıyor. CLAUDE.md'nin "bitmiş" tanımının her maddesi gerçek API'lere karşı
gösterildi:

| "Bitmiş" gereksinimi | Durum |
|---|---|
| Bir cevap üretir | ✅ İngilizce + Türkçe, tam havuz |
| Ölü bir sağlayıcıdan sağ çıkar | ✅ (kredisiz Claude düştü, loglandı; 503 sentez arızası fallback'e düştü) |
| Bozuk hakem yanıtından sağ çıkar | ✅ D-009 uyarısı basılıyor; rastgele-fallback gözlemlenebilir |
| Sentezin olup olmadığını söyleyecek kadar bilgi yayar | ✅ yapılandırılmış log + `final_matches_winner_verbatim` |

Kalan açık maddeler tamamı **belgelenmiş, bilinçli** MVP-sonrası işler — kırık
bir şey değil, ertelenmiş kararlar.

---

## 9. Çalıştırma

Python 3.11+ gerekir.

```bash
pip install -r requirements.txt   # openai, anthropic, python-dotenv, streamlit
cp .env.example .env              # ve anahtarları doldur
```

**CLI:**
```bash
python main.py "Gökyüzü neden mavi?"
```

**Web arayüzü:**
```bash
streamlit run app.py
```
