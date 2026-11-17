from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "datasets"
RESULTS = HERE.parents[2] / "eval_results"
