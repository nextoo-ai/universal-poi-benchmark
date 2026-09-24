# Canonical POI v1 export

Step 2 will produce two JSON files from the same reviewed canonical entities. They
share one schema and differ through `metadata.exportProfile` and media inclusion
policy.

## `canonical-poi-v1.safe.json`

The safe profile is suitable for distribution with UI benchmark packages. It keeps
media as a first-class optional field, but includes a media item only when its license
and required attribution are sufficiently documented under the configured policy.
An empty `media` array means that the POI has no distributable media; it does not make
the POI invalid.

Every included media item has `rightsStatus: "verified-permissive"`, a source page,
a normalized license label, and the attribution fields required by that license.

## `canonical-poi-v1.detailed.json`

The detailed profile is intended for controlled development, audit, and later review.
It retains candidate media even when rights are declared, unknown, or conflicting.
It must never imply that `unknown` means reusable. Each media item exposes its rights
state and source metadata so downstream tools can make an explicit decision.

## Ratings

Ratings are provider-neutral and optional per POI. The canonical representation is an
array. Every rating declares:

- provider name;
- raw numeric value;
- minimum and maximum scale;
- normalized score from 0 to 1;
- how the scale was established;
- whether the rating has a verifiable source;
- optional review count, observation date, and source URL.

The exporter prefers an explicit source scale. A documented provider rule is second
choice. Dataset-level inference is allowed only when the observed range is internally
consistent and the decision is recorded as `dataset-inferred`.

The normalized value is:

```text
(value - scale.min) / (scale.max - scale.min)
```

Ratings from different providers may be filtered through the normalized value, while
the UI still displays the original value and scale. Missing ratings remain an empty
array and are never converted into zero.

The safe profile includes only ratings with `verificationStatus: "verified-source"`.
The detailed profile can retain `source-unavailable` and `unverified` values so they
remain auditable without being presented as equally trustworthy.

In the current Rome database all 3,244 imported rating records use the provider label
`google` and range from 2.2 to 5.0. Their stored records do not declare a scale, so a
documented provider rule would normalize them to 0–5. Only 1,029 currently carry a
source URL; this distinction must be preserved during export.

## Required review before export

- no unresolved identity relation may silently collapse two POIs;
- canonical field selection must be auditable;
- media rights status must follow a versioned allowlist policy;
- rating scale and normalization must be explicit;
- broken required links must be removed or replaced;
- the export report must count omitted media and every exclusion reason.
