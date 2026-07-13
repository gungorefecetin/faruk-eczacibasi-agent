from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Candidate:
    """Bir proposer modelin ürettiği aday cevap."""
    model_id: str          # dostça havuz adı (ör. "chatgpt")
    text: str
    latency_ms: int = 0
    error: Optional[str] = None
    model_name: str = ""   # gerçek model dizesi (ör. "gpt-4o"), UI gösterimi için

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text.strip())


@dataclass
class JudgeResult:
    """Judge'ın kararı. winner_label anonim etikettir (A, B, C, D)."""
    winner_label: str
    reason: str = ""
    raw: str = ""


@dataclass
class FinalAnswer:
    """Pipeline'ın nihai çıktısı."""
    answer: str
    winner_model: str
    synthesizer_model: str
    candidates: list[Candidate] = field(default_factory=list)
    judge_reason: str = ""
    # R-1 sinyali: nihai cevabın kazanan adaya benzerliği (0.0-1.0). Yüksekse
    # sentez değil seçim yapılmış demektir. Bkz. pipeline._run, D-018.
    winner_similarity: float = 0.0
    # Sentezleyicinin gerekçesi: adayları neden/nasıl birleştirdiği (D-019).
    # Boş olabilir (ayraç gelmezse veya sentez fallback'e düşerse).
    synthesis_reasoning: str = ""
    # Anonim etiket -> model_id eşlemesi (ör. {"A": "chatgpt"}), YALNIZCA görüntü
    # katmanı için (D-023). Anonimlik invariant'ı bozulmaz: judge/sentezleyici
    # prompt'ları hâlâ sadece etiket görür; kimlik verdikten SONRA çözülür ve
    # kullanıcıya gösterim için buraya konur.
    labels: dict[str, str] = field(default_factory=dict)
