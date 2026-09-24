# Product Contract

This contract defines what every submission must do while preserving broad design
freedom. It is not an evaluation rubric.

## Required states

### 1. Empty first run

The app loads without POI data and shows an empty Rome map. This is the fallback for
the “All roads lead to Rome” empty-state idea, not a destination constraint. No POI
from the development dataset may be discoverable in the page source, JavaScript
bundle, storage, caches, or network responses. The user immediately understands that
loading a file is the next action.

### 2. Import in progress

The interface acknowledges the selected file and communicates progress for a dataset
of at least 500 POIs. The UI remains responsive.

### 3. Successful import

The interface communicates the accepted POI count. It derives the actual map extent
from the imported coordinates and leaves Rome when the dataset describes another
place or region. Valid POIs become explorable through the product's chosen map and
browsing model.

### 4. Partial import

If some rows are invalid, the app reports accepted and rejected counts and gives a
human-readable reason or summary. Valid rows remain usable.

### 5. Failed import

Malformed JSON, an unsupported root structure, or a file with no valid POIs produces
a clear recoverable error and another opportunity to load a file. When a valid
dataset already exists, a failed later import leaves it intact.

### 6. Place inspection

Selecting a visible place reveals its available name, category, description, and
location context. Additional content is optional. Missing optional fields must not
leave broken or empty UI fragments.

### 7. Visibility and filtering

The user can filter the dataset and hide or restore individual POIs without changing
the source records. Hidden records are clearly distinguishable from filtered-out and
scheduled records.

### 8. Trip setup

The user can enter arrival and departure dates and times. The interface derives the
available trip days and handles partial first and last days. A number-of-days path is
an acceptable fallback when exact times are unknown.

### 9. Itinerary building

The user can assign POIs to days, order them, remove them from the plan without hiding
them, and set an expected visit duration. The plan makes unscheduled time and obvious
schedule pressure understandable without claiming unsupported route precision.

### 10. Stay or daily base

The experience provides a way to represent where the traveler stays or begins a day.
If the imported dataset has no accommodation category, the UI offers a clear neutral
fallback rather than inventing a hotel or mutating the POI dataset.

### 11. Additional dataset upload

The user can load another compatible file. The submission may merge it with existing
data, replace existing data, or offer both modes. The interface communicates the
chosen behavior before applying it. A merge defines how duplicate IDs and overlapping
records are handled.

### 12. Dataset deletion

A visible, deliberate action deletes the active dataset and returns the product to
the empty Rome state. If multiple source datasets are managed separately, the design
may additionally support deleting one source at a time. Dataset deletion must explain
what happens to itinerary items that reference removed POIs.

### 13. No direct POI editing

The application does not expose direct source-record editing. A user cannot rename,
move, rewrite, create, or delete an individual imported POI. Hiding a POI or removing
it from an itinerary is an overlay action and does not mutate the source record.

### 14. Optional media

The populated experience works when every POI has media, when some do, and when none
do. It can distinguish and filter records with and without media. Broken or omitted
media does not collapse the place-detail layout. When an image is shown, available
creator, attribution, source page, license, and rights status remain accessible.

### 15. Optional provider-neutral ratings

The experience distinguishes an absent rating from a numeric zero. It can filter POIs
that have ratings and POIs that do not. A displayed rating includes its provider and
original scale. Cross-provider ordering or filtering uses a normalized score only
after the scale has been declared or consistently detected.

## Required data behavior

- Required format: UTF-8 JSON matching `contracts/poi-upload.schema.json`.
- Required capacity: 500 POIs; recommended design capacity: 5,000 POIs.
- Geography: any city, region, country, or valid multi-region coordinate extent.
- Duplicate IDs: keep the first valid record and report subsequent duplicates, or
  reject the import with a clear explanation.
- Invalid coordinates: reject that record and report it.
- Unknown fields: preserve compatibility by ignoring or using them; do not reject a
  record solely because it is richer than the minimum schema.
- File processing: browser-local only.
- Dataset lifecycle: additional uploads are required. Merge, replacement, or a user
  choice between them is a product-design decision.
- Dataset deletion: required and must restore the empty Rome state when no data remain.
- POI editing: source records remain read-only regardless of dataset lifecycle.
- Media and ratings: optional per POI; their absence is a supported state.
- Rating scale: explicit canonical scale is preferred. Legacy scale detection must be
  dataset-consistent and must not silently compare ambiguous values.
- POI persistence: optional. If implemented, dataset deletion must also clear the
  persisted copy.
- Plan persistence: optional but encouraged; keep it separate from source POI data.

## Distribution boundary

The final application may contain zero bundled POIs. A small bundled example is also
allowed when it is original, synthetic, image-free, and declared in the submission
manifest. It must never load automatically; the default view remains empty.

The supplied `fixtures/safe-demo.json` may be offered as a separate download or test
file. It may not be silently preloaded.

## Visual and product expectation

The application should feel finished rather than like a map component demonstration.
It needs a deliberate visual system, coherent empty and populated states, thoughtful
content density, responsive composition, precise copy, and purposeful interaction
feedback. The journey from upload through discovery to a credible daily plan should
remain understandable without instructions outside the product.
