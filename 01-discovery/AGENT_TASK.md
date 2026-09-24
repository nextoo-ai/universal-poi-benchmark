# Benchmark task — Universal POI Discovery, Rome v1

You are an autonomous research-and-data-curation agent. **Do not build a website or UI.** Produce a structured, independently verifiable POI dataset for the destination in `destination.json`, using the exact supplied JSON contract and taxonomy.

## Authoritative inputs

1. `poi.schema.json` — field types and required fields.
2. `taxonomy.json` — closed list of category, subcategory and tag IDs.
3. `destination.json` — geographical scope and destination context.
4. `benchmark.config.json` — count thresholds and benchmark-specific rules.

Do not reinterpret Rome-specific quotas as a universal property of the schema. Do not edit the supplied inputs during a scored run. A new destination requires a newly versioned profile and benchmark configuration, **not** changes to the POI contract.

## Scope and completeness

- Find **at least 500 unique, real POIs** in the configured Rome geography, not fictional or filler places.
- At least **80 gastronomy** and **150 culture** POIs; at least **80 POIs tagged `hidden_gem`**, distributed across at least three primary categories. Hidden gems are not a category or a boolean field.
- At least 8 populated subcategories each for gastronomy and culture; meaningful representation of urban, nature, local experiences, and transport where available.
- Represent Metro **A, B, B1 and C**, and at least two meaningful major transport hubs. `transit.lines` is structured data, not just tags.
- Include well-known sites and useful less-obvious alternatives; do not inflate the count by making many entries for a single entity.
- A historic building, its independently visitable museum and its separate chapel may be separate POIs only if supported as independently meaningful entities.

## Gastro acceptance

- Every gastronomic **business** other than `food_market` requires an observed Google Maps rating **≥ 4.0/5**.
- Store the exact score, review count, date verified and a **direct place URL** in `ratings.google`. This is a snapshot, not a live promise; never generate approximate, inferred or editorial scores.
- There is **no minimum review count**; low review counts remain visible for later quality assessment.
- A non-business public food market may have `ratings.google: null` if no meaningful establishment-wide Google rating exists.
- Do not substitute another platform's rating for a Google rating. If verified Google rating is unavailable for a business, exclude it rather than fabricate the value.
- If Google access is blocked or inconsistent, document the limitation and submit an honestly incomplete dataset rather than inventing ratings.

## Mandatory links and image metadata — every POI

- `links.reference`: an actual page about that specific place (official page preferred, otherwise reliable specific article or listing).
- `links.googleMaps`: a **direct link to the exact Google Maps place**, not a generic search-result URL. Verify the resolved identity where possible.
- `links.official`: official site if found; otherwise `null`.
- `links.googleImages`: optional Google Images query link; it **does not substitute** for Google Maps or the direct image URL.
- `media.primaryImage.url`: a **direct URL to an actual image asset depicting that POI**.
- `media.primaryImage.sourcePageUrl`: the human-readable page where the asset was found.
- `media.primaryImage.license`: exact verified license identifier/text or literal `"unknown"`.
- `licenseUrl`, `creator`, `attribution`: record when known, otherwise `null`. Never guess licensing or an author.
- The Discovery agent **records** rights metadata; the downstream Explorer decides whether/how to display or replace the image. Do not claim `unknown` authorizes reuse.
- If an image or reference cannot be found, disclose the shortfall; do **not** fabricate URLs. A submission missing a required image fails the current benchmark but is preferable to invented data.

## Quality, taxonomy, and evidence

- Each POI has exactly one primary category and subcategory; additional discovery facets go into tags from the provided taxonomy.
- Each POI must have an intelligible factual description (40–500 chars) and 1–4 specific highlights.
- A `hidden_gem` tag requires a place-specific explanation in `tagRationales.hidden_gem` and evidence supporting the reason. Do not claim a place is uncrowded or popular among locals without a source.
- Assign artist tags and `relatedPeople` only where there is a documented relationship to a specific place or artwork.
- Use `null` for unknown optional values, not false, zero or an invented default.
- Every POI must cite source-register entries in `evidence`, covering **identity** and **location** at minimum; `hidden_gem` also requires `hidden_gem_reason`. Register a relevant source for image evidence when possible.
- Latitude/longitude must denote the actual location, suitable entrance or clearly labelled approximate point in WGS84. A coarse bounding box check is **not** evidence that the point is correct.
- Do not copy large amounts of copyrighted source text; write brief original descriptions grounded in sources.
- External links and numeric rating metadata must respect the source's terms in downstream use. The Discovery agent should not download or redistribute photographs without permission.

## Deliverables

1. `pois.json`: a complete object matching `poi.schema.json`, including identical taxonomy arrays, source register and POI records. Do not hardcode generated timestamp values from examples.
2. `discovery-report.json`: counts, provenance coverage, unverifiable claims, reported sources and limitations, plus automated validation result and manual-audit summary if conducted.
3. `README.md`: concise data collection methodology, setup/validation command, sources, assumptions and unresolved gaps. This is the **agent submission README**, distinct from the benchmark package README.

Use the supplied offline validator:

```bash
python tools/validate.py pois.json --report discovery-report.json
```

Run the validator before submission. Any failed check must be disclosed. The validator checks structure, configured counts, some consistency and presence of evidence; it **cannot** establish existence, photographic identity, coordinates accuracy, working links, license correctness or truth of descriptions. These require manual/sample-based audit.

## Priority

Real, traceable information > meeting a numeric target by fabrication. A technically schema-valid file with fake POIs is a failed benchmark.
