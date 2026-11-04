"""Command line interface.

pptx-to-md INPUT [-o OUTPUT] [--llm] [--provider P] [--model M] [-v]
pptx-to-md configure [--show | --path]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__
from .config import PROVIDERS, ConfigError, config_path, load_settings
from .configure import require_tty, run_wizard, show_config
from .converter import convert_tree
from .llm import LLMDescriber
from .usage import format_summary


def _convert_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pptx-to-md",
        description="Convert .pptx presentations to Markdown. Run 'pptx-to-md configure' to set up an LLM.",
    )
    p.add_argument("input", type=Path, help=".pptx file, or a directory searched recursively for .pptx files")
    p.add_argument("-o", "--output", type=Path, default=Path("output"), help="output directory (default: ./output)")
    p.add_argument(
        "--llm",
        action="store_true",
        help="describe pictures and slides with an LLM (sends slide text and pictures to the provider; may cost money)",
    )
    p.add_argument("--provider", choices=PROVIDERS, help="LLM provider (default: from config / PPTX_TO_MD_PROVIDER)")
    p.add_argument("--model", help="LLM model id (default: from config / PPTX_TO_MD_MODEL / provider default)")
    p.add_argument("--workers", type=int, help="parallel LLM requests (default: 2)")
    p.add_argument("-v", "--verbose", action="store_true", help="log progress and per-deck LLM usage")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _configure_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pptx-to-md configure", description="Set up the LLM provider and credentials.")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--show", action="store_true", help="print the current config (secrets masked)")
    group.add_argument("--path", action="store_true", help="print the config file location")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "configure":
        return _configure(argv[1:])
    return _convert(argv)


def _configure(argv: list[str]) -> int:
    args = _configure_parser().parse_args(argv)
    try:
        if args.path:
            print(config_path())
        elif args.show:
            print(show_config())
        else:
            require_tty()
            run_wizard()
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled; nothing was changed.", file=sys.stderr)
        return 130
    return 0


def _convert(argv: list[str]) -> int:
    parser = _convert_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    logging.getLogger("pptx_to_md").setLevel(logging.INFO if args.verbose else logging.WARNING)

    if not args.input.exists():
        parser.error(f"input does not exist: {args.input}")

    try:
        settings = load_settings(provider=args.provider, model=args.model, workers=args.workers)
        describer = None
        if args.llm:
            if settings.provider is None:
                if not (sys.stdin.isatty() and sys.stdout.isatty()):
                    raise ConfigError("--llm needs a provider: run 'pptx-to-md configure' or set PPTX_TO_MD_PROVIDER")
                print("No LLM provider is configured yet - let's set one up.\n")
                run_wizard()
                print()
                settings = load_settings(provider=args.provider, model=args.model, workers=args.workers)
            describer = LLMDescriber(settings)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.", file=sys.stderr)
        return 130

    if describer is not None:
        print(f"LLM: {settings.provider} / {settings.model_id}")

    results = convert_tree(args.input, args.output, describer=describer, workers=settings.workers)
    if not results:
        print(f"No .pptx files found in {args.input}", file=sys.stderr)
        return 1
    failed = [(src, err) for src, err in results if err is not None]
    for src, err in failed:
        print(f"FAILED {src}: {err}", file=sys.stderr)
    print(f"Converted {len(results) - len(failed)}/{len(results)} deck(s) into {args.output}")

    if describer is not None:
        usage = describer.usage.snapshot()
        print("\nLLM usage:\n" + format_summary(usage))
        args.output.mkdir(parents=True, exist_ok=True)
        report = args.output / "llm_usage.json"
        report.write_text(json.dumps({"total": usage, "decks": describer.usage.decks}, indent=2), encoding="utf-8")
        print(f"Usage report: {report}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
