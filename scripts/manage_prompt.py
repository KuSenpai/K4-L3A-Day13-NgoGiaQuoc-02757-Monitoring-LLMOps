"""Quản lý prompt `day13-chat` trong project Langfuse cá nhân.

Ví dụ:
    python scripts/manage_prompt.py create      # tạo v1 (baseline, production) và v2 (candidate)
    python scripts/manage_prompt.py promote 2   # gắn production cho version 2
    python scripts/manage_prompt.py rollback 1  # đưa production về version 1
    python scripts/manage_prompt.py show
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio

PROMPT_V1 = "Feature={{feature}}\nDocs={{docs}}\nQuestion={{message}}"
PROMPT_V2 = (
    "Feature={{feature}}\n"
    "Docs={{docs}}\n"
    "Question={{message}}\n"
    "Answer in at most 3 short bullet points, using only the docs above."
)
# Label production chỉ được giữ bởi một version tại một thời điểm.
BASE_LABELS = {1: ["baseline"], 2: ["candidate"]}


def _client():
    from langfuse import Langfuse

    load_dotenv(REPO_ROOT / ".env")
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        raise SystemExit("Thiếu LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY trong .env")
    return Langfuse()


def show(client, name: str) -> None:
    for version in (1, 2):
        try:
            prompt = client.get_prompt(name, version=version, cache_ttl_seconds=0)
        except Exception as exc:  # version chưa tồn tại
            print(f"v{version}: không lấy được ({type(exc).__name__})")
            continue
        print(f"v{prompt.version}: labels={prompt.labels}")


def create(client, name: str) -> None:
    client.create_prompt(
        name=name,
        prompt=PROMPT_V1,
        labels=["baseline", "production"],
        type="text",
        commit_message="v1: baseline template",
    )
    client.create_prompt(
        name=name,
        prompt=PROMPT_V2,
        labels=["candidate"],
        type="text",
        commit_message="v2: concise bullet-point answers",
    )


def set_production(client, name: str, version: int) -> None:
    client.update_prompt(name=name, version=version, new_labels=BASE_LABELS[version] + ["production"])


def main() -> None:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create", "promote", "rollback", "show"])
    parser.add_argument("version", nargs="?", type=int, choices=[1, 2])
    args = parser.parse_args()

    name = os.getenv("LANGFUSE_PROMPT_NAME", "day13-chat")
    client = _client()
    if args.action == "create":
        create(client, name)
    elif args.action in {"promote", "rollback"}:
        if args.version is None:
            parser.error("promote/rollback cần version (1 hoặc 2)")
        set_production(client, name, args.version)
    show(client, name)


if __name__ == "__main__":
    main()
