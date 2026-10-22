# Starter design decisions

This records the implementation choices made while translating the team's A2 model into runnable code. Update it when a business rule changes, with the affected code and tests.

## 1. Python desktop application

The team requested Python. Tkinter supplies a small desktop interface and SQLite supplies local persistence using the standard library. This avoids needing a web server or a separately managed database while the team implements the business workflow.

The runtime is one local desktop process. The interface calls an application facade, the facade coordinates domain operations, and storage receives a serialised snapshot. The domain model owns business state and validation. The UI collects inputs and presents results.

The intended dependency direction is UI to application, application to domain and storage boundaries, and storage to serialised data. UI callbacks should not directly assign lifecycle statuses or modify payment amounts. This keeps the same validation usable by the desktop interface, demonstration runner and tests.

## 2. Retain the ten A2 domain classes

The implementation keeps Customer, DeliveryRequest, Parcel, DeliveryQuote, StaffList, DeliveryStaff, AvailabilitySchedule, DeliveryAssignment, PaymentRecord and DeliveryStatistics. Statuses and quote decisions are enum values rather than separate lifecycle classes.

Supporting code is explicit:

- `DomainError` reports invalid input and disallowed business operations.
- `TariffPolicy` contains the sample calculation and route duration for team review.
- The application facade supplies identifiers and coordinates use cases, including creation, authorisation and saving.
- Serialisation converts domain objects to portable values and reconstructs shared references during loading.
- `SQLiteStore` handles atomic persistence and detects conflicting saved revisions.
- Tkinter windows and dialogs are interface components, not extra business entities.

These support classes and modules implement input, persistence and startup responsibilities outside the ten business entities.

## 3. Assignment and payment multiplicities

**A2 clarification:** a request retains zero or more assignments over time, with at most one active assignment. It has zero or one current payment record.

`DeliveryRequest.assignments` retains ended assignments. Allocation is permitted only for an Accepted request with no active assignment. Ending an assignment records its end time and outcome rather than deleting it. The allocated worker also retains the assignment identifier.

`DeliveryRequest.payment` holds the single payment outcome. A later failed delivery does not erase or replace it. Attempts to replace a pending record with different amounts are rejected. This resolves the inconsistent assignment and payment multiplicities in the earlier relationship table.

## 4. Staff registration belongs to the roster

**A2 clarification:** `StaffList.register()` creates the roster association. AvailabilitySchedule manages time coverage, not employee registration.

Workers retain their own schedules and assess their own eligibility. StaffList returns active workers who report sufficient coverage. Deactivation prevents new allocation but preserves the worker and their existing or historical assignments. The worker assigned to existing work can still report its outcome after deactivation, consistent with retaining unresolved work.

Schedules merge overlapping and adjacent coverage periods. The quote window must be fully covered. The starter retains the A2 rule that overlapping assignments do not automatically make a worker unavailable; vehicle capacity and route optimisation would need additional requirements.

## 5. Sample service area, tariff and quotation window

The business requirements do not specify a complete pricing or travel-time algorithm. `pricing.py` therefore makes the sample policy visible instead of hardcoding the example quotes as universal prices.

The configured demonstration suburbs and zones are:

- Central: Melbourne, Docklands, Southbank.
- North: Carlton, Brunswick.
- East: Richmond, Hawthorn.
- West: Footscray.
- South: St Kilda, South Yarra.

This is a deliberately limited service configuration. It does not establish coverage for all Greater Melbourne addresses. A request outside the configured area is rejected before quotation, with its rejection reason retained.

The request-entry refinement now stores complete pickup and destination address text separately from the existing `pickup` and `destination` suburb keys. `pickup_address` and `destination_address` are appended to DeliveryRequest's default fields so existing positional constructor calls retain their meaning. Address text is trimmed; a partial pair or non-text value is invalid. New requests through the application require both addresses. The existing suburb keys continue to drive coverage and pricing, so an address string is not accidentally used as a tariff-zone lookup.

`DeliveryRequest.update_addresses()` validates both values before changing either and permits corrections only while Requested. The application exposes that operation through **Edit addresses**. An issued quote therefore cannot silently keep its old amount and window after its delivery addresses change. Legacy Requested records can be repaired before quoting; their missing addresses are not guessed from suburb names.

The sample AUD amount is:

```text
10.00
+ 2.00 * parcel_count
+ 2.00 * sum(max(actual_kg, volume_cm3 / 5000) for each parcel)
+ (2.00 for the same zone, otherwise 5.00)
```

Decimal arithmetic is used and the final amount is rounded to cents. The policy is an implementation assumption for team agreement, not a researched courier rate or payment gateway result.

Estimated windows account for request age and roster availability. The policy applies a 15-minute lead time and 15-minute priority-rank increments, then selects a covering available worker window. Duration is 60 minutes within a zone and 90 minutes across zones. Issuing a quote does not create an assignment or reserve the worker. Allocation checks the selected worker's current eligibility again.

## 6. Payment exception authorisation precedes pickup

**A2 clarification:** the assumption requiring business authorisation takes precedence over the scenario text that previously allowed Picked Up before approval.

When all parcels pass collection checks, the request validates that the payment record concerns its own accepted quote. Matching payment permits Picked Up. A mismatch is retained as a pending record, while the request stays Allocated and the parcels stay Pending.

An office action must record both the authorising person's name and the reason. The allocated worker then confirms pickup again using the same retained payment. Authorisation alone never marks parcels collected. The application does not process a financial transaction or assume that an entered office name has been authenticated.

If the required parcels cannot be collected, the request becomes Failed pickup, its assignment ends and no payment record is created. The starter rejects a failed-pickup report that would discard an already pending payment outcome; that exception must first be resolved explicitly.

## 7. Pickup retry and failed-delivery history

Pickup retry is an explicit office action, permitted only after Failed pickup when there is no active assignment and no payment. It returns the request to Accepted, preserves the accepted quote and retains the ended assignment. A new allocation creates another assignment record.

Delivery reporting requires Picked Up, the active assignment and the correct reporting worker. Successful handover changes all collected parcels to Delivered, records the completion time and ends the assignment. Failed delivery requires a reason, ends the assignment, retains the payment and flags the collected parcels as Return required. This flag does not claim the parcels have physically reached the depot.

Collection and handover are all-or-nothing in this starter. Partial outcomes would need parcel-level event history and agreed aggregate request-status rules before implementation.

## 8. Restore the complete retained graph

**A2 clarification:** startup must restore retained historical records as well as current requests and staff. Active-only restoration would lose statistics and historical worker attribution.

Customer and worker registries provide shared identities. Restored requests refer to the same Customer objects, while assignments use retained staff identifiers. Serialisation checks these references and the identifiers stored by customers and workers. Historical assignments, failed outcomes, pending authorisations and payment records are preserved in the snapshot.

Statistics are derived from requests and assignments. There is no separate table copying completed-delivery counts. A delivered request counts once according to its completion date; former staff remain identifiable. Average minutes means elapsed request-creation-to-completion time, not road travel time.

## 9. Local snapshot persistence

`SQLiteStore` writes a single schema-versioned JSON application snapshot inside one SQLite row. Each complete save is transactional. Revision comparison prevents an application instance from silently overwriting a state saved by another instance after it loaded its own copy. A conflict is reported rather than silently choosing a winner.

New snapshots use schema 2 and include both address keys. The decoder and storage boundary continue to accept schema 1, restoring its unknown addresses as blank pairs while preserving lifecycle state, payments, assignments and shared customer identities. Schema 2 requires both keys and rejects invalid partial pairs. Loading an older file alone does not rewrite its snapshot or advance its revision; a successful later save writes schema 2. The older starter cannot read schema 2, so use a separate test database when comparing versions.

This design gives the starter a small persistence boundary and preserves the object graph. It does not provide a normalised relational schema, per-record concurrent editing, user permissions or a multi-user service.

## 10. Time and validation

All domain datetimes are naive local Melbourne values. Timezone-aware values are rejected to avoid mixing incompatible time representations. This is sufficient for the local demonstration scope but does not model multiple timezones or daylight-saving conversions.

Money is finite, nonnegative Decimal data with cent precision. Parcel dimensions and weight must be finite and positive. Contact fields, time order, object identities and transition preconditions are validated before permitted business state changes.

Draft parcel rows use the same validation before being added or replaced. **Edit selected parcel** supports correction without creating a saved request, and cancellation leaves the previous parcel unchanged. Removing a row affects only the unsaved request draft.

Tests exercise both successful paths and rejected actions, including history retention and authorisation. Hidden-window desktop tests check callbacks and widget state; visual layout and usability need separate inspection.

## Updating this record

For each agreed improvement, record:

1. The responsibility, invariant or scenario concerned.
2. The observed implementation issue.
3. The decision and reason.
4. The affected code and regression checks.
5. Any remaining technical limitation.

Keep this record consistent with implemented behaviour and test results.
