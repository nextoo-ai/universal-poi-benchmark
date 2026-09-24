# Media license audit — Rome submissions

Snapshot date: 2026-09-24. The SQLite evaluation database contains 3,244 primary
image records, one for every imported POI record.

## Normalized license labels

| Normalized license | Images |
|---|---:|
| Unknown | 1,854 |
| CC BY-SA 4.x | 715 |
| CC BY-SA 3.x | 280 |
| Public domain | 193 |
| CC BY 4.x | 86 |
| CC BY 2.x | 36 |
| CC BY 3.x | 27 |
| CC0 | 21 |
| CC BY-SA 2.x | 16 |
| CC BY-SA 2.5 | 5 |
| CC BY 2.5 | 5 |
| CC SA 1.0 | 2 |
| Attribution | 2 |
| GFDL | 1 |
| GPL | 1 |

The largest shared license group is **CC BY-SA 4.x with 715 images**. Across all
recognized Creative Commons labels there are 1,191 images. Another 193 are labelled
public domain.

## Metadata readiness

| Check | Images |
|---|---:|
| Known, non-`unknown` license label | 1,390 |
| Explicit `licenseUrl` | 734 |
| Source page URL | 3,244 |
| Creator value | 850 |
| Known license + license URL + required creator/public-domain exception | 716 |

These counts describe submitted metadata, not legal verification. License strings
can be wrong, source pages can change, and a reachable image is not proof that the
uploader owned the work. The safe export must use a documented allowlist, normalize
license variants, retain attribution, and report why each excluded media item failed.

Earlier URL checks were strongly affected by Wikimedia rate limiting. Reachability
must not be used as the sole license criterion, and rate-limited URLs must not be
classified as broken.
