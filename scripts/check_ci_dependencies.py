"""Fail required CI summaries when an upstream job failed or was skipped."""

import json
import os


def unsuccessful_dependencies(results: dict[str, dict[str, str]]) -> list[str]:
    if not results:
        return ["<no dependency results>"]
    return sorted(
        name for name, job in results.items() if job.get("result") != "success"
    )


def main() -> int:
    failed = unsuccessful_dependencies(json.loads(os.environ["NEEDS_JSON"]))
    if failed:
        print(f"Required dependencies did not succeed: {', '.join(failed)}")
        return 1
    print("All dependency jobs succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
