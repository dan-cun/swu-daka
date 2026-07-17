"""Thin CLI entrypoint for the legacy SWU check-in flow."""

import sys

from legacy.cli import main


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"[!] {exc}")
        sys.exit(1)
