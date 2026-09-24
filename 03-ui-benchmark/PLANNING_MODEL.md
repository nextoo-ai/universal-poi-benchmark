# Travel Planning Model

This document clarifies the required planning concepts without prescribing a UI or
storage implementation.

## Immutable source layer

Imported POI files form the source layer. Their individual records are read-only:
product actions never rename, rewrite, move, create, or directly delete source POIs.
The source collection itself has a lifecycle: the user can load another file, the
product can merge or replace according to its declared behavior, and the user can
delete the active dataset.

## User overlay layer

The user creates a separate overlay containing:

- hidden POI IDs;
- active filters and search state;
- trip arrival and departure date/time, or a simple day count;
- the timezone selected or inferred for the trip;
- daily plan entries referencing source POI IDs;
- visit order and expected duration in minutes;
- an optional stay or daily-base location;
- optional personal notes if the design benefits from them.

Removing an item from the itinerary does not hide or delete the POI. Hiding a POI
removes it from the active discovery view but does not silently remove an already
scheduled visit; the interface should make that relationship understandable.

Loading or deleting a dataset may invalidate itinerary references. The interface
must resolve this visibly rather than silently reassigning a plan item to another POI.
Merged datasets should retain source provenance when that information is necessary
to explain duplicates or allow source-level deletion.

## Time behavior

Exact arrival and departure times define partial first and last days. A visit has an
expected duration and may optionally have a chosen start time. The interface should
help users notice impossible or crowded days while avoiding false precision when
travel times are unavailable.

## Stay or base behavior

A stay can reference an accommodation POI when the imported data provides one. When
it does not, the design may support a temporary map point, address label, or neutral
“not set” state. This is user planning data and must not be written back as a source
POI.

## Geographic behavior

The experience begins in Rome only when no dataset exists. After import, all map
bounds, destination summaries, distance cues, and planning views derive from the
loaded coordinates. Country-scale inputs such as Slovakia are valid and should not
be treated as malformed city datasets.
