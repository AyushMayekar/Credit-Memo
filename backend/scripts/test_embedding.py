import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.ai.embedding_model import get_embedding_client


def main():

    embedder = get_embedding_client()

    embedding = embedder.embed_text("The company reported strong revenue growth.")

    print("\n=== EMBEDDING DETAILS ===")
    print(f"Dimensions: {len(embedding)}")

    print("\nFirst 10 Values:")
    print(embedding[:10])

    print("\n✅ Embeddings working")


if __name__ == "__main__":
    main()
