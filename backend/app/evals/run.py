import argparse, json, traceback
from datetime import datetime
from dataclasses import asdict
from .config import DATA, RESULTS
from .models import Result, Check
from .graders import retrieval, answer, classify
from .memo_grader import grade
from .report import write


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--application", required=True)
    p.add_argument("--suite", choices=["qa", "memo", "all"], default="all")
    p.add_argument("--mode", choices=["retrieval", "full"], default="retrieval")
    a = p.parse_args()
    from app.db.session import SessionLocal
    from .adapter import Adapter

    cases = json.loads((DATA / "qa_gold.json").read_text(encoding="utf-8"))
    results = []
    with SessionLocal() as s:
        ad = Adapter(s)
        ad.load(a.application)
        if a.suite in ["qa", "all"]:
            for case in cases:
                try:
                    selected = ad.retrieve(case["question"])
                    checks = retrieval(case, selected)
                    actual = {}
                    if a.mode == "full":
                        actual = ad.answer(case["question"])
                        checks += answer(case, actual)
                    status, layer = classify(checks)
                    trace = {
                        "selected": [
                            {
                                "content_id": getattr(x, "content_id", None),
                                "parent_content_id": getattr(
                                    x, "parent_content_id", None
                                ),
                                "page": getattr(x, "page_number", None),
                                "type": getattr(x, "content_type", None),
                                "section": getattr(x, "section_title", None),
                                "source": getattr(x, "source_reference", None),
                                "text": getattr(x, "text", "")[:1500],
                            }
                            for x in selected
                        ]
                    }
                    results.append(
                        Result(case["id"], status, layer, checks, actual, trace).dict()
                    )
                except Exception as e:
                    results.append(
                        Result(
                            case["id"],
                            "BLOCKED",
                            "environment",
                            [Check("execution", False, str(e))],
                            trace={"exception": traceback.format_exc()},
                        ).dict()
                    )
        if a.suite in ["memo", "all"]:
            try:
                if a.mode != "full":
                    raise RuntimeError("Memo evaluation requires --mode full")
                memo = ad.new_memo()
                checks = grade(memo)
                status = "PASS" if all(x.passed for x in checks) else "FAIL_GENERATION"
                results.append(
                    Result(
                        "MEMO-NEW",
                        status,
                        None if status == "PASS" else "generation",
                        checks,
                        memo,
                    ).dict()
                )
            except Exception as e:
                results.append(
                    Result(
                        "MEMO-NEW",
                        "BLOCKED",
                        "environment",
                        [Check("execution", False, str(e))],
                        trace={"exception": traceback.format_exc()},
                    ).dict()
                )
        s.rollback()
    passed = sum(x["status"] == "PASS" for x in results)
    blocked = sum(x["status"] == "BLOCKED" for x in results)
    failed = len(results) - passed - blocked
    payload = {
        "application": a.application,
        "created_at": datetime.now().isoformat(),
        "metrics": {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "blocked": blocked,
            "pass_rate": round(100 * passed / max(1, len(results) - blocked), 2),
        },
        "results": results,
    }
    out = RESULTS / datetime.now().strftime("%Y%m%d_%H%M%S")
    write(out, payload)
    print(json.dumps({"output": str(out), **payload["metrics"]}, indent=2))
    if failed or blocked:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
