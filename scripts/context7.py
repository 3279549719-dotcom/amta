"""Context7 CLI wrapper — query up-to-date library documentation.

Reads CONTEXT7_API_KEY from env or ../.env (repo root parent). Zero deps (urllib).

Usage:
  python scripts/context7.py search <query> [libraryName]
  python scripts/context7.py ctx <libraryId> <query> [--type json|markdown]
  python scripts/context7.py libs <query>            # alias for search

Examples:
  python scripts/context7.py search "siliconflow OCR api"
  python scripts/context7.py ctx /websites/siliconflow_cn_cn "PaddleOCR model id free"
  python scripts/context7.py ctx /fastapi/fastapi "create router" --type markdown

Exit codes: 0 ok, 1 usage/auth error, 2 API error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://context7.com"
SEARCH = "/api/v2/libs/search"
CONTEXT = "/api/v2/context"


def load_key() -> str:
    key = os.environ.get("CONTEXT7_API_KEY", "").strip()
    if key:
        return key
    # repo layout: scripts/context7.py -> repo root -> parent has .env
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (os.path.dirname(here), os.path.dirname(os.path.dirname(here))):
        env = os.path.join(base, ".env")
        if os.path.exists(env):
            with open(env, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("CONTEXT7_API_KEY="):
                        return line.split("=", 1)[1].strip()
    sys.stderr.write("error: CONTEXT7_API_KEY not found in env or .env\n")
    raise SystemExit(1)


def get(path: str, params: dict, key: str) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{API}{path}?{qs}",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        sys.stderr.write(f"error: HTTP {e.code}: {body}\n")
        raise SystemExit(2)
    except urllib.error.URLError as e:
        sys.stderr.write(f"error: {e.reason}\n")
        raise SystemExit(2)


def print_search(data: dict) -> None:
    results = data.get("results", [])
    if not results:
        print("(no results)")
        return
    for r in results:
        title = r.get("title", "")
        rid = r.get("id", "")
        desc = (r.get("description") or r.get("summary") or "")[:160]
        print(f"id={rid}\ttitle={title}")
        if desc:
            print(f"  {desc}")


def print_context(data: dict, as_markdown: bool) -> None:
    code = data.get("codeSnippets", [])
    info = data.get("infoSnippets", [])
    if not code and not info:
        print("(no context snippets)")
        return
    for s in code:
        title = s.get("codeTitle", "code")
        if as_markdown:
            print(f"\n### {title}\n")
        else:
            print(f"\n--- {title} ---")
        for c in s.get("codeList", []):
            snippet = c.get("code", "")
            if as_markdown:
                print("```" + (c.get("language") or "") + "\n" + snippet + "\n```")
            else:
                print(snippet)
    for s in info:
        content = s.get("content", "")
        if as_markdown:
            print(f"\n> {content}\n")
        else:
            print(f"\nINFO: {content}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Context7 doc lookup CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_search = sub.add_parser("search", help="find libraries by name/query")
    p_search.add_argument("query")
    p_search.add_argument("libraryName", nargs="?", default="")
    p_ctx = sub.add_parser("ctx", help="get doc context for a library")
    p_ctx.add_argument("libraryId")
    p_ctx.add_argument("query")
    p_ctx.add_argument("--type", choices=["json", "markdown"], default="json")
    args = ap.parse_args(argv)

    key = load_key()
    if args.cmd == "search":
        params = {"query": args.query}
        if args.libraryName:
            params["libraryName"] = args.libraryName
        print_search(get(SEARCH, params, key))
    elif args.cmd == "ctx":
        print_context(
            get(CONTEXT, {"libraryId": args.libraryId, "query": args.query, "type": "json"}, key),
            as_markdown=(args.type == "markdown"),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
