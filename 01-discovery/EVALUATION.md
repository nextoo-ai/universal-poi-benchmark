# Two-stage evaluation — Universal POI Discovery

## Stage 1 — deterministic checks (automated)

Run `python tools/validate.py pois.json --report discovery-report.json` and attach console exit status. Failures are not silently waived. Validator checks:

- JSON Schema and ISO-formatted timestamps, types, required fields, link URI syntax;
- supplied canonical taxonomy equality, category/subcategory relationship, tag vocabulary;
- counts: 500 unique IDs, gastronomy ≥80, culture ≥150, hidden gems ≥80, at least 8 populated subcategories in each of gastronomy and culture, hidden gems in ≥3 categories;
- Rome bounding **envelope** (not actual administrative boundary), destination/country association;
- existence and referential integrity of source and evidence IDs; identity/location evidence and hidden-gem-rationale evidence;
- Google rating metadata on gastronomic businesses other than food markets, score ≥4.0;
- direct image URL field, source page, license known or `unknown`;
- Metro A, B, B1, C and transit hub candidates;
- potential close-by same-name duplicates are warnings, not automatic deletions.

Do **not** reward only the raw POI count. All quotas are minimums, not permission to add low-confidence filler.

## Stage 2 — factual and visual audit (human or suitably equipped evaluator)

Sample across categories and prioritise suspicious patterns; record sample size and failures. Check:

1. Does the entity actually exist? Are same-entity duplicates present under translations or alternate coordinates?
2. Does the POI have meaningful independent identity and sit in the intended geographic area?
3. Are coordinates placed at the real entrance or feature (not a random centroid or nearby street)?
4. Does the reference page support identity, details and the stated hidden-gem rationale?
5. Does `googleMaps` lead to the **exact place**, and does its displayed rating/review count match the captured dated snapshot when reasonably auditable?
6. Is `media.primaryImage.url` a directly retrievable image depicting the correct POI, and is `sourcePageUrl` the actual provenance page?
7. Is `license` truthful? `unknown` is an honest observation, **not** permission to reuse the image. Confirm any attribution details reported.
8. Does the dataset represent different neighborhoods and meaningful subcategories, including non-obvious places, without trivial filler?
9. Do text descriptions and highlights contain factual, non-generic visitor-relevant details, and do related artist/person tags correspond to an actual documented connection?
10. Are transit lines and interchanges correct for the source snapshot date?

Report documented failures and uncertainty. Do not equate a missing public Google rating with a zero score. Screenshots, generated documentation and a valid JSON file do not on their own verify real-world data.

## Compare agents fairly

Use the **same frozen versions** of `poi.schema.json`, `taxonomy.json`, `destination.json`, `benchmark.config.json`, evaluation date window and audit methodology for all agents compared. Report factual validation separately from UI quality. A dataset with invented locations or invented ratings fails regardless of its visual appeal or item count.
