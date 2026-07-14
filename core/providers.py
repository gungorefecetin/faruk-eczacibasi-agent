import os
from abc import ABC, abstractmethod

import aiohttp
from anthropic import AsyncAnthropic
from azure.ai.inference.aio import ChatCompletionsClient as AzureInferenceClient
from azure.core.credentials import AzureKeyCredential
from openai import AsyncAzureOpenAI, AsyncOpenAI


class Provider(ABC):

    def __init__(self, model: str, proposer_max_tokens: int = 2048,
                 synth_max_tokens: int = 4096):
        self.model = model
        # Proposer (taslak) çağrılarının token bütçesi. Model başına config'de
        # ayarlanır : yavaş üreticiler (grok ~30 tok/s, claude uzun yazar)
        # düşük tutulur; reasoning modelleri (kimi) gizli düşünmeye token yaktığı
        # için YÜKSEK ister — düşük bütçe cevabı kısaltmaz, BOŞALTIR.
        self.proposer_max_tokens = proposer_max_tokens
        # Sentez çağrısının bütçesi.
        # kimi sentezleyici olunca 4096'nın bir kısmını gizli reasoning'e yakar,
        # uzun yapılandırılmış cevap ortasından kesilir (TOKEN_LIMIT_REACHED,
        # canlı vakada tablo satırı ortasında). Reasoning modellere cömert ver.
        self.synth_max_tokens = synth_max_tokens

    @abstractmethod
    async def complete(self, system: str, prompt: str, max_tokens: int = 2048) -> str:
        ...


class OpenAIProvider(Provider):
    def __init__(self, model: str, base_url: str | None = None,
                 api_key_env: str = "OPENAI_API_KEY", max_retries: int | None = None,
                 proposer_max_tokens: int = 2048, synth_max_tokens: int = 4096):
        super().__init__(model, proposer_max_tokens, synth_max_tokens)

        kwargs: dict = {"api_key": os.environ[api_key_env], "base_url": base_url}
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        self.client = AsyncOpenAI(**kwargs)

    async def complete(self, system: str, prompt: str, max_tokens: int = 2048) -> str:
        resp = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content or ""


class AzureOpenAIProvider(Provider):


    def __init__(self, deployment: str, azure_endpoint: str, api_version: str,
                 api_key: str):
        super().__init__(model=deployment)  # Azure için model == deployment adı
        self.client = AsyncAzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_version=api_version,
            api_key=api_key,
        )

    async def complete(self, system: str, prompt: str, max_tokens: int = 2048) -> str:
        resp = await self.client.chat.completions.create(
            model=self.model,  # Azure'da bu deployment adıdır
            # gpt-5.x nesli 'max_tokens'ı reddeder, 'max_completion_tokens' ister.
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content or ""


class AzureInferenceProvider(Provider):
    """Azure AI Foundry inference (azure.ai.inference). Grok, Kimi vb.

    Azure OpenAI'dan (AzureOpenAIProvider) AYRI bir aile: farklı SDK, farklı
    endpoint tipi (.services.ai.azure.com), farklı auth (AzureKeyCredential).
    Bkz. D-020. providers.py + config.py'ye dokunur, pipeline'a değil (CLAUDE.md #4).

    Endpoint biçimi kritik: doğrulanan çalışan yol `{kök-host}/models`. Config'de
    gelen `/api/projects/...` proje yolu KULLANILMAZ; yalnızca host köküne /models
    eklenir. api_version verilmez — SDK varsayılanı doğru olandır.
    """

    def __init__(self, model: str, endpoint: str, api_key: str,
                 proposer_max_tokens: int = 2048, synth_max_tokens: int = 4096):
        super().__init__(model, proposer_max_tokens, synth_max_tokens)
        root = endpoint.rstrip("/").split("/api/")[0]  # model == deployment adı
        self._endpoint = f"{root}/models"
        self._api_key = api_key

    async def complete(self, system: str, prompt: str, max_tokens: int = 2048) -> str:
        # İstemciyi çağrı başına aç/kapat: azure.ai.inference'ın async client'ı
        # kendi aiohttp session'ını tutar ve kapatılmazsa "Unclosed client
        # session" sızıntısı verir. `async with` temiz kapatmayı garanti eder.
        async with AzureInferenceClient(
            endpoint=self._endpoint,
            credential=AzureKeyCredential(self._api_key),
        ) as client:
            resp = await client.complete(
                model=self.model,
                # Kimi gibi modeller dahili reasoning'de token harcar; cömert tut.
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
        return resp.choices[0].message.content or ""


class AnthropicProvider(Provider):
    def __init__(self, model: str, api_key_env: str = "ANTHROPIC_API_KEY",
                 proposer_max_tokens: int = 2048, synth_max_tokens: int = 4096):
        super().__init__(model, proposer_max_tokens, synth_max_tokens)
        self.client = AsyncAnthropic(api_key=os.environ[api_key_env])

    async def complete(self, system: str, prompt: str, max_tokens: int = 2048) -> str:
        resp = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in resp.content if block.type == "text")


class PerplexityResponsesProvider(Provider):
    """Perplexity /v1/responses proposer'ı — web-grounded aday üretir.

    Diğer sağlayıcılardan AYRI bir aile: SDK yok, düz HTTP (aiohttp) ile
    POST https://api.perplexity.ai/v1/responses çağrılır. Preset tabanlı
    ("fast-search"), tek bir `input` string alanı bekler — bu yüzden sistem
    prompt'u ile kullanıcı sorusunu tek metinde güvenle birleştiriyoruz.

    Pipeline bu sağlayıcıyı diğerlerinden ayırt etmez (CLAUDE.md #2): sadece
    Provider.complete arayüzünü görür. Anahtar env'den okunur, ASLA hardcode
    edilmez; hata/timeout durumunda pipeline'ın diğer başarısız proposer'lara
    yaptığı gibi bu aday sessizce düşer (fanout izole eder).

    ANAHTAR AYRIMI (kullanıcı isteği): Responses ve Search API'ları AYRI
    anahtarlar kullanır — bu proposer YALNIZCA PERPLEXITY_RESPONSES_API_KEY'i
    okur, Search anahtarına asla dokunmaz.
    """

    ENDPOINT = "https://api.perplexity.ai/v1/responses"
    PRESET = "fast-search"

    def __init__(self, model: str, api_key_env: str = "PERPLEXITY_RESPONSES_API_KEY",
                 proposer_max_tokens: int = 2048, synth_max_tokens: int = 4096):
        super().__init__(model, proposer_max_tokens, synth_max_tokens)
        # Anahtar init'te okunur (havuz kurulurken zaten _has_key ile doğrulandı).
        self._api_key = os.environ[api_key_env]

    @staticmethod
    def _extract_text(data: dict) -> str:
        """Perplexity yanıtından SADECE nihai metni çıkar (savunmacı ayrıştırıcı).

        Yanıt şekli sürüme/preset'e göre değişebiliyor; bilinen dört biçim
        sırayla denenir. Hiçbiri metin vermezse ham JSON'u kullanıcıya SIZDIRMADAN
        net bir hata yükseltilir (metadata/anahtar/ham gövde asla mesaja girmez).
        """
        # 1) Düz kısayol: {"output_text": "..."}
        text = data.get("output_text")
        if isinstance(text, str) and text.strip():
            return text

        # 2) output[].content[].text  (type == "output_text" olanları tercih et)
        output = data.get("output")
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btext = block.get("text")
                    if isinstance(btext, str) and btext.strip():
                        parts.append(btext)
            if parts:
                return "".join(parts)

        # 3) OpenAI uyumlu biçim: choices[].message.content
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        return content

        # 4) Hiçbiri yok: ham gövdeyi/anahtarı SIZDIRMADAN net hata (req #8, #9).
        raise RuntimeError(
            "Perplexity yanıtından metin çıkarılamadı (beklenmeyen yanıt şekli)."
        )

    async def complete(self, system: str, prompt: str,
                       max_tokens: int | None = 2048) -> str:
        # Preset endpoint tek `input` alanı alır; sistem talimatı ile kullanıcı
        # sorusunu tek metinde birleştir (req #6). max_tokens arayüz uyumu için
        # kabul edilir ama fast-search preset'i gövdede kullanmaz.
        combined = (
            "System instructions:\n"
            f"{system}\n\n"
            "User request:\n"
            f"{prompt}"
        )
        payload = {"preset": self.PRESET, "input": combined}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        # Session'ı çağrı başına aç/kapat (azure inference sağlayıcısıyla aynı
        # desen): sızıntısız. Timeout pipeline'ın asyncio.wait_for'u ile ayrıca
        # da korunur; burada ağ-seviyesi bir tavan koyuyoruz.
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                self.ENDPOINT, json=payload, headers=headers
            ) as resp:
                # 4xx/5xx: ham gövdeyi kullanıcıya sızdırma; sadece durum kodu
                # (req #9). raise_for_status yerine kontrollü, redakte mesaj.
                if resp.status >= 400:
                    raise RuntimeError(
                        f"Perplexity isteği başarısız (HTTP {resp.status})."
                    )
                data = await resp.json()
        return self._extract_text(data)


class PerplexitySearchProvider:
    """Perplexity /search retrieval istemcisi — kanıt (evidence) katmanı.

    KASITLI OLARAK Provider'dan TÜREMEZ (CLAUDE.md #2 + kullanıcı isteği #10):
    bu bir aday ÜRETMEZ. Bir proposer/judge/synthesizer DEĞİLDİR ve build_pool /
    build_judge'a asla girmez — Provider arayüzü olmadığı için girmesi de
    imkânsız. Yalnızca ham arama sonuçları döndürür; onları bir kanıt bloğuna
    biçimlendirmek pipeline'ın (vendor-neutral) işi.

    ANAHTAR AYRIMI: YALNIZCA PERPLEXITY_SEARCH_API_KEY okur; Responses
    anahtarına asla dokunmaz. Hata/timeout'ta çağıran taraf kanıtsız devam
    eder (fail-open) — bu yüzden search() ham sonuç listesi döndürür veya
    yükseltir; karar üst katmanda.
    """

    ENDPOINT = "https://api.perplexity.ai/search"

    def __init__(self, api_key_env: str = "PERPLEXITY_SEARCH_API_KEY"):
        self._api_key = os.environ[api_key_env]

    async def search(self, query: str, max_results: int = 3,
                     max_tokens_per_page: int = 256,
                     timeout_s: int = 15) -> list[dict]:
        """Arama sonuçlarını [{title, url, snippet}, ...] olarak döndür.

        Yanıt şekli sürüme göre değişebildiği için savunmacı ayrıştırma:
        sonuç listesi `results` (veya `data`) altında olabilir; her sonuçta
        başlık `title`, url `url`, metin ise `snippet`/`text`/`content`
        anahtarlarından biriyle gelebilir. Ham gövde/anahtar ASLA sızmaz.
        """
        payload = {
            "query": query,
            "max_results": max_results,
            "max_tokens_per_page": max_tokens_per_page,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=timeout_s)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                self.ENDPOINT, json=payload, headers=headers
            ) as resp:
                if resp.status >= 400:
                    # Ham gövdeyi sızdırma; sadece durum kodu (req #7).
                    raise RuntimeError(
                        f"Perplexity search başarısız (HTTP {resp.status})."
                    )
                data = await resp.json()
        return self._normalize(data, max_results)

    @staticmethod
    def _normalize(data: dict, max_results: int) -> list[dict]:
        """Ham arama yanıtını temiz [{title,url,snippet}] listesine indir."""
        raw = data.get("results")
        if not isinstance(raw, list):
            raw = data.get("data") if isinstance(data.get("data"), list) else []
        out: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            snippet = (
                item.get("snippet")
                or item.get("text")
                or item.get("content")
                or ""
            )
            out.append({
                "title": str(item.get("title") or "").strip(),
                "url": str(item.get("url") or "").strip(),
                "snippet": str(snippet).strip(),
            })
            if len(out) >= max_results:
                break
        return out
