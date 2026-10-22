# YOWD delivery-management starter

A local Python desktop application for SWE30003 Assignment 3, based on the team's Assignment 2 object design. It implements request lodgement, quotation, allocation, pickup/payment, delivery outcomes and local persistence.

## Run it

Use Python 3.11 or newer. The application uses the Python standard library, including Tkinter and SQLite. No third-party runtime packages or database server are needed. Work from this folder in a terminal.

```text
python run.py
```

The equivalent module entry point is:

```text
python -m yowd
```

On Windows, double-click `start-yowd.bat`, or run it from a terminal. It uses the Windows Python launcher where available and otherwise calls `python`.

If `python` is not found on Windows, try `py -3` in place of `python`. The application needs Python 3.11 or newer regardless of which launcher is used. To check Tkinter separately, run `python -m tkinter`; a small Tk window should open. Some Linux installations provide Tkinter as a separate operating-system package.

Use a separate database file for independent demonstration data:

```text
python run.py --db data/my-review.sqlite3
```

Use a separate test database when reviewing this version alongside the older starter. New saves use snapshot schema 2, which the older starter cannot read. This version can load schema 1 without rewriting it merely on startup; a later successful change saves schema 2.

Run the scripted terminal demonstration without changing an existing database:

```text
python run.py --demo
```

The scripted demonstration uses an in-memory database and advances a simulated clock to the quoted pickup and delivery times. It is a functional check; desktop usability needs a separate review.

Run the test suite:

```text
python -m unittest discover -s tests -v
```

## Try the desktop workflow

The desktop interface groups work into Delivery requests, Staff and availability, and Delivery statistics. Select a request to see its parcels, current quote, allocation history and payment outcome together.

1. Register a worker and add an availability period covering a future delivery window. The **Load sample data** action provides demonstration records for an empty database.
2. Create a customer request with complete pickup and destination address text and separate configured suburbs. Add at least one parcel with a description, weight and dimensions. Invalid draft parcels are rejected immediately. Use **Edit selected parcel** to correct a row or remove it before submitting; cancellation preserves the previous draft.
3. Use **Edit addresses** to correct a Requested delivery before preparing its quote. Then check the quote's sample price and estimated window and record acceptance or decline. Address changes after quotation are rejected so the existing offer keeps its original delivery context.
4. Allocate an active worker whose schedule covers the full quoted window. An existing job in the same window does not, by itself, make the worker ineligible under the agreed A2 simplification.
5. Record collection as the allocated worker. Matching payment allows pickup. A mismatched payment is retained as pending and requires an explicit office authorisation before the worker confirms pickup again.
6. Record successful delivery or a failed delivery with a reason. Both close the active assignment. Failed delivery retains the pickup payment and flags the collected parcels as requiring return.
7. Calculate statistics for an inclusive date range. Completed deliveries use completion dates, including deliveries performed by workers who are now inactive.
8. Close and reopen the application with the same database to inspect the restored records.

Also try invalid operations: zero parcel weight, an invalid email, an inactive worker, an uncovered quote window, the wrong reporting worker, and an empty failed-delivery reason. A rejected action should explain the problem and preserve the previous business state.

## Explicit starter policies

These are implementation assumptions for team review, not a real YOWD tariff or complete Melbourne service definition.

- The configured sample service area is Melbourne, Docklands, Southbank, Carlton, Brunswick, Richmond, Hawthorn, Footscray, St Kilda and South Yarra. New requests require complete delivery-address text separately from these suburb keys; pricing and coverage still use suburbs.
- Legacy records with no street addresses keep both address fields blank. The request details show that the information was not recorded. A legacy Requested delivery must be corrected through **Edit addresses** before it can be quoted; historical records are not assigned invented addresses.
- The sample quote is AUD 10 base fee, plus AUD 2 per parcel, plus AUD 2 per total billable kilogram, plus a route charge of AUD 2 within one zone or AUD 5 across zones. Each parcel's billable weight is the greater of actual kilograms and `length_cm * width_cm * height_cm / 5000`. The total is rounded to cents.
- Window estimation considers request age and active workers' availability. The scheduling policy uses a 15-minute lead time and 15-minute priority-rank increments. The estimated delivery duration is 60 minutes within a zone and 90 minutes across zones. A quote does not reserve a worker.
- All datetimes are naive local Melbourne times. Enter desktop date/time values as `YYYY-MM-DD HH:MM` and statistics dates as `YYYY-MM-DD`.
- Pickup and handover operate on all required parcels together. Partial collection and partial delivery need a separate agreed design.
- Payments are simulated outcome records. Office authorisation records an entered name and reason; the starter does not authenticate that person.
- A payment mismatch keeps the request Allocated and the parcels Pending. After office authorisation, the allocated worker must confirm pickup again. Recording authorisation alone does not change the delivery status.
- Failed pickup creates no payment record and closes its assignment. An explicit office retry returns it to Accepted while retaining the previous assignment. Failed delivery preserves the payment already recorded at pickup.
- SQLite stores one versioned JSON application snapshot. Schema 2 records both delivery addresses and accepts migrated legacy blank pairs. Schema 1 is still readable, and loading alone does not advance the saved revision or migrate its contents. Revision checks prevent silent replacement of a newer snapshot by an older instance. This is a local starter persistence design, not a full relational data model or multi-user server.

Implementation rationale is recorded in [Design decisions](docs/DESIGN_DECISIONS.md). [Technical integration notes](docs/TEAM_HANDOFF.md) describe shared interfaces, snapshot compatibility and business invariants. [Verification results](docs/VERIFICATION.md) record the tested environment and checks.

## Code map

```text
run.py                       Terminal entry point
start-yowd.bat               Windows launcher
yowd/__main__.py             Command-line options and startup
yowd/application.py          Application facade for screens and demonstrations
yowd/pricing.py              Sample service zones, tariff and duration policy
yowd/serialization.py        Convert the shared object graph to/from snapshots
yowd/storage.py              Atomic SQLite snapshot storage and revision checks
yowd/ui.py                   Tkinter desktop screens
yowd/models/common.py        DomainError, status values and input validation
yowd/models/customer.py      Customer
yowd/models/delivery_request.py
                             DeliveryRequest lifecycle coordination
yowd/models/parcel.py        Parcel
yowd/models/delivery_quote.py
                             DeliveryQuote
yowd/models/staff_list.py    StaffList
yowd/models/delivery_staff.py
                             DeliveryStaff
yowd/models/availability_schedule.py
                             AvailabilitySchedule
yowd/models/delivery_assignment.py
                             DeliveryAssignment
yowd/models/payment_record.py
                             PaymentRecord
yowd/models/delivery_statistics.py
                             DeliveryStatistics
tests/                       Domain, application, persistence and desktop checks
docs/                        Technical decisions, integration notes and checks
```

Use [PEP 8](https://peps.python.org/pep-0008/) as the coding standard when extending the project. Keep business validation in the domain/application layer, rather than duplicating it inside a button callback. New business behaviour needs tests for both the intended outcome and rejected operations.

## Runtime and packaging status

This source package requires Python with Tkinter installed. A standalone executable has not been built. Verify launch, database location and save/reopen on the target computer when preparing an executable package.
