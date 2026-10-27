# Technical integration notes

## Module boundaries

- `ui.py` collects inputs and calls `YowdApplication`; it does not assign domain statuses or save snapshots directly.
- `application.py` coordinates use cases, identifiers, the clock and atomic saving. `_change()` restores the previous graph if validation or saving fails.
- `models/` owns contact, parcel, quotation, availability and delivery lifecycle rules.
- `pricing.py` defines the sample service zones, tariff and estimated duration.
- `serialization.py` encodes and validates the complete retained graph; `storage.py` writes the versioned snapshot with revision checks.

## Request and address interfaces

`DeliveryRequest.pickup` and `destination` remain suburb keys for pricing and service-area validation. `pickup_address` and `destination_address` carry the separate delivery-address text. Do not substitute full address text for a suburb key in quotation code.

New calls to `YowdApplication.create_request(...)` must supply `pickup_address=` and `destination_address=` as keyword arguments. Blank or invalid addresses are rejected without saving a partial customer/request graph.

`update_request_addresses(request_id, pickup_address, destination_address)` corrects both street details atomically while the request is Requested. It preserves suburbs and rejects edits after quotation. The domain operation is `DeliveryRequest.update_addresses()`.

`validate_parcel(data)` accepts a dictionary with `description`, `weight_kg`, `length_cm`, `width_cm` and `height_cm`. It validates an unsaved draft without saving business state. Draft add/edit and final lodgement reuse Parcel validation.

## Snapshot compatibility

- New saves use schema 2, with both address keys present.
- Schema 1 remains readable. Unknown legacy addresses are restored as a blank pair, with lifecycle and related history preserved.
- Loading alone does not rewrite a snapshot or advance its revision. The next successful business change saves schema 2.
- A legacy Requested record needs both addresses before a new quote can be issued. Existing historical quotes are restored without being recalculated.
- The older starter cannot read schema 2. Use a separate database when comparing versions.
- Preserve shared Customer objects, assignment history, worker references and pending payment records when changing serialization.

## Operating hours and availability

`yowd/operating_hours.py` is the shared calendar. Quote estimation and allocation both use it. Change the hours there if the team picks a different shift. Do not copy the clock into `AvailabilitySchedule`.

`merged_availability(periods)` checks and merges a draft without saving. `set_availability(staff_id, periods)` saves that result, including an empty list. `allocation_options(request_id)` returns each worker's eligibility and the refusal text the allocate action will raise. Existing assignment records are unchanged by an availability edit.

## Business invariants across features

- A quote does not create an assignment or reserve a worker. Allocation rechecks employment status and full-window availability.
- A request retains zero or more assignments, with at most one active assignment, and zero or one current payment record.
- A payment mismatch keeps the request Allocated and parcels Pending. Office authorisation is recorded separately; the worker must confirm pickup again.
- Failed pickup closes its assignment without creating payment. Retry retains the ended assignment. Failed delivery preserves payment and marks collected parcels Return required.
- Statistics count completed requests by completion date and retain attribution to former workers.
- Rejected operations and failed saves must leave the preceding business state intact.

## Verification

Run `python -m unittest discover -s tests -v` after changes crossing these boundaries. Check startup with `python -m yowd --check-ui` and the connected workflow with `python run.py --demo`. Current results and environment details are in `VERIFICATION.md`.

Use a separate local database for manual checks. Runtime databases, caches and build output are excluded from source control by `.gitignore`.
