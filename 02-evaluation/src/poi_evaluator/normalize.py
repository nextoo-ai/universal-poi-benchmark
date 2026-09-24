from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Iterable


_SPACE = re.compile(r"\s+")


def normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    characters: list[str] = []
    previous_was_latin = False
    for char in decomposed:
        if unicodedata.combining(char):
            if not previous_was_latin:
                characters.append(char)
            continue
        characters.append(char)
        previous_was_latin = "LATIN" in unicodedata.name(char, "")
    value = unicodedata.normalize("NFC", "".join(characters))
    value = value.casefold().replace("&", " and ")
    # Keep letters and digits from every script so matching remains useful for
    # cities whose names are not written in Latin characters.
    value = "".join(char if char.isalnum() else " " for char in value)
    return _SPACE.sub(" ", value).strip()


def normalize_tag(value: str) -> str:
    return normalize_name(value).replace(" ", "_").strip("_")


def as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _SPACE.sub(" ", value).strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, dict):
        candidate = first_present(value, ("name", "label", "slug", "value", "formatted"))
        if candidate is not None and candidate is not value:
            return as_text(candidate)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def first_present(data: dict[str, Any], paths: Iterable[str]) -> Any:
    for path in paths:
        current: Any = data
        for key in path.split("."):
            if not isinstance(current, dict) or key not in current:
                current = None
                break
            current = current[key]
        if current is not None and current != "":
            return current
    return None


def as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return None


def normalize_poi(raw: dict[str, Any], index: int) -> dict[str, Any]:
    original_id = first_present(raw, ("id", "poiId", "poi_id", "uuid", "slug"))
    name = first_present(raw, ("name", "title", "displayName", "display_name"))
    if not name or not isinstance(name, str):
        raise ValueError(f"POI at index {index} has no usable name")

    latitude = as_float(
        first_present(raw, ("latitude", "lat", "location.latitude", "location.lat", "coordinates.latitude", "coordinates.lat"))
    )
    longitude = as_float(
        first_present(raw, ("longitude", "lng", "lon", "location.longitude", "location.lng", "location.lon", "coordinates.longitude", "coordinates.lng", "coordinates.lon"))
    )
    if latitude is not None and not -90 <= latitude <= 90:
        raise ValueError(f"POI {original_id or index}: latitude is outside WGS84 bounds")
    if longitude is not None and not -180 <= longitude <= 180:
        raise ValueError(f"POI {original_id or index}: longitude is outside WGS84 bounds")

    normalized = {
        "original_poi_id": str(original_id) if original_id is not None else f"row-{index + 1}",
        "name": _SPACE.sub(" ", name).strip(),
        "normalized_name": normalize_name(name),
        "description": as_text(first_present(raw, ("description", "summary", "shortDescription", "short_description"))),
        "category": as_text(first_present(raw, ("category", "taxonomy.category", "primaryCategory"))),
        "subcategory": as_text(first_present(raw, ("subcategory", "subCategory", "taxonomy.subcategory", "primarySubcategory"))),
        "latitude": latitude,
        "longitude": longitude,
        "address": as_text(first_present(raw, ("address", "location.address", "address.formatted"))),
        "locality": as_text(first_present(raw, ("locality", "city", "location.city", "address.locality"))),
        "region": as_text(first_present(raw, ("region", "location.region", "address.region"))),
        "country_code": as_text(first_present(raw, ("countryCode", "country_code", "location.countryCode", "address.countryCode"))),
        "is_hidden_gem": as_bool(first_present(raw, ("isHiddenGem", "is_hidden_gem", "hiddenGem"))),
    }
    return normalized
