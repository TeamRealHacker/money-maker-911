"""Turn the pytest report (written by tests/conftest.py) into a failure summary.

The job log and the uploaded artifacts both live on a blob host that is not always reachable,
so the summary is published as a step summary *and* as a check-run annotation: annotations are
served by api.github.com, which is what makes a red Windows run diagnosable from anywhere.

Used by .github/workflows/build.yml:

    python .github/scripts/test_report.py test-report.txt --github-summary "$GITHUB_STEP_SUMMARY"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

MAX_ANNOTATIONS = 50          # the checks API caps annotations per request
MAX_MESSAGE = 6000            # and the size of each annotation message


def read_report(path: Path) -> dict:
    failures: list[tuple[str, str]] = []
    host = ""
    node = None
    detail: list[str] = []
    if path.exists():
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if raw.startswith("[configure]") and not host:
                host = raw.split("]", 1)[1].strip()
            elif raw.startswith("[FAILED]"):
                if node:
                    failures.append((node, "\n".join(detail)))
                node, detail = raw.split("]", 1)[1].strip(), []
            elif node and raw.startswith("    "):
                detail.append(raw[4:])
            elif raw.startswith("[finish]") and (not host or "elapsed" not in host):
                host = host or raw.split("]", 1)[1].strip()
        if node:
            failures.append((node, "\n".join(detail)))
    return {"failures": failures, "host": host, "found": path.exists()}


def summary_text(info: dict) -> str:
    lines = ["### Pytest failures", ""]
    if not info["found"]:
        lines.append("_no test report was written (did the Tests step start?)_")
        return "\n".join(lines)
    if info["host"]:
        lines += [f"host: `{info['host']}`", ""]
    if not info["failures"]:
        lines.append("no failures recorded")
        return "\n".join(lines)
    lines.append(f"{len(info['failures'])} failing test(s):")
    lines.append("")
    for node, _ in info["failures"]:
        lines.append(f"- `{node}`")
    return "\n".join(lines)


def post_annotations(info: dict) -> None:
    """Publish the failures as a check run, so they are readable through api.github.com.

    The job log and the artifacts live on a blob host that is not always reachable; annotations
    are served by the API, which is what makes a red run diagnosable. Needs GH_TOKEN and the
    GITHUB_* env vars (CI only, `permissions: checks: write`).
    """
    token, repo = os.environ.get("GH_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    head = os.environ.get("GITHUB_SHA")
    if not (token and repo and head and info["failures"]):
        return
    payload = {
        "name": "pytest",
        "head_sha": head,
        "status": "completed",
        "conclusion": "failure",
        "output": {
            "title": f"{len(info['failures'])} failing test(s)",
            "summary": summary_text(info)[:65000],
            "annotations": [{"path": ".github/workflows/build.yml",
                             "start_line": 1, "end_line": 1,
                             "annotation_level": "failure",
                             "title": (node.split("::")[-1] or node)[:250],
                             "message": (node + "\n\n" + detail)[:MAX_MESSAGE]}
                            for node, detail in info["failures"][:MAX_ANNOTATIONS]],
        },
    }
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/check-runs",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"posted check run: {r.status}")
    except Exception as e:                  # annotations are a convenience, never fail the job
        print(f"could not post annotations: {e}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", nargs="?", default="test-report.txt")
    ap.add_argument("--github-summary")
    a = ap.parse_args()
    info = read_report(Path(a.report))
    text = summary_text(info)
    print(text)
    if os.environ.get("POST_ANNOTATIONS") == "1":
        post_annotations(info)
    if a.github_summary:
        with open(a.github_summary, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
