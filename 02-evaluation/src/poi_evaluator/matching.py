from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any


RELATIONS = {"same_place", "part_of", "contains", "related", "different_place", "uncertain"}


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_008.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    value = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _candidate_pairs(
    connection: sqlite3.Connection,
    exact_distance_m: float,
    fuzzy_distance_m: float,
    fuzzy_threshold: float,
) -> dict[tuple[int, int], dict[str, Any]]:
    candidates: dict[tuple[int, int], dict[str, Any]] = {}

    external_rows = connection.execute(
        """
        SELECT a.poi_record_id AS left_id, b.poi_record_id AS right_id,
               a.namespace, a.external_id
        FROM external_identifiers a
        JOIN external_identifiers b
          ON a.namespace=b.namespace AND a.external_id=b.external_id
         AND a.poi_record_id < b.poi_record_id
        JOIN poi_records pa ON pa.id=a.poi_record_id
        JOIN poi_records pb ON pb.id=b.poi_record_id
        WHERE pa.submission_id <> pb.submission_id
        """
    ).fetchall()
    for row in external_rows:
        key = (row["left_id"], row["right_id"])
        data = candidates.setdefault(key, {"reasons": [], "external": False})
        data["external"] = True
        data["reasons"].append(f"external_id:{row['namespace']}:{row['external_id']}")

    exact_rows = connection.execute(
        """
        SELECT a.id AS left_id, b.id AS right_id,
               a.normalized_name AS left_name, b.normalized_name AS right_name,
               a.latitude AS left_lat, a.longitude AS left_lon,
               b.latitude AS right_lat, b.longitude AS right_lon
        FROM poi_records a
        JOIN poi_records b
          ON a.normalized_name=b.normalized_name AND a.id < b.id
        WHERE a.submission_id <> b.submission_id AND a.normalized_name <> ''
        """
    ).fetchall()
    for row in exact_rows:
        key = (row["left_id"], row["right_id"])
        data = candidates.setdefault(key, {"reasons": [], "external": False})
        data["exact_name"] = True
        data["reasons"].append("normalized_name_exact")
        _add_distance(data, row)

    # A broad SQL bounding box prevents an O(n²) comparison while leaving the
    # exact haversine threshold to Python.
    latitude_window = fuzzy_distance_m / 110_574.0
    longitude_window = fuzzy_distance_m / 60_000.0
    nearby_rows = connection.execute(
        """
        SELECT a.id AS left_id, b.id AS right_id,
               a.normalized_name AS left_name, b.normalized_name AS right_name,
               a.latitude AS left_lat, a.longitude AS left_lon,
               b.latitude AS right_lat, b.longitude AS right_lon
        FROM poi_records a
        JOIN poi_records b
          ON a.id < b.id AND a.submission_id <> b.submission_id
         AND ABS(a.latitude-b.latitude) <= ?
         AND ABS(a.longitude-b.longitude) <= ?
        WHERE a.latitude IS NOT NULL AND a.longitude IS NOT NULL
          AND b.latitude IS NOT NULL AND b.longitude IS NOT NULL
          AND a.normalized_name <> b.normalized_name
        """,
        (latitude_window, longitude_window),
    ).fetchall()
    for row in nearby_rows:
        distance = haversine_m(row["left_lat"], row["left_lon"], row["right_lat"], row["right_lon"])
        if distance > fuzzy_distance_m:
            continue
        similarity = SequenceMatcher(None, row["left_name"], row["right_name"]).ratio()
        if similarity < fuzzy_threshold:
            continue
        key = (row["left_id"], row["right_id"])
        data = candidates.setdefault(key, {"reasons": [], "external": False})
        data.update({"distance_m": distance, "name_similarity": similarity, "fuzzy_name": True})
        data["reasons"].append("fuzzy_name_and_geo")

    for data in candidates.values():
        if "distance_m" not in data:
            data["distance_m"] = None
        if "name_similarity" not in data:
            data["name_similarity"] = 1.0 if data.get("exact_name") else None
        if data.get("external"):
            data.update(relation="same_place", status="auto_accepted", confidence=0.99)
        elif data.get("exact_name") and data["distance_m"] is not None and data["distance_m"] <= exact_distance_m:
            data.update(relation="same_place", status="auto_accepted", confidence=0.96)
            data["reasons"].append("within_exact_distance")
        elif data.get("exact_name"):
            data.update(relation="uncertain", status="candidate", confidence=0.72)
            data["reasons"].append("missing_or_distant_coordinates")
        else:
            similarity = float(data["name_similarity"] or 0)
            distance_factor = max(0.0, 1.0 - float(data["distance_m"] or 0) / fuzzy_distance_m)
            confidence = min(0.94, 0.55 + 0.25 * similarity + 0.14 * distance_factor)
            data.update(relation="uncertain", status="candidate", confidence=confidence)
    return candidates


def _add_distance(data: dict[str, Any], row: sqlite3.Row) -> None:
    coords = (row["left_lat"], row["left_lon"], row["right_lat"], row["right_lon"])
    if all(value is not None for value in coords):
        data["distance_m"] = haversine_m(*coords)


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def find(self, value: int) -> int:
        self.parent.setdefault(value, value)
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def _assign_canonical(connection: sqlite3.Connection) -> int:
    union_find = _UnionFind()
    rows = connection.execute(
        "SELECT left_poi_record_id, right_poi_record_id FROM matches "
        "WHERE relation='same_place' AND status IN ('auto_accepted', 'confirmed')"
    ).fetchall()
    for row in rows:
        union_find.union(row[0], row[1])
    groups: dict[int, list[int]] = defaultdict(list)
    for poi_id in union_find.parent:
        groups[union_find.find(poi_id)].append(poi_id)

    created = 0
    for members in groups.values():
        placeholders = ",".join("?" for _ in members)
        existing = connection.execute(
            f"SELECT DISTINCT canonical_poi_id FROM poi_records WHERE id IN ({placeholders}) AND canonical_poi_id IS NOT NULL",
            members,
        ).fetchall()
        canonical_ids = sorted(row[0] for row in existing)
        if canonical_ids:
            canonical_id = canonical_ids[0]
            for obsolete in canonical_ids[1:]:
                connection.execute("UPDATE poi_records SET canonical_poi_id=? WHERE canonical_poi_id=?", (canonical_id, obsolete))
                connection.execute("DELETE FROM canonical_pois WHERE id=?", (obsolete,))
        else:
            representative = connection.execute(
                f"SELECT name, normalized_name, latitude, longitude, region FROM poi_records WHERE id IN ({placeholders}) ORDER BY LENGTH(description) DESC, id LIMIT 1",
                members,
            ).fetchone()
            cursor = connection.execute(
                "INSERT INTO canonical_pois(canonical_name, normalized_name, latitude, longitude, region_name) VALUES (?, ?, ?, ?, ?)",
                tuple(representative),
            )
            canonical_id = int(cursor.lastrowid)
            created += 1
        connection.execute(
            f"UPDATE poi_records SET canonical_poi_id=? WHERE id IN ({placeholders})",
            (canonical_id, *members),
        )
    return created


def _queue_uncertain(connection: sqlite3.Connection, run_id: int) -> int:
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO review_queue(
            evaluation_run_id, item_type, entity_type, entity_id, priority,
            reason_code, payload_json
        )
        SELECT ?, 'identity_match', 'match', id,
               CAST(50 + confidence * 30 AS INTEGER), 'uncertain_identity',
               json_object(
                   'left_poi_record_id', left_poi_record_id,
                   'right_poi_record_id', right_poi_record_id,
                   'confidence', confidence,
                   'distance_m', distance_m,
                   'name_similarity', name_similarity,
                   'reasons', json(reasons_json)
               )
        FROM matches
        WHERE relation='uncertain' AND status='candidate'
        """,
        (run_id,),
    )
    return cursor.rowcount


def _detect_conflicts(connection: sqlite3.Connection, run_id: int) -> int:
    rows = connection.execute(
        """
        SELECT a.canonical_poi_id, a.id AS left_id, b.id AS right_id,
               a.category AS left_category, b.category AS right_category,
               a.subcategory AS left_subcategory, b.subcategory AS right_subcategory,
               a.latitude AS left_lat, a.longitude AS left_lon,
               b.latitude AS right_lat, b.longitude AS right_lon
        FROM poi_records a
        JOIN poi_records b
          ON a.canonical_poi_id=b.canonical_poi_id AND a.id < b.id
        WHERE a.canonical_poi_id IS NOT NULL AND a.submission_id <> b.submission_id
        """
    ).fetchall()
    created = 0
    for row in rows:
        findings: list[tuple[str, str, object, object, str]] = []
        for field in ("category", "subcategory"):
            left, right = row[f"left_{field}"], row[f"right_{field}"]
            if left and right and str(left).casefold() != str(right).casefold():
                findings.append((field, "value_mismatch", left, right, "medium"))
        coords = (row["left_lat"], row["left_lon"], row["right_lat"], row["right_lon"])
        if all(value is not None for value in coords):
            distance = haversine_m(*coords)
            if distance > 100:
                findings.append(
                    (
                        "coordinates",
                        "distance_mismatch",
                        {"latitude": row["left_lat"], "longitude": row["left_lon"]},
                        {"latitude": row["right_lat"], "longitude": row["right_lon"], "distance_m": distance},
                        "high" if distance > 1000 else "medium",
                    )
                )
        for field, conflict_type, left_value, right_value, severity in findings:
            existing = connection.execute(
                "SELECT id FROM conflicts WHERE left_poi_record_id=? AND right_poi_record_id=? "
                "AND field_name=? AND conflict_type=? AND status='open'",
                (row["left_id"], row["right_id"], field, conflict_type),
            ).fetchone()
            if existing:
                continue
            cursor = connection.execute(
                "INSERT INTO conflicts(canonical_poi_id, left_poi_record_id, right_poi_record_id, field_name, conflict_type, left_value_json, right_value_json, severity) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["canonical_poi_id"],
                    row["left_id"],
                    row["right_id"],
                    field,
                    conflict_type,
                    json.dumps(left_value, ensure_ascii=False),
                    json.dumps(right_value, ensure_ascii=False),
                    severity,
                ),
            )
            conflict_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT OR IGNORE INTO review_queue(evaluation_run_id, item_type, entity_type, entity_id, priority, reason_code, payload_json) VALUES (?, 'data_conflict', 'conflict', ?, ?, ?, ?)",
                (
                    run_id,
                    conflict_id,
                    85 if severity == "high" else 65,
                    conflict_type,
                    json.dumps({"field": field, "left": left_value, "right": right_value}, ensure_ascii=False),
                ),
            )
            created += 1
    return created


def match_candidates(
    connection: sqlite3.Connection,
    run_id: int,
    exact_distance_m: float = 75.0,
    fuzzy_distance_m: float = 250.0,
    fuzzy_threshold: float = 0.86,
) -> dict[str, int]:
    candidates = _candidate_pairs(connection, exact_distance_m, fuzzy_distance_m, fuzzy_threshold)
    auto_accepted = 0
    uncertain = 0
    for (left_id, right_id), data in candidates.items():
        connection.execute(
            """
            INSERT INTO matches(
                evaluation_run_id, left_poi_record_id, right_poi_record_id,
                relation, status, confidence, distance_m, name_similarity, reasons_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(left_poi_record_id, right_poi_record_id) DO UPDATE SET
                evaluation_run_id=excluded.evaluation_run_id,
                relation=CASE WHEN matches.status IN ('confirmed','rejected') THEN matches.relation ELSE excluded.relation END,
                status=CASE WHEN matches.status IN ('confirmed','rejected') THEN matches.status ELSE excluded.status END,
                confidence=excluded.confidence,
                distance_m=excluded.distance_m,
                name_similarity=excluded.name_similarity,
                reasons_json=excluded.reasons_json
            """,
            (
                run_id,
                left_id,
                right_id,
                data["relation"],
                data["status"],
                data["confidence"],
                data["distance_m"],
                data["name_similarity"],
                json.dumps(data["reasons"], ensure_ascii=False),
            ),
        )
        auto_accepted += data["status"] == "auto_accepted"
        uncertain += data["relation"] == "uncertain"
    canonical_created = _assign_canonical(connection)
    conflicts_created = _detect_conflicts(connection, run_id)
    queued = _queue_uncertain(connection, run_id)
    connection.commit()
    return {
        "candidate_pairs": len(candidates),
        "auto_accepted": auto_accepted,
        "uncertain": uncertain,
        "canonical_created": canonical_created,
        "conflicts_created": conflicts_created,
        "review_items_created": queued,
    }


def resolve_match(
    connection: sqlite3.Connection, match_id: int, relation: str, decided_by: str
) -> None:
    if relation not in RELATIONS:
        raise ValueError(f"Unknown relation: {relation}")
    cursor = connection.execute(
        "UPDATE matches SET relation=?, status='confirmed', decided_by=?, decided_at=CURRENT_TIMESTAMP WHERE id=?",
        (relation, decided_by, match_id),
    )
    if cursor.rowcount != 1:
        raise ValueError(f"Match {match_id} does not exist")
    connection.execute(
        "UPDATE review_queue SET status='resolved', resolved_at=CURRENT_TIMESTAMP, "
        "resolution_json=? WHERE entity_type='match' AND entity_id=? AND status IN ('pending','in_review')",
        (json.dumps({"relation": relation, "decided_by": decided_by}), match_id),
    )
    if relation == "same_place":
        _assign_canonical(connection)
    connection.commit()
