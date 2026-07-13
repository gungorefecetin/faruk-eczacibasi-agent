import asyncio
import logging
import sys

from dotenv import load_dotenv

load_dotenv()  # .env dosyasını os.environ'a yükle (varsa)

from core.pipeline import run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


async def main() -> None:
    question = " ".join(sys.argv[1:]) or input("Soru: ")
    result = await run(question)

    print(f"\n--- Adaylar ({len(result.candidates)}) ---")
    for c in result.candidates:
        print(f"  {c.model_id:8s} {c.latency_ms:>6d} ms")

    print(f"\nKazanan / sentezleyici: {result.synthesizer_model}")
    print(f"Judge gerekçesi: {result.judge_reason}")
    print(f"\n--- Nihai cevap ---\n{result.answer}")


if __name__ == "__main__":
    asyncio.run(main())
