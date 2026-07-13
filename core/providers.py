import os
from abc import ABC, abstractmethod

from anthropic import AsyncAnthropic
from azure.ai.inference.aio import ChatCompletionsClient as AzureInferenceClient
from azure.core.credentials import AzureKeyCredential
from openai import AsyncAzureOpenAI, AsyncOpenAI


class Provider(ABC):

    def __init__(self, model: str, proposer_max_tokens: int = 2048,
                 synth_max_tokens: int = 4096):
        self.model = model
        # Proposer (taslak) çağrılarının token bütçesi. Model başına config'de
        # ayarlanır (D-021): yavaş üreticiler (grok ~30 tok/s, claude uzun yazar)
        # düşük tutulur; reasoning modelleri (kimi) gizli düşünmeye token yaktığı
        # için YÜKSEK ister — düşük bütçe cevabı kısaltmaz, BOŞALTIR.
        self.proposer_max_tokens = proposer_max_tokens
        # Sentez çağrısının bütçesi (D-027). Aynı D-021 dersi sentez aşamasında:
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
