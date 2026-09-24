from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .db import complete_run, connect, evaluation_run, initialize
from .importer import import_dataset
from .matching import RELATIONS, match_candidates, resolve_match
from .reports import export_review_queue, write_agent_report, write_report
from .url_validator import UrlValidator, validate_urls


DEFAULT_CONFIG: dict[str, Any] = {
    "matching": {
        "exact_name_distance_m": 75.0,
        "fuzzy_name_distance_m": 250.0,
        "fuzzy_name_threshold": 0.86,
    },
    "url_validation": {
        "timeout_seconds": 10.0,
        "max_redirects": 5,
        "max_body_bytes": 65_536,
        "user_agent": "poi-evaluator/0.1",
        "workers": 16,
        "per_host": 4,
    },
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | None) -> dict[str, Any]:
    if not path:
        return DEFAULT_CONFIG
    return _merge(DEFAULT_CONFIG, json.loads(Path(path).read_text(encoding="utf-8")))


def _connection(path: str):
    connection = connect(path)
    initialize(connection)
    return connection


def _print(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="poi-evaluator", description="Evaluate POI JSON datasets in SQLite")
    parser.add_argument("--db", default="poi-evaluator.sqlite", help="SQLite database path")
    parser.add_argument("--config", help="JSON configuration file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Create or migrate the SQLite database")

    import_parser = subparsers.add_parser("import", help="Import one JSON dataset")
    import_parser.add_argument("dataset")
    import_parser.add_argument("--agent", required=True, help="Stable submission/agent label")

    match_parser = subparsers.add_parser("match", help="Generate cross-submission identity candidates")
    match_parser.add_argument("--exact-distance-m", type=float)
    match_parser.add_argument("--fuzzy-distance-m", type=float)
    match_parser.add_argument("--fuzzy-threshold", type=float)

    resolve_parser = subparsers.add_parser("resolve-match", help="Confirm the relationship for a match")
    resolve_parser.add_argument("match_id", type=int)
    resolve_parser.add_argument("relation", choices=sorted(RELATIONS))
    resolve_parser.add_argument("--reviewer", required=True)

    url_parser = subparsers.add_parser("validate-urls", help="Run SSRF-safe HTTP checks")
    url_parser.add_argument("--limit", type=int)
    url_parser.add_argument("--workers", type=int)
    url_parser.add_argument("--per-host", type=int)
    url_parser.add_argument("--no-resume", action="store_true")

    review_parser = subparsers.add_parser("export-review", help="Export pending review queue")
    review_parser.add_argument("output")
    review_parser.add_argument("--format", choices=("json", "jsonl", "csv"), default="jsonl")

    report_parser = subparsers.add_parser("report", help="Write a deterministic summary report")
    report_parser.add_argument("output")

    agent_report_parser = subparsers.add_parser(
        "agent-report", help="Write per-agent deterministic metrics and provisional ranking"
    )
    agent_report_parser.add_argument("output", help="JSON output path")
    agent_report_parser.add_argument("--markdown", help="Optional human-readable Markdown output path")

    pipeline_parser = subparsers.add_parser("pipeline", help="Import, match, optionally validate URLs, and report")
    pipeline_parser.add_argument(
        "--submission",
        action="append",
        default=[],
        metavar="AGENT=PATH",
        help="May be supplied more than once",
    )
    pipeline_parser.add_argument("--validate-urls", action="store_true")
    pipeline_parser.add_argument("--url-limit", type=int)
    pipeline_parser.add_argument("--url-workers", type=int)
    pipeline_parser.add_argument("--url-per-host", type=int)
    pipeline_parser.add_argument("--report", default="outputs/report.json")
    pipeline_parser.add_argument("--review", default="outputs/review-queue.jsonl")
    return parser


def _run_matching(connection, config: dict[str, Any], args: argparse.Namespace | None = None) -> dict[str, Any]:
    settings = config["matching"]
    exact = getattr(args, "exact_distance_m", None) if args else None
    fuzzy = getattr(args, "fuzzy_distance_m", None) if args else None
    threshold = getattr(args, "fuzzy_threshold", None) if args else None
    effective = {
        "exact_distance_m": exact if exact is not None else settings["exact_name_distance_m"],
        "fuzzy_distance_m": fuzzy if fuzzy is not None else settings["fuzzy_name_distance_m"],
        "fuzzy_threshold": threshold if threshold is not None else settings["fuzzy_name_threshold"],
    }
    with evaluation_run(connection, "matching", effective) as run_id:
        summary = match_candidates(connection, run_id, **effective)
        complete_run(connection, run_id, summary)
    return {"run_id": run_id, **summary}


def _run_urls(
    connection,
    config: dict[str, Any],
    limit: int | None,
    workers: int | None = None,
    per_host: int | None = None,
    resume: bool = True,
) -> dict[str, Any]:
    settings = config["url_validation"]
    validator = UrlValidator(
        timeout=float(settings["timeout_seconds"]),
        max_redirects=int(settings["max_redirects"]),
        max_body_bytes=int(settings["max_body_bytes"]),
        user_agent=str(settings["user_agent"]),
    )
    effective_workers = int(workers if workers is not None else settings["workers"])
    effective_per_host = int(per_host if per_host is not None else settings["per_host"])
    run_config = dict(
        settings,
        limit=limit,
        workers=effective_workers,
        per_host=effective_per_host,
        resume=resume,
    )
    with evaluation_run(connection, "url_validation", run_config) as run_id:
        summary = validate_urls(
            connection,
            run_id,
            validator,
            limit=limit,
            workers=effective_workers,
            per_host=effective_per_host,
            resume=resume,
        )
        complete_run(connection, run_id, summary)
    return {"run_id": run_id, **summary}


def _parse_submission(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise ValueError(f"Submission must use AGENT=PATH: {value}")
    agent, path = value.split("=", 1)
    if not agent.strip() or not path.strip():
        raise ValueError(f"Submission must use AGENT=PATH: {value}")
    return agent.strip(), path.strip()


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)
    connection = _connection(args.db)
    try:
        if args.command == "init-db":
            _print({"database": str(Path(args.db).resolve()), "status": "ready"})
        elif args.command == "import":
            _print(import_dataset(connection, args.dataset, args.agent))
        elif args.command == "match":
            _print(_run_matching(connection, config, args))
        elif args.command == "resolve-match":
            resolve_match(connection, args.match_id, args.relation, args.reviewer)
            _print({"match_id": args.match_id, "relation": args.relation, "status": "confirmed"})
        elif args.command == "validate-urls":
            _print(
                _run_urls(
                    connection,
                    config,
                    args.limit,
                    workers=args.workers,
                    per_host=args.per_host,
                    resume=not args.no_resume,
                )
            )
        elif args.command == "export-review":
            count = export_review_queue(connection, args.output, args.format)
            _print({"output": str(Path(args.output).resolve()), "items": count})
        elif args.command == "report":
            report = write_report(connection, args.output)
            _print({"output": str(Path(args.output).resolve()), "totals": report["totals"]})
        elif args.command == "agent-report":
            report = write_agent_report(connection, args.output, args.markdown)
            _print(
                {
                    "output": str(Path(args.output).resolve()),
                    "markdown": str(Path(args.markdown).resolve()) if args.markdown else None,
                    "agents": len(report["agents"]),
                }
            )
        elif args.command == "pipeline":
            imported = []
            for value in args.submission:
                agent, path = _parse_submission(value)
                imported.append(import_dataset(connection, path, agent))
            match_summary = _run_matching(connection, config)
            url_summary = (
                _run_urls(
                    connection,
                    config,
                    args.url_limit,
                    workers=args.url_workers,
                    per_host=args.url_per_host,
                )
                if args.validate_urls
                else None
            )
            report_path = Path(args.report)
            review_path = Path(args.review)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            review_path.parent.mkdir(parents=True, exist_ok=True)
            write_report(connection, report_path)
            review_count = export_review_queue(connection, review_path)
            _print(
                {
                    "imported": imported,
                    "matching": match_summary,
                    "url_validation": url_summary,
                    "report": str(report_path.resolve()),
                    "review_queue": str(review_path.resolve()),
                    "review_items": review_count,
                }
            )
    finally:
        connection.close()
    return 0


def main() -> None:
    try:
        raise SystemExit(run())
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
