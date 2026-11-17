from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.ai.llm import get_llm
from app.ai.retrieval.json_utils import parse_json_object


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default='Return JSON only: {"status": "ok"}')
    args = parser.parse_args()
    raw = get_llm().invoke(args.prompt, max_tokens=300)
    print("RAW RESPONSE:")
    print(repr(raw))
    print("\nPARSED JSON:")
    print(json.dumps(parse_json_object(raw), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
