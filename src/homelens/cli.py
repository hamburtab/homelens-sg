"""Installed command-line entry point."""

from __future__ import annotations

import argparse
import json

from homelens.service import HomeLensService
from homelens.utils import json_default
from homelens.web import serve


def main() -> None:
    parser = argparse.ArgumentParser(prog="homelens")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="show dataset, model and integration status")
    web_parser = subparsers.add_parser("serve", help="serve the local web application")
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8000)

    recommend_parser = subparsers.add_parser("recommend", help="request recommendations")
    recommend_parser.add_argument("--budget", type=float, required=True)
    recommend_parser.add_argument("--query", default="")
    recommend_parser.add_argument("--flat-type", action="append", default=[])
    recommend_parser.add_argument("--town", action="append", default=[])
    recommend_parser.add_argument("--top-k", type=int, default=5)
    recommend_parser.add_argument("--use-llm", action="store_true")

    args = parser.parse_args()
    if args.command == "serve":
        serve(args.host, args.port)
        return
    service = HomeLensService()
    if args.command == "status":
        result = service.health()
    else:
        result = service.get_recommendations(
            {
                "budget": args.budget,
                "query": args.query,
                "flat_types": args.flat_type,
                "preferred_towns": args.town,
                "top_k": args.top_k,
                "use_llm": args.use_llm,
            }
        )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=json_default))


if __name__ == "__main__":
    main()
