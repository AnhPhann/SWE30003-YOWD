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

## 6. Payment exception authorisation precedes delivery

**Implementation refinement:** collection is recorded when the worker reports it. A payment mismatch is an unresolved business decision that blocks delivery, rather than concealing an already reported physical pickup. This changes the earlier approval-before-pickup timing.

When all parcels pass collection checks, the request validates the payment against its accepted quote, records Picked Up and collects all parcels. A mismatch remains unauthorised, preventing both successful and failed delivery reporting until an office decision is recorded.

An office action records both the authorising person's name and reason. New requests need no second pickup. The application records a simulated payment outcome; it does not process a bank transaction or authenticate an entered office name.

Older saved Allocated requests may already hold a payment while parcels are Pending. They load without invented collection or automatic migration. The office can authorise the retained payment, then the allocated worker confirms actual collection using its existing ID, amount and received time. An unapproved confirmation leaves the legacy request Allocated. A changed amount, replacement payment or wrong reporter is rejected.

If the required parcels cannot be collected, the request becomes Failed pickup, its assignment ends and no payment record is created. The starter rejects a failed-pickup report that would discard an already pending payment outcome; that exception must first be resolved explicitly.

## 7. Pickup retry and failed-delivery history

Pickup retry is an explicit office action, permitted only after Failed pickup when there is no active assignment and no payment. It returns the request to Accepted, preserves the accepted quote and retains the ended assignment. `DeliveryAssignment.outcome_details` preserves the specific failure reason and affected-parcel text after the current request reason is cleared. Known details from an older failed request are retained before retry; unknown older details are not invented. A new allocation creates another assignment record.

Delivery reporting requires Picked Up, the active assignment and the correct reporting worker. Successful handover changes all collected parcels to Delivered, records the completion time and ends the assignment. Failed delivery requires a reason, ends the assignment, retains the payment and flags the collected parcels as Return required. This flag does not claim the parcels have physically reached the depot.

Collection and handover are all-or-nothing in this starter. Partial outcomes would need parcel-level event history and agreed aggregate request-status rules before implementation.

## 8. Restore the complete retained graph

**A2 clarification:** startup must restore retained historical records as well as current requests and staff. Active-only restoration would lose statistics and historical worker attribution.

Customer and worker registries provide shared identities. Restored requests refer to the same Customer objects, while assignments use retained staff identifiers. Serialisation checks these references and the identifiers stored by customers and workers. Historical assignments, failed outcomes, pending authorisations and payment records are preserved in the snapshot.

Statistics are derived from requests and assignments. There is no separate table copying completed-delivery counts. A delivered request counts once according to its completion date; former staff remain identifiable. Average minutes means elapsed request-creation-to-completion time, not road travel time.

## 9. Local snapshot persistence

`SQLiteStore` writes a single schema-versioned JSON application snapshot inside one SQLite row. Each complete save is transactional. Revision comparison prevents an application instance from silently overwriting a state saved by another instance after it loaded its own copy. A conflict is reported rather than silently choosing a winner.

New snapshots use schema 3 and require assignment outcome details as text. Schemas 1 and 2 remain readable with unknown assignment details blank. Version 1 can also lack addresses; version 2 requires address keys. The loader preserves lifecycle states, payments, assignments and shared identities. Loading alone does not rewrite a snapshot or advance its revision; a successful later save writes schema 3. Older applications cannot read schema 3, so use a separate database when comparing versions.

This design gives the starter a small persistence boundary and preserves the object graph. It does not provide a normalised relational schema, per-record concurrent editing, user permissions or a multi-user service.

## 10. Time and validation

All domain datetimes are naive local Melbourne values. Timezone-aware values are rejected to avoid mixing incompatible time representations. This is sufficient for the local demonstration scope but does not model multiple timezones or daylight-saving conversions.

Money is finite, nonnegative Decimal data with cent precision. Parcel dimensions and weight must be finite and positive. Contact fields, time order, object identities and transition preconditions are validated before permitted business state changes.

Draft parcel rows use the same validation before being added or replaced. **Edit selected parcel** supports correction without creating a saved request, and cancellation leaves the previous parcel unchanged. Removing a row affects only the unsaved request draft.

Tests exercise both successful paths and rejected actions, including history retention and authorisation. Hidden-window desktop tests check callbacks and widget state; visual layout and usability need separate inspection.

## 11. Weekday operating hours and editable availability

**Proposal for team review.** A small Melbourne same-day courier normally dispatches on weekdays inside a fixed day shift. The working rule is Monday to Friday, 08:00 to 18:00, naive Melbourne local time. Saturday, Sunday, overnight periods and public-holiday calendars are out of this rule. Public holidays are a known gap: a real operation would add a holiday calendar later without changing the staff classes.

`AvailabilitySchedule` still only stores periods and answers whether a window is covered. It does not know the company calendar. `operating_hours.py` is the single policy. Registration, availability edits and quotation all call it. Allocation asks for the same quoted-window check, then asks the worker about employment and schedule coverage. Loading an older schedule does not delete periods that sit outside the new hours. The next edit must comply. No snapshot field was added, so schema 2 is unchanged.

The availability screen edits a draft. Add, replace, remove and clear change only that draft. Cancel discards it. Save replaces the stored periods and leaves existing assignments in place. The allocation screen lists every worker as Eligible or gives the refusal: wrong request status, an active assignment already exists, the window is outside operating hours, the worker is inactive, or the schedule does not cover the window. Another assignment in the same window is still allowed, because that was the Assignment 2 simplification. A real courier would also limit vehicle capacity; that needs a separate team decision.

Affected code: `operating_hours.py`, `availability_schedule.py`, `application.py`, `ui.py`, and the staff, quote and allocation tests.

## Updating this record

For each agreed improvement, record:

1. The responsibility, invariant or scenario concerned.
2. The observed implementation issue.
3. The decision and reason.
4. The affected code and regression checks.
5. Any remaining technical limitation.

Keep this record consistent with implemented behaviour and test results.

## 12. Visible history and packaged data

Request details distinguish the quoted estimates from the actual pickup time and show assignment start/end times and retained outcome details. Statistics count current final request outcomes in the selected period; the failed total is not a count of every historical failed pickup attempt.

Python source keeps its existing project-relative database. The frozen Windows app uses a stable per-user LocalAppData location, independent of its extraction or working directory. Explicit `--db` overrides either default. A reproducible one-folder PyInstaller build includes the runtime and packages source separately from executable files in the same ZIP. User records and caches are excluded.

## 13. Statistics failure rate and summary text

1. **Responsibility:** the A2 DeliveryStatistics CRC card (section 5.8) gives the class two responsibilities that were not implemented: calculating failure rates, and formatting the results into a summary for the business owner.
2. **Issue:** `summarise()` returned counts and averages only. The statistics screen built the summary text itself, and the `--demo` output printed the raw result dictionary.
3. **Decision:** `summarise()` now also returns `failure_rate_percent`, overall and for each worker. It is failed outcomes as a percentage of completed plus failed outcomes in the period, rounded to one decimal place, and 0 when there are no outcomes. The new static method `DeliveryStatistics.format_summary()` builds the summary lines, and `format_duration()` shows averages in days, hours and minutes. `YowdApplication.statistics_report()` returns that text to the statistics screen and the `--demo` output, so both show the same summary. Existing result keys are unchanged.
4. **Affected code and checks:** `models/delivery_statistics.py`, `application.py`, the statistics tab in `ui.py` and `__main__.py`. Tests in `tests/test_statistics.py` cover the overall and per-worker rate, the zero case, the summary lines, the empty summary and the duration format.
5. **Limitation:** the rate uses each request's final outcome, as in section 12. A request that failed pickup and was later delivered counts as one completed delivery, not as a failure.

## 14. Customer contact changes and request ownership

1. **Responsibility:** the A2 Customer CRC card (section 5.1) gives Customer three responsibilities that were not implemented: record changes to its own contact information, determine whether a selected request belongs to it, and obtain the status of its requests.
2. **Issue:** Customer only held contact details and request IDs. Details could not be changed after the first request, and quote responses only compared customer IDs.
3. **Decision:** `Customer.update_contact()` validates all three values before changing any of them. `owns_request()` checks the customer's own request list, and `DeliveryRequest.respond_to_quote()` now requires both the matching customer ID and ownership. `request_statuses()` reads each status from DeliveryRequest instead of keeping a copy. `YowdApplication.update_customer_contact()` rejects an email that belongs to another customer, because new requests are matched to existing customers by email. The **Edit Customer** button opens a form with the current details and lists the customer's requests and their statuses. All of the customer's requests share one Customer object, so a change applies to every request. No snapshot field was added.
4. **Affected code and checks:** `models/customer.py`, `models/delivery_request.py`, `application.py` and the Edit Customer form in `ui.py`. Tests in `tests/test_customer_contact.py` cover valid and invalid updates, ownership, status lookup, an email that belongs to another customer, saving across a restart, quote response ownership and the form.
5. **Limitation:** earlier contact details are not kept as history, and there is no login, so anyone using the application can edit a customer's details.

## 15. Tracking information provided by DeliveryRequest

1. **Responsibility:** A2 section 3.7 and the DeliveryRequest CRC card (section 5.2) state that the request provides tracking information from its status, quoted window and active assignment, while keeping historical assignments distinguishable.
2. **Issue:** the application facade worked out the tracking view itself from the request's fields. The request list did not show the quoted delivery time, and a worker whose assignment had ended looked the same as the worker currently allocated.
3. **Decision:** `DeliveryRequest.tracking_info()` returns the status, the quoted pickup and delivery times, the worker on the active assignment, the worker on the latest assignment and the number of ended assignments. `YowdApplication.overview()` reads the list values from it. The request list gains a **Delivery due** column, and the Worker column adds "(ended)" when the latest assignment has finished. No snapshot field was added.
4. **Affected code and checks:** `models/delivery_request.py`, `application.py` and the request list columns in `ui.py`. Tests in `tests/test_request_tracking.py` cover a new request, an allocated request, a pickup retry with retained history, and the list values.
5. **Limitation:** tracking shows recorded business status only. It is not live location tracking, as stated in A2 assumption A12.