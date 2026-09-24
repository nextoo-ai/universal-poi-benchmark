from __future__ import annotations

import csv
import json
import sqlite3
import statistics
from pathlib import Path
from typing import Any


def _scalar(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    return int(connection.execute(sql, params).fetchone()[0])


def build_report(connection: sqlite3.Connection) -> dict[str, Any]:
    submissions = []
    for row in connection.execute(
        """
        SELECT s.id, s.agent_name, s.dataset_name, s.region_name, s.imported_at,
               COUNT(p.id) AS poi_count,
               SUM(CASE WHEN p.latitude IS NOT NULL AND p.longitude IS NOT NULL THEN 1 ELSE 0 END) AS geocoded_count,
               SUM(CASE WHEN p.description IS NOT NULL AND TRIM(p.description) <> '' THEN 1 ELSE 0 END) AS described_count
        FROM submissions s LEFT JOIN poi_records p ON p.submission_id=s.id
        GROUP BY s.id ORDER BY s.id
        """
    ):
        submissions.append(dict(row))

    url_statuses = {
        row["status"]: row["count"]
        for row in connection.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM url_checks
            WHERE id IN (
                SELECT MAX(id) FROM url_checks GROUP BY target_type, target_id
            )
            GROUP BY status ORDER BY status
            """
        )
    }
    match_relations = {
        row["relation"]: row["count"]
        for row in connection.execute(
            "SELECT relation, COUNT(*) AS count FROM matches GROUP BY relation ORDER BY relation"
        )
    }
    return {
        "totals": {
            "submissions": len(submissions),
            "poi_records": _scalar(connection, "SELECT COUNT(*) FROM poi_records"),
            "canonical_pois": _scalar(connection, "SELECT COUNT(*) FROM canonical_pois"),
            "links": _scalar(connection, "SELECT COUNT(*) FROM links"),
            "images": _scalar(connection, "SELECT COUNT(*) FROM images"),
            "evidence": _scalar(connection, "SELECT COUNT(*) FROM evidence"),
            "url_check_attempts": _scalar(connection, "SELECT COUNT(*) FROM url_checks"),
            "url_targets_checked": sum(url_statuses.values()),
            "open_review_items": _scalar(connection, "SELECT COUNT(*) FROM review_queue WHERE status IN ('pending','in_review')"),
            "open_conflicts": _scalar(connection, "SELECT COUNT(*) FROM conflicts WHERE status='open'"),
        },
        "submissions": submissions,
        "latest_url_checks_by_status": url_statuses,
        "matches_by_relation": match_relations,
    }


def write_report(connection: sqlite3.Connection, output: str | Path) -> dict[str, Any]:
    report = build_report(connection)
    Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


GOOD_URL_STATUSES = {"reachable", "redirected"}
BAD_URL_STATUSES = {"not_found", "invalid_url", "mime_mismatch", "blocked"}
INCONCLUSIVE_URL_STATUSES = {"rate_limited", "timeout", "network_error", "unverified"}


def _percent(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 2) if denominator else 0.0


def _agent_url_statuses(connection: sqlite3.Connection) -> dict[int, dict[str, int]]:
    result: dict[int, dict[str, int]] = {}
    rows = connection.execute(
        """
        WITH latest AS (
            SELECT u.*
            FROM url_checks u
            JOIN (
                SELECT target_type, target_id, MAX(id) AS max_id
                FROM url_checks GROUP BY target_type, target_id
            ) x ON x.max_id=u.id
        ), targets AS (
            SELECT 'link' AS target_type, l.id AS target_id, p.submission_id
            FROM links l JOIN poi_records p ON p.id=l.poi_record_id
            UNION ALL
            SELECT 'image', i.id, p.submission_id
            FROM images i JOIN poi_records p ON p.id=i.poi_record_id
            UNION ALL
            SELECT 'image_page', i.id, p.submission_id
            FROM images i JOIN poi_records p ON p.id=i.poi_record_id
            WHERE i.page_url IS NOT NULL AND TRIM(i.page_url) <> ''
            UNION ALL
            SELECT 'rating', r.id, p.submission_id
            FROM ratings r JOIN poi_records p ON p.id=r.poi_record_id
            WHERE r.source_url IS NOT NULL AND TRIM(r.source_url) <> ''
            UNION ALL
            SELECT 'evidence', e.id, p.submission_id
            FROM evidence e JOIN poi_records p ON p.id=e.poi_record_id
            WHERE e.url IS NOT NULL AND TRIM(e.url) <> ''
        )
        SELECT t.submission_id, u.status, COUNT(*) AS count
        FROM targets t JOIN latest u
          ON u.target_type=t.target_type AND u.target_id=t.target_id
        GROUP BY t.submission_id, u.status
        """
    )
    for row in rows:
        result.setdefault(int(row["submission_id"]), {})[row["status"]] = int(row["count"])
    return result


def build_agent_report(connection: sqlite3.Connection) -> dict[str, Any]:
    """Build a comparable, deterministic report for every submission.

    The score intentionally measures structural completeness and URL verification,
    not factual correctness or writing quality. Those require evidence-backed review.
    """
    url_by_submission = _agent_url_statuses(connection)
    agents: list[dict[str, Any]] = []
    submissions = connection.execute("SELECT * FROM submissions ORDER BY id").fetchall()
    for submission in submissions:
        submission_id = int(submission["id"])
        records = connection.execute(
            "SELECT id, description, normalized_name, latitude, longitude, category FROM poi_records "
            "WHERE submission_id=? ORDER BY id",
            (submission_id,),
        ).fetchall()
        record_ids = [int(row["id"]) for row in records]
        total = len(records)

        def records_with(table: str) -> int:
            return _scalar(
                connection,
                f"SELECT COUNT(DISTINCT p.id) FROM poi_records p JOIN {table} c ON c.poi_record_id=p.id "
                "WHERE p.submission_id=?",
                (submission_id,),
            )

        counts = {
            "poi": total,
            "geocoded": sum(r["latitude"] is not None and r["longitude"] is not None for r in records),
            "described": sum(bool((r["description"] or "").strip()) for r in records),
            "categorized": sum(bool((r["category"] or "").strip()) for r in records),
            "with_tags": records_with("poi_tags"),
            "with_external_id": records_with("external_identifiers"),
            "with_link": records_with("links"),
            "with_image": records_with("images"),
            "with_rating": records_with("ratings"),
            "with_evidence": records_with("evidence"),
        }
        rates = {key: _percent(value, total) for key, value in counts.items() if key != "poi"}

        descriptions = [(r["description"] or "").strip() for r in records if (r["description"] or "").strip()]
        lengths = [len(value) for value in descriptions]
        description_frequencies: dict[str, int] = {}
        for value in descriptions:
            normalized = " ".join(value.casefold().split())
            description_frequencies[normalized] = description_frequencies.get(normalized, 0) + 1
        repeated_descriptions = sum(count for count in description_frequencies.values() if count > 1)
        duplicate_name_records = _scalar(
            connection,
            """
            SELECT COALESCE(SUM(n), 0) FROM (
                SELECT COUNT(*) AS n FROM poi_records WHERE submission_id=?
                GROUP BY normalized_name HAVING COUNT(*) > 1
            )
            """,
            (submission_id,),
        )

        match_row = connection.execute(
            """
            SELECT
              COUNT(DISTINCT CASE WHEN m.relation='same_place' THEN p.id END) AS same_place,
              COUNT(DISTINCT CASE WHEN m.relation='uncertain' THEN p.id END) AS uncertain,
              COUNT(DISTINCT CASE WHEN m.id IS NOT NULL THEN p.id END) AS any_match
            FROM poi_records p
            LEFT JOIN matches m ON p.id=m.left_poi_record_id OR p.id=m.right_poi_record_id
            WHERE p.submission_id=?
            """,
            (submission_id,),
        ).fetchone()
        conflict_row = connection.execute(
            """
            SELECT COUNT(DISTINCT c.id) AS conflicts,
                   COUNT(DISTINCT CASE WHEN c.id IS NOT NULL THEN p.id END) AS records
            FROM poi_records p
            LEFT JOIN conflicts c ON p.id=c.left_poi_record_id OR p.id=c.right_poi_record_id
            WHERE p.submission_id=? AND (c.status='open' OR c.status IS NULL)
            """,
            (submission_id,),
        ).fetchone()

        statuses = url_by_submission.get(submission_id, {})
        url_total = sum(statuses.values())
        good = sum(statuses.get(status, 0) for status in GOOD_URL_STATUSES)
        bad = sum(statuses.get(status, 0) for status in BAD_URL_STATUSES)
        inconclusive = sum(statuses.get(status, 0) for status in INCONCLUSIVE_URL_STATUSES)
        conclusive = good + bad

        completeness_fields = (
            "geocoded", "described", "categorized", "with_tags", "with_external_id",
            "with_link", "with_image", "with_rating", "with_evidence",
        )
        completeness_score = round(sum(rates[field] for field in completeness_fields) / len(completeness_fields), 2)
        url_success_rate = _percent(good, conclusive)
        url_verification_coverage = _percent(conclusive, url_total)
        deterministic_score = round(
            0.50 * completeness_score + 0.30 * url_success_rate + 0.20 * url_verification_coverage,
            2,
        )

        agents.append(
            {
                "submission_id": submission_id,
                "agent_name": submission["agent_name"],
                "dataset_name": submission["dataset_name"],
                "region_name": submission["region_name"],
                "record_counts": counts,
                "field_coverage_percent": rates,
                "description_diagnostics": {
                    "average_characters": round(statistics.mean(lengths), 1) if lengths else 0.0,
                    "median_characters": round(statistics.median(lengths), 1) if lengths else 0.0,
                    "under_80_characters": sum(length < 80 for length in lengths),
                    "records_with_repeated_description": repeated_descriptions,
                    "records_with_duplicate_normalized_name": duplicate_name_records,
                },
                "url_validation": {
                    "total": url_total,
                    "good": good,
                    "bad": bad,
                    "inconclusive": inconclusive,
                    "success_percent_of_conclusive": url_success_rate,
                    "conclusive_coverage_percent": url_verification_coverage,
                    "by_status": dict(sorted(statuses.items())),
                },
                "cross_agent_comparison": {
                    "records_with_any_candidate": int(match_row["any_match"] or 0),
                    "records_with_same_place_match": int(match_row["same_place"] or 0),
                    "records_with_uncertain_match": int(match_row["uncertain"] or 0),
                    "unmatched_records": total - int(match_row["any_match"] or 0),
                    "open_conflicts_involving_agent": int(conflict_row["conflicts"] or 0),
                    "records_in_open_conflict": int(conflict_row["records"] or 0),
                },
                "provisional_deterministic_score": deterministic_score,
                "score_components": {
                    "structural_completeness_percent": completeness_score,
                    "url_success_percent": url_success_rate,
                    "url_conclusive_coverage_percent": url_verification_coverage,
                    "weights": {"structural_completeness": 0.50, "url_success": 0.30, "url_coverage": 0.20},
                },
            }
        )

    ranked = sorted(agents, key=lambda item: (-item["provisional_deterministic_score"], item["agent_name"]))
    for rank, agent in enumerate(ranked, 1):
        agent["provisional_rank"] = rank
    agents.sort(key=lambda item: item["submission_id"])
    return {
        "scope": "deterministic infrastructure only",
        "score_notice": (
            "The provisional score is 50% structural completeness, 30% success among conclusive URL checks, "
            "and 20% conclusive URL coverage. Rate limits and network failures are inconclusive, not broken links. "
            "Factual accuracy, description quality, image identity, licensing validity, and relevance require review."
        ),
        "agents": agents,
    }


def write_agent_report(
    connection: sqlite3.Connection,
    output: str | Path,
    markdown_output: str | Path | None = None,
) -> dict[str, Any]:
    report = build_agent_report(connection)
    Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if markdown_output:
        ranked = sorted(report["agents"], key=lambda item: item["provisional_rank"])
        lines = [
            "# Individual agent evaluation",
            "",
            report["score_notice"],
            "",
            "| Rank | Agent | Score | POIs | Completeness | URL success* | URL coverage | Same-place | Uncertain | Conflicts |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for agent in ranked:
            urls = agent["url_validation"]
            comparison = agent["cross_agent_comparison"]
            lines.append(
                f"| {agent['provisional_rank']} | {agent['agent_name']} | {agent['provisional_deterministic_score']:.2f} "
                f"| {agent['record_counts']['poi']} | {agent['score_components']['structural_completeness_percent']:.2f}% "
                f"| {urls['success_percent_of_conclusive']:.2f}% | {urls['conclusive_coverage_percent']:.2f}% "
                f"| {comparison['records_with_same_place_match']} | {comparison['records_with_uncertain_match']} "
                f"| {comparison['open_conflicts_involving_agent']} |"
            )
        lines.extend([
            "",
            "\\* URL success excludes rate limits, timeouts, network failures, and unverified responses from the denominator.",
            "Conflicts show disagreement and are not assigned as an error to either agent.",
            "",
        ])
        for agent in ranked:
            desc = agent["description_diagnostics"]
            urls = agent["url_validation"]
            coverage = agent["field_coverage_percent"]
            comparison = agent["cross_agent_comparison"]
            lines.extend([
                f"## {agent['provisional_rank']}. {agent['agent_name']} — {agent['provisional_deterministic_score']:.2f}",
                "",
                f"- Dataset: {agent['record_counts']['poi']} POIs; coordinates {coverage['geocoded']:.2f}%; descriptions {coverage['described']:.2f}%; tags {coverage['with_tags']:.2f}%; external IDs {coverage['with_external_id']:.2f}%.",
                f"- Descriptions: median {desc['median_characters']:.1f} characters; {desc['under_80_characters']} under 80 characters; {desc['records_with_repeated_description']} records reuse an identical description.",
                f"- URLs: {urls['good']} good, {urls['bad']} bad, {urls['inconclusive']} inconclusive, from {urls['total']} targets.",
                f"- Comparison: {comparison['records_with_same_place_match']} records corroborated as the same place, {comparison['records_with_uncertain_match']} uncertain, {comparison['unmatched_records']} unmatched, {comparison['open_conflicts_involving_agent']} open shared conflicts.",
                "",
            ])
        Path(markdown_output).write_text("\n".join(lines), encoding="utf-8")
    return report


def export_review_queue(
    connection: sqlite3.Connection, output: str | Path, output_format: str = "jsonl"
) -> int:
    rows = [
        dict(row)
        for row in connection.execute(
            """
            SELECT id, item_type, entity_type, entity_id, priority, reason_code,
                   json(payload_json) AS payload, status, assigned_to, created_at
            FROM review_queue
            WHERE status IN ('pending', 'in_review')
            ORDER BY priority DESC, id
            """
        )
    ]
    destination = Path(output)
    if output_format == "json":
        destination.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif output_format == "jsonl":
        destination.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    elif output_format == "csv":
        with destination.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["id"])
            writer.writeheader()
            writer.writerows(rows)
    else:
        raise ValueError("Format must be json, jsonl, or csv")
    return len(rows)
