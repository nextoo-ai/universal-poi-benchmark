# Agent Task: Design a Premium POI Travel Planner

Design and implement a visually exceptional, production-quality travel application
for exploring and planning with user-provided POI data. This is primarily a product
design and UX benchmark. Craft, clarity, interaction quality, responsive behavior,
and a coherent visual point of view matter more than the number of features.

## Development input

You receive one consolidated Rome POI JSON file produced by a previous evaluation
step. Use the full dataset while designing and testing the experience. It represents
the scale and content richness the product must handle.

The development dataset is not redistributable application content. Do not copy,
embed, transform, cache, encode, or generate it into the final build, source tree,
service worker, screenshots, fixtures, or documentation.

## First-run experience

The final application must open successfully without POI data. Its initial state is:

- an empty map centered on Rome at approximately latitude `41.9028`, longitude
  `12.4964`;
- no POI markers, list entries, counts, cards, or hidden preloaded POI records;
- a prominent and inviting way to choose or drop a compatible JSON file;
- concise guidance that the file is processed locally in the browser;
- a tasteful use of the idea “All roads lead to Rome” in the empty experience;
- a graceful explanation of the expected format without making the interface feel
  like a developer tool.

Rome is only the no-data fallback. It must not remain the assumed destination after
import. A Barcelona, Miami, Slovakia, or multi-region dataset must move the experience
to its actual geographic extent. The map itself may use an external map provider.
Preserve the provider's required attribution. The application must not require an
account or API key from the user to reach its first-run state.

## Experience after import

Once a valid file is loaded, turn hundreds of POIs into a polished discovery and
trip-planning experience. The user should be able to understand what was loaded,
navigate its actual geography, find places, inspect a place, hide irrelevant POIs,
and build a realistic multi-day itinerary.

Imported POI records are read-only. Do not provide controls that directly rename,
rewrite, move, create, or delete individual source POIs. Hiding, filtering, selecting,
and scheduling a POI changes only the user's view or plan.

The user may load another compatible file after the first import. You may replace the
active dataset, merge multiple datasets, or let the user choose between those modes.
Make the behavior understandable before the action is committed. If you support
merging, handle duplicate IDs and preserve enough source identity to explain or undo
the merge coherently.

The required product capabilities are deliberately short:

- local JSON selection and drag-and-drop;
- clear loading, success, partial-success, empty, and error states;
- map markers or another appropriate spatial representation for all valid POIs;
- an effective way to browse or search a dataset containing at least 500 POIs;
- a useful place detail experience based on available text and metadata;
- filters and a reversible way to hide individual POIs from the working view;
- a clear way to load another dataset, with explicit merge or replacement behavior;
- a visible action to delete the active dataset and return to the empty Rome state;
- a trip setup flow based on arrival and departure date and time, with a simpler
  number-of-days option as a fallback;
- a multi-day plan in which the user can add POIs to a day, choose their order, and
  set or adjust expected time spent at each place;
- a way to choose where the traveler stays or uses as a base when the data supports
  it, with a clear fallback when no accommodation POI is present;
- a usable distinction between unscheduled, scheduled, and hidden POIs;
- responsive use on desktop and mobile;
- keyboard-accessible core actions and legible contrast.

Clustering, route visualization, travel-time estimation, schedule conflict warnings,
saved plans, category styling, transitions, onboarding, list-map coordination, and
other enhancements are design decisions. Add them when they make the experience
better. Avoid features that weaken the main flow or pretend to know travel times that
cannot be supported.

## Media and licensing boundary

The benchmark does not require photographs. The final build must contain no POI
images from the development dataset. You may choose any of these product directions:

- a strong image-free interface;
- support for image URLs present in a user-loaded file;
- a user preference that enables or disables remote images.

If the interface displays user-provided media, surface attribution and license fields
when present. Do not use third-party POI photography as decorative application
content.

## Data handling

The required JSON format is defined in `contracts/poi-upload.schema.json`. Accept
additional fields so the experience can use richer Step 2 records. At minimum, a
valid POI contains an ID, name, category, and WGS84 latitude/longitude.

Parse the file locally. Do not send the file, its contents, POI names, or derived data
to an application server, analytics product, logging service, or AI endpoint. Normal
map tile and map style requests are allowed.

Treat malformed rows as a product state, not as a crash. Explain what happened and
let the user retry. A failed replacement or merge must not damage the currently valid
dataset. The app may import valid rows from a partially invalid file if it reports
both the accepted and rejected counts.

Infer the imported geographic extent from valid coordinates. Use destination metadata
as a label when available, but never require the destination to be a city or assume
that all POIs fit within Rome or even within one municipality.

## Design freedom

Choose the framework, map renderer, architecture, typography, color system, motion,
information hierarchy, and interaction model. Do not imitate a supplied reference
application; there is none. The goal is to demonstrate a distinct, carefully made
product that people would enjoy using.

## Submission

Provide:

1. complete source code;
2. installation and run instructions;
3. a production build;
4. `submission-manifest.json`, valid against the supplied schema;
5. a short design rationale covering the main product decisions;
6. confirmation that the consolidated development dataset is absent from the result.

Do not include the consolidated Step 2 file in the submission archive or repository.
