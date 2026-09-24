from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PERMISSIVE_LICENSES = {
    "cc0-1.0",
    "public-domain",
    "cc-by-2.0",
    "cc-by-2.5",
    "cc-by-3.0",
    "cc-by-4.0",
    "cc-by-sa-2.0",
    "cc-by-sa-2.5",
    "cc-by-sa-3.0",
    "cc-by-sa-4.0",
}


def _json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _license_name(value: str | None) -> str | None:
    if not value or value.strip().casefold() in {"unknown", "unspecified", "n/a", "none"}:
        return None
    text = value.strip().casefold().replace("creative commons", "cc")
    text = re.sub(r"[^a-z0-9.]+", "-", text).strip("-")
    aliases = {
        "public-domain-mark": "public-domain",
        "public-domain-mark-1.0": "public-domain",
        "cc-zero": "cc0-1.0",
        "cc0": "cc0-1.0",
        "cc0-1": "cc0-1.0",
    }
    normalized = aliases.get(text, text)
    match = re.search(r"cc-(by(?:-sa)?)-([234](?:\.0)?|2\.5)", normalized)
    if match:
        return f"cc-{match.group(1)}-{float(match.group(2)):.1f}"
    return normalized


def _entity_id(rows: list[sqlite3.Row], external_ids: list[sqlite3.Row]) -> str:
    wikidata = sorted(
        {str(row["external_id"]) for row in external_ids if str(row["namespace"]).casefold() == "wikidata"}
    )
    if wikidata:
        return f"wikidata:{wikidata[0]}"
    basis = "|".join(sorted(f"{row['agent_name']}:{row['original_poi_id']}" for row in rows))
    slug = re.sub(r"[^a-z0-9]+", "-", rows[0]["normalized_name"]).strip("-")[:48] or "poi"
    return f"poi:{slug}-{hashlib.sha256(basis.encode()).hexdigest()[:12]}"


def _majority(rows: list[sqlite3.Row], field: str, preferred: sqlite3.Row) -> str | None:
    values = [str(row[field]).strip() for row in rows if row[field] and str(row[field]).strip()]
    if not values:
        return None
    counts = Counter(value.casefold() for value in values)
    maximum = max(counts.values())
    winners = {value for value, count in counts.items() if count == maximum}
    preferred_value = preferred[field]
    if preferred_value and str(preferred_value).strip().casefold() in winners:
        return str(preferred_value).strip()
    return sorted((value for value in values if value.casefold() in winners), key=lambda v: (v.casefold(), v))[0]


def _richness(row: sqlite3.Row, counts: dict[int, int]) -> tuple[int, int, int]:
    raw = _json(row["raw_json"], {})
    description = row["description"] or ""
    populated = sum(value not in (None, "", [], {}) for value in raw.values()) if isinstance(raw, dict) else 0
    return (min(len(description), 4000) + counts.get(row["id"], 0) * 60 + populated * 5, len(description), -row["id"])


def _group_rows(connection: sqlite3.Connection) -> tuple[dict[str, list[sqlite3.Row]], dict[int, str]]:
    rows = connection.execute(
        """
        SELECT p.*, s.agent_name, s.dataset_name, s.dataset_version, s.language,
               s.region_name AS submission_region
        FROM poi_records p JOIN submissions s ON s.id=p.submission_id
        ORDER BY p.id
        """
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    record_to_entity: dict[int, str] = {}
    for row in rows:
        key = f"canonical:{row['canonical_poi_id']}" if row["canonical_poi_id"] is not None else f"record:{row['id']}"
        groups[key].append(row)
        record_to_entity[row["id"]] = key
    return dict(groups), record_to_entity


def _by_record(connection: sqlite3.Connection, table: str) -> dict[int, list[sqlite3.Row]]:
    result: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in connection.execute(f"SELECT * FROM {table} ORDER BY poi_record_id").fetchall():
        result[row["poi_record_id"]].append(row)
    return result


def _latest_url_status(connection: sqlite3.Connection, target_type: str) -> dict[int, str]:
    return {
        row["target_id"]: row["status"]
        for row in connection.execute(
            """
            SELECT u.target_id, u.status FROM url_checks u
            JOIN (SELECT target_id, MAX(id) id FROM url_checks WHERE target_type=? GROUP BY target_id) latest
              ON latest.id=u.id
            """,
            (target_type,),
        ).fetchall()
    }


def _media_item(row: sqlite3.Row, conflict_urls: set[str]) -> dict[str, Any]:
    raw = _json(row["raw_json"], {})
    license_name = row["license"] or raw.get("license")
    normalized = _license_name(license_name)
    license_url = raw.get("licenseUrl") or raw.get("license_url")
    creator = row["creator"] or raw.get("creator")
    attribution = raw.get("attribution")
    source_page = row["page_url"] or raw.get("sourcePageUrl") or raw.get("pageUrl")
    if row["image_url"] in conflict_urls:
        rights = "conflicting"
    elif not normalized:
        rights = "unknown"
    elif (
        normalized in PERMISSIVE_LICENSES
        and license_url
        and source_page
        and (creator or attribution or normalized in {"cc0-1.0", "public-domain"})
    ):
        rights = "verified-permissive"
    else:
        rights = "declared"
    return {
        "url": row["image_url"],
        "sourcePageUrl": source_page or row["image_url"],
        "license": {"name": license_name or "unknown", "normalized": normalized, "url": license_url},
        "rightsStatus": rights,
        "creator": creator,
        "attribution": attribution,
        "caption": row["caption"] or raw.get("caption"),
    }


def _rating_item(row: sqlite3.Row, url_status: dict[int, str]) -> dict[str, Any] | None:
    if row["rating"] is None:
        return None
    raw = _json(row["raw_json"], {})
    value = float(row["rating"])
    explicit = row["rating_scale"] or raw.get("scale") or raw.get("max")
    if isinstance(explicit, dict):
        scale_min, scale_max = float(explicit.get("min", 0)), float(explicit["max"])
        inference = "explicit"
    elif explicit:
        scale_min, scale_max, inference = 0.0, float(explicit), "explicit"
    elif str(row["provider"]).casefold() in {"google", "google-maps", "google maps"}:
        scale_min, scale_max, inference = 0.0, 5.0, "provider-rule"
    else:
        scale_min = 0.0
        scale_max = 5.0 if value <= 5 else 10.0 if value <= 10 else 100.0
        inference = "dataset-inferred"
    normalized = max(0.0, min(1.0, (value - scale_min) / (scale_max - scale_min)))
    status = url_status.get(row["id"])
    verification = (
        "verified-source"
        if row["source_url"] and status in {"reachable", "redirected"}
        else "source-unavailable"
        if not row["source_url"]
        else "unverified"
    )
    observed = row["observed_at"] or raw.get("verifiedAt") or raw.get("observedAt")
    return {
        "provider": row["provider"],
        "value": value,
        "scale": {"min": scale_min, "max": scale_max},
        "normalizedScore": round(normalized, 6),
        "scaleInference": inference,
        "verificationStatus": verification,
        "reviewCount": row["review_count"],
        "observedAt": observed,
        "sourceUrl": row["source_url"],
    }


def _best_ratings(rows: Iterable[sqlite3.Row], statuses: dict[int, str]) -> list[dict[str, Any]]:
    by_provider: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        if row["rating"] is not None:
            by_provider[str(row["provider"]).casefold()].append(row)
    result = []
    for provider in sorted(by_provider):
        candidates = by_provider[provider]
        best = max(
            candidates,
            key=lambda r: (
                statuses.get(r["id"]) in {"reachable", "redirected"},
                r["source_url"] is not None,
                r["review_count"] or -1,
                r["observed_at"] or "",
                -r["id"],
            ),
        )
        item = _rating_item(best, statuses)
        if item:
            result.append(item)
    return result


def build_canonical_datasets(
    connection: sqlite3.Connection, dataset_version: str = "canonical-v1"
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    groups, record_to_entity = _group_rows(connection)
    ambiguous: set[str] = set()
    for row in connection.execute(
        "SELECT left_poi_record_id, right_poi_record_id FROM matches WHERE relation='uncertain' AND status='candidate'"
    ).fetchall():
        ambiguous.update((record_to_entity[row[0]], record_to_entity[row[1]]))
    high_conflicts = {
        record_to_entity[row[0]]
        for row in connection.execute(
            "SELECT left_poi_record_id FROM conflicts WHERE severity='high' AND status='open'"
        ).fetchall()
        if row[0] in record_to_entity
    }

    tables = {
        name: _by_record(connection, name)
        for name in ("external_identifiers", "poi_tags", "links", "images", "ratings", "evidence")
    }
    tags = {row["id"]: row["slug"] for row in connection.execute("SELECT id, slug FROM tags")}
    rating_status = _latest_url_status(connection, "rating")
    license_sets: dict[str, set[str | None]] = defaultdict(set)
    for rows in tables["images"].values():
        for row in rows:
            license_sets[row["image_url"]].add(_license_name(row["license"] or _json(row["raw_json"], {}).get("license")))
    conflicting_image_urls = {url for url, licenses in license_sets.items() if len(licenses) > 1}

    detailed_pois: list[dict[str, Any]] = []
    safe_pois: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for key in sorted(groups, key=lambda k: min(row["id"] for row in groups[k])):
        rows = groups[key]
        reasons = []
        if key in ambiguous:
            reasons.append("open_uncertain_identity")
        if key in high_conflicts:
            reasons.append("open_high_severity_conflict")
        if reasons:
            exclusions.append({"entity": key, "recordIds": [row["id"] for row in rows], "reasons": reasons})
            continue

        member_ids = [row["id"] for row in rows]
        child_count = {
            record_id: sum(len(tables[name].get(record_id, [])) for name in tables)
            for record_id in member_ids
        }
        representative = max(rows, key=lambda row: _richness(row, child_count))
        external_rows = [item for record_id in member_ids for item in tables["external_identifiers"].get(record_id, [])]
        canonical_id = _entity_id(rows, external_rows)
        raw_rows = [_json(row["raw_json"], {}) for row in rows]
        names = {row["name"].strip() for row in rows if row["name"].strip()}
        for raw in raw_rows:
            for name in raw.get("alternateNames", []) if isinstance(raw, dict) else []:
                if isinstance(name, str) and name.strip():
                    names.add(name.strip())
        names.discard(representative["name"].strip())
        coordinates = [(row["latitude"], row["longitude"]) for row in rows if row["latitude"] is not None and row["longitude"] is not None]
        location = {
            "latitude": statistics.median(point[0] for point in coordinates),
            "longitude": statistics.median(point[1] for point in coordinates),
        }
        for source, target in (("address", "address"), ("locality", "locality"), ("region", "region"), ("country_code", "countryCode")):
            value = _majority(rows, source, representative)
            if value:
                location[target] = value

        external: dict[str, set[str]] = defaultdict(set)
        for row in external_rows:
            external[row["namespace"]].add(row["external_id"])
        external_ids = {key: sorted(values)[0] if len(values) == 1 else sorted(values) for key, values in sorted(external.items())}
        tag_values = sorted({tags[item["tag_id"]] for record_id in member_ids for item in tables["poi_tags"].get(record_id, [])})
        link_values = []
        seen_links = set()
        for record_id in member_ids:
            for item in tables["links"].get(record_id, []):
                marker = (item["link_type"], item["url"])
                if marker not in seen_links:
                    seen_links.add(marker)
                    link_values.append({"type": item["link_type"], "url": item["url"], "title": item["title"]})
        link_values.sort(key=lambda item: (item["type"], item["url"]))

        media_by_url: dict[str, dict[str, Any]] = {}
        for record_id in member_ids:
            for image in tables["images"].get(record_id, []):
                item = _media_item(image, conflicting_image_urls)
                previous = media_by_url.get(item["url"])
                rank = {"verified-permissive": 3, "declared": 2, "unknown": 1, "conflicting": 0}
                if previous is None or rank[item["rightsStatus"]] > rank[previous["rightsStatus"]]:
                    media_by_url[item["url"]] = item
        detailed_media = [media_by_url[url] for url in sorted(media_by_url)]
        safe_media = [item for item in detailed_media if item["rightsStatus"] == "verified-permissive"]
        rating_rows = [item for record_id in member_ids for item in tables["ratings"].get(record_id, [])]
        detailed_ratings = _best_ratings(rating_rows, rating_status)
        safe_ratings = [item for item in detailed_ratings if item["verificationStatus"] == "verified-source"]
        description = representative["description"] or None
        base = {
            "id": canonical_id,
            "name": representative["name"],
            "alternateNames": sorted(names, key=lambda value: (value.casefold(), value)),
            "category": _majority(rows, "category", representative) or "other",
            "subcategory": _majority(rows, "subcategory", representative),
            "description": description,
            "tags": tag_values,
            "location": location,
            "externalIds": external_ids,
            "links": link_values,
            "provenance": {
                "sourceRecords": [
                    {"agent": row["agent_name"], "recordId": row["original_poi_id"]}
                    for row in sorted(rows, key=lambda value: (value["agent_name"], value["original_poi_id"]))
                ],
                "mergeMethod": "cross-agent-canonical" if len(rows) > 1 else "single-record",
                "coordinateMethod": "median",
                "categoryMethod": "majority-with-representative-tiebreak",
            },
        }
        detailed = {**base, "ratings": detailed_ratings, "media": detailed_media}
        safe = {**base, "ratings": safe_ratings, "media": safe_media}
        detailed_pois.append(detailed)
        safe_pois.append(safe)

    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    submission_metadata = connection.execute(
        "SELECT region_name, language FROM submissions ORDER BY id"
    ).fetchall()
    destinations = [row["region_name"] for row in submission_metadata if row["region_name"]]
    languages = [row["language"] for row in submission_metadata if row["language"]]
    destination_id = Counter(destinations).most_common(1)[0][0] if destinations else None
    language = Counter(languages).most_common(1)[0][0] if languages else None
    common_metadata = {
        "schemaVersion": "1.0",
        "generatedAt": generated_at,
        "datasetVersion": dataset_version,
        "destinationId": destination_id,
        "language": language,
        "licensePolicyVersion": "1.0",
    }
    safe = {"metadata": {**common_metadata, "exportProfile": "safe"}, "pois": safe_pois}
    detailed = {"metadata": {**common_metadata, "exportProfile": "detailed"}, "pois": detailed_pois}
    audit = {
        "generatedAt": generated_at,
        "datasetVersion": dataset_version,
        "counts": {
            "sourceRecords": sum(len(rows) for rows in groups.values()),
            "sourceEntities": len(groups),
            "excludedAmbiguousEntities": len(ambiguous),
            "excludedHighConflictEntities": len(high_conflicts),
            "excludedUniqueEntities": len({item["entity"] for item in exclusions}),
            "exportedEntities": len(detailed_pois),
            "detailedMedia": sum(len(item["media"]) for item in detailed_pois),
            "safeMedia": sum(len(item["media"]) for item in safe_pois),
            "detailedRatings": sum(len(item["ratings"]) for item in detailed_pois),
            "safeRatings": sum(len(item["ratings"]) for item in safe_pois),
        },
        "mediaRights": dict(sorted(Counter(media["rightsStatus"] for poi in detailed_pois for media in poi["media"]).items())),
        "mediaLicenses": dict(
            sorted(
                Counter(
                    media["license"]["normalized"] or "unknown"
                    for poi in detailed_pois
                    for media in poi["media"]
                ).items()
            )
        ),
        "ratingVerification": dict(sorted(Counter(rating["verificationStatus"] for poi in detailed_pois for rating in poi["ratings"]).items())),
        "categoryCounts": dict(sorted(Counter(poi["category"] for poi in detailed_pois).items())),
        "exclusions": exclusions,
    }
    return safe, detailed, audit


def write_canonical_exports(
    connection: sqlite3.Connection,
    safe_output: str | Path,
    detailed_output: str | Path,
    audit_output: str | Path,
    dataset_version: str = "canonical-v1",
) -> dict[str, Any]:
    safe, detailed, audit = build_canonical_datasets(connection, dataset_version)
    for path, value in ((Path(safe_output), safe), (Path(detailed_output), detailed), (Path(audit_output), audit)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit["counts"]
