# Step 3 — POI UI and UX Benchmark

This package defines the design phase that follows POI discovery and evaluation.
Every participating agent receives the same consolidated Rome dataset produced by
Step 2 and uses it to design and test a polished map application.

The benchmark is intentionally design-led. Visual quality and user experience will
account for at least 60% of the final evaluation. The exact scoring method is not
part of this version and will be designed after the application brief is stable.

Two data boundaries are fundamental:

1. The consolidated Step 2 dataset is private development input. It lets every
   agent work with realistic volume, categories, descriptions, links, and optional
   media fields.
2. The submitted application must not contain that dataset. It starts with an empty
   map centered on Rome and asks the user to load a compatible POI JSON file locally.
   Rome is a fallback and a playful reference to “All roads lead to Rome,” not the
   application's fixed destination.

This separation prevents the benchmark application from redistributing POI media.
The application may ignore media completely. If it supports media from a user-loaded
file, those resources remain the user's input and are not bundled with the product.

## Package contents

- `AGENT_TASK.md` — the brief given to every UI agent.
- `PRODUCT_CONTRACT.md` — required behavior and the boundary between requirements
  and design freedom.
- `PLANNING_MODEL.md` — immutable POI source and personal itinerary overlay concepts.
- `contracts/poi-upload.schema.json` — portable JSON upload format.
- `contracts/submission-manifest.schema.json` — declaration included with a result.
- `fixtures/safe-demo.json` — optional synthetic, image-free sample file. It is not
  preloaded by the application.
- `development-data/README.md` — placement and non-distribution rules for the merged
  Step 2 dataset.

JSON is the required v1 upload format. It works in a browser without a database
runtime, is inspectable by users, and matches the source format used in the previous
steps. SQLite import may be added by an agent, but it is not required. Imported POI
records are read-only, but the user can load another dataset. The product designer
may replace the active dataset, merge multiple datasets, or offer both choices. The
user works through filters, visibility controls, and a personal itinerary layer
rather than editing source POIs directly.

## Result expected from an agent

The result is a production-quality travel-planning web application, its source, a
runnable build, and a short README. The build must run successfully before any POI
file is loaded and adapt its map to any geography after import. No framework, map
library, visual system, or layout is prescribed.
