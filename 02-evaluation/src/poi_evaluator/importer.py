from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .normalize import first_present, normalize_poi, normalize_tag


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _extract_pois(document: Any) -> list[dict[str, Any]]:
    if isinstance(document, list):
        items = document
    elif isinstance(document, dict):
        items = first_present(document, ("pois", "pointsOfInterest", "points_of_interest", "features"))
        if items is None:
            raise ValueError("Dataset must be a JSON array or contain pois[]")
    else:
        raise ValueError("Dataset root must be a JSON object or array")
    if not isinstance(items, list):
        raise ValueError("POI collection must be an array")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"POI at index {index} is not an object")
        result.append(item)
    return result


def _normalization_input(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("type") != "Feature" or not isinstance(raw.get("properties"), dict):
        return raw
    combined = dict(raw["properties"])
    geometry = _as_dict(raw.get("geometry"))
    coordinates = geometry.get("coordinates")
    if geometry.get("type") == "Point" and isinstance(coordinates, list) and len(coordinates) >= 2:
        combined.setdefault("longitude", coordinates[0])
        combined.setdefault("latitude", coordinates[1])
    return combined


def _metadata(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        return {}
    excluded = {"pois", "pointsOfInterest", "points_of_interest", "features"}
    return {key: value for key, value in document.items() if key not in excluded}


def _declared_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    nested = metadata.get("metadata")
    return nested if isinstance(nested, dict) else metadata


def _iter_external_ids(raw: dict[str, Any]) -> Iterable[tuple[str, str, Any]]:
    value = first_present(raw, ("externalIds", "external_ids", "identifiers"))
    if isinstance(value, dict):
        for namespace, external_id in value.items():
            if external_id not in (None, ""):
                yield str(namespace).casefold(), str(external_id), {namespace: external_id}
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                namespace = first_present(item, ("namespace", "provider", "type"))
                external_id = first_present(item, ("id", "value", "externalId"))
                if namespace and external_id:
                    yield str(namespace).casefold(), str(external_id), item


def _iter_links(raw: dict[str, Any]) -> Iterable[tuple[str, str, str | None, str | None, Any]]:
    known = {
        "website": ("website", "official"),
        "officialWebsite": ("officialWebsite", "official"),
        "official_website": ("official_website", "official"),
        "wikipediaUrl": ("wikipediaUrl", "reference"),
        "wikipedia_url": ("wikipedia_url", "reference"),
        "googleMapsUrl": ("googleMapsUrl", "map"),
        "google_maps_url": ("google_maps_url", "map"),
    }
    seen: set[tuple[str, str]] = set()
    for key, (_, link_type) in known.items():
        url = raw.get(key)
        if isinstance(url, str) and url:
            seen.add((link_type, url))
            yield link_type, url, None, None, {key: url}
    links = first_present(raw, ("links", "urls"))
    if isinstance(links, dict):
        links = [{"type": key, "url": value} for key, value in links.items()]
    for item in _as_list(links):
        if isinstance(item, str):
            parsed = ("reference", item, None, None, item)
        elif isinstance(item, dict):
            url = first_present(item, ("url", "href"))
            if not isinstance(url, str) or not url:
                continue
            parsed = (
                str(first_present(item, ("type", "kind", "rel")) or "reference"),
                url,
                first_present(item, ("title", "label")),
                first_present(item, ("sourceId", "source_id")),
                item,
            )
        else:
            continue
        if (parsed[0], parsed[1]) not in seen:
            seen.add((parsed[0], parsed[1]))
            yield parsed


def _insert_children(connection: sqlite3.Connection, poi_id: int, raw: dict[str, Any]) -> None:
    for namespace, external_id, original in _iter_external_ids(raw):
        connection.execute(
            "INSERT OR IGNORE INTO external_identifiers(poi_record_id, namespace, external_id, raw_json) VALUES (?, ?, ?, ?)",
            (poi_id, namespace, external_id, _json(original)),
        )

    for item in _as_list(raw.get("tags")):
        value = item.get("slug") or item.get("name") if isinstance(item, dict) else item
        if not isinstance(value, str) or not value.strip():
            continue
        slug = normalize_tag(value)
        if not slug:
            continue
        connection.execute("INSERT OR IGNORE INTO tags(slug, display_name) VALUES (?, ?)", (slug, value))
        tag_id = connection.execute("SELECT id FROM tags WHERE slug=?", (slug,)).fetchone()[0]
        connection.execute(
            "INSERT OR IGNORE INTO poi_tags(poi_record_id, tag_id, raw_value) VALUES (?, ?, ?)",
            (poi_id, tag_id, _json(item)),
        )

    for link_type, url, title, source_id, original in _iter_links(raw):
        connection.execute(
            "INSERT OR IGNORE INTO links(poi_record_id, link_type, url, title, source_id, raw_json) VALUES (?, ?, ?, ?, ?, ?)",
            (poi_id, link_type, url, title, source_id, _json(original)),
        )

    media = _as_dict(raw.get("media"))
    image_items: list[Any] = []
    image_items.extend(_as_list(raw.get("images")))
    image_items.extend(_as_list(raw.get("image")))
    image_items.extend(_as_list(media.get("images")))
    image_items.extend(_as_list(media.get("primaryImage")))
    seen_image_urls: set[str] = set()
    for item in image_items:
        if isinstance(item, str):
            image = {"url": item}
        elif isinstance(item, dict):
            image = item
        else:
            continue
        image_url = first_present(image, ("url", "imageUrl", "image_url", "src"))
        if not isinstance(image_url, str) or not image_url or image_url in seen_image_urls:
            continue
        seen_image_urls.add(image_url)
        connection.execute(
            "INSERT OR IGNORE INTO images(poi_record_id, image_url, page_url, caption, creator, license, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                poi_id,
                image_url,
                first_present(image, ("pageUrl", "page_url", "sourcePageUrl", "sourceUrl")),
                image.get("caption"),
                first_present(image, ("creator", "author")),
                first_present(image, ("license", "licenseName")),
                _json(item),
            ),
        )

    ratings = raw.get("ratings", raw.get("rating"))
    if isinstance(ratings, dict) and any(key in ratings for key in ("value", "rating", "score")):
        ratings = [ratings]
    elif isinstance(ratings, dict):
        ratings = [dict(value, provider=key) if isinstance(value, dict) else {"provider": key, "value": value} for key, value in ratings.items()]
    for item in _as_list(ratings):
        if not isinstance(item, dict):
            continue
        provider = str(first_present(item, ("provider", "source", "type")) or "unknown")
        connection.execute(
            "INSERT OR IGNORE INTO ratings(poi_record_id, provider, rating, rating_scale, review_count, observed_at, source_url, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                poi_id,
                provider,
                first_present(item, ("value", "rating", "score")),
                first_present(item, ("scale", "ratingScale", "max")),
                first_present(item, ("reviewCount", "review_count", "count")),
                first_present(item, ("observedAt", "observed_at", "date")),
                first_present(item, ("sourceUrl", "source_url", "url")),
                _json(item),
            ),
        )

    evidence_items = first_present(raw, ("evidence", "provenance.evidence"))
    for item in _as_list(evidence_items):
        if not isinstance(item, dict):
            continue
        connection.execute(
            "INSERT INTO evidence(poi_record_id, evidence_type, source_id, url, supports_json, quote, note, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                poi_id,
                str(first_present(item, ("type", "evidenceType", "kind")) or "source"),
                first_present(item, ("sourceId", "source_id")),
                item.get("url"),
                _json(item.get("supports", [])),
                item.get("quote"),
                item.get("note"),
                _json(item),
            ),
        )


def import_dataset(connection: sqlite3.Connection, path: str | Path, agent_name: str) -> dict[str, Any]:
    source_path = Path(path).resolve()
    raw_text = source_path.read_text(encoding="utf-8")
    document = json.loads(raw_text)
    pois = _extract_pois(document)
    metadata = _metadata(document)
    declared_metadata = _declared_metadata(metadata)
    digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

    connection.execute("SAVEPOINT import_dataset")
    try:
        cursor = connection.execute(
            "INSERT INTO submissions(agent_name, dataset_name, source_path, source_sha256, schema_version, dataset_version, language, region_name, raw_document_json, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                agent_name,
                declared_metadata.get("name") or declared_metadata.get("datasetName") or source_path.stem,
                str(source_path),
                digest,
                declared_metadata.get("schemaVersion"),
                declared_metadata.get("datasetVersion"),
                declared_metadata.get("language"),
                first_present(
                    declared_metadata,
                    ("region.name", "destination.name", "city", "regionName", "destinationId"),
                ),
                raw_text,
                _json(metadata),
            ),
        )
        submission_id = int(cursor.lastrowid)
        seen_ids: set[str] = set()
        for index, raw in enumerate(pois):
            importable = _normalization_input(raw)
            normalized = normalize_poi(importable, index)
            original_id = normalized["original_poi_id"]
            if original_id in seen_ids:
                raise ValueError(f"Duplicate POI id in submission: {original_id}")
            seen_ids.add(original_id)
            cursor = connection.execute(
                "INSERT INTO poi_records(submission_id, original_poi_id, name, normalized_name, description, category, subcategory, latitude, longitude, address, locality, region, country_code, is_hidden_gem, raw_json, normalized_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    submission_id,
                    original_id,
                    normalized["name"],
                    normalized["normalized_name"],
                    normalized["description"],
                    normalized["category"],
                    normalized["subcategory"],
                    normalized["latitude"],
                    normalized["longitude"],
                    normalized["address"],
                    normalized["locality"],
                    normalized["region"],
                    normalized["country_code"],
                    int(normalized["is_hidden_gem"]) if normalized["is_hidden_gem"] is not None else None,
                    _json(raw),
                    _json(normalized),
                ),
            )
            _insert_children(connection, int(cursor.lastrowid), importable)
        connection.execute("RELEASE SAVEPOINT import_dataset")
        connection.commit()
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT import_dataset")
        connection.execute("RELEASE SAVEPOINT import_dataset")
        raise
    return {"submission_id": submission_id, "poi_count": len(pois), "sha256": digest}
