import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.ai.llm import get_llm


def main() -> None:
    llm = get_llm()

    response = llm.invoke("Reply with exactly: LLM connection successful")

    print("\n=== RESPONSE ===")
    print(response)

    print("\n✅ LLM working")


if __name__ == "__main__":
    main()
