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

Use a separate test database when comparing versions. New saves use snapshot schema 3, which includes retained assignment outcome details. This version reads schemas 1, 2 and 3 without rewriting merely on startup; the next successful change saves schema 3. Older application versions cannot open schema 3 saves.

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
5. Record collection as the allocated worker. The parcels become collected and the received amount is saved. A mismatch keeps the request Picked Up but blocks delivery until office authorisation. There is no second pickup for a new request. An older saved Allocated request that already holds a mismatched payment can be authorised and then confirmed by its worker using that same payment record.
6. Record successful delivery or a failed delivery with a reason. Both close the active assignment. Failed delivery retains the pickup payment and flags the collected parcels as requiring return.
7. Calculate statistics for an inclusive date range. Completed deliveries use completion dates, including deliveries performed by workers who are now inactive.
8. Close and reopen the application with the same database to inspect the restored records.

Also try invalid operations: zero parcel weight, an invalid email, an inactive worker, an uncovered quote window, the wrong reporting worker, and an empty failed-delivery reason. A rejected action should explain the problem and preserve the previous business state.

## Explicit starter policies

These are implementation assumptions for team review, not a real YOWD tariff or complete Melbourne service definition.

- The configured sample service area is Melbourne, Docklands, Southbank, Carlton, Brunswick, Richmond, Hawthorn, Footscray, St Kilda and South Yarra. New requests require complete delivery-address text separately from these suburb keys; pricing and coverage still use suburbs.
- Legacy records with no street addresses keep both address fields blank. The request details show that the information was not recorded. A legacy Requested delivery must be corrected through **Edit addresses** before it can be quoted; historical records are not assigned invented addresses.
- The sample quote is AUD 10 base fee, plus AUD 2 per parcel, plus AUD 2 per total billable kilogram, plus a route charge of AUD 2 within one zone or AUD 5 across zones. Each parcel's billable weight is the greater of actual kilograms and `length_cm * width_cm * height_cm / 5000`. The total is rounded to cents.
- Operating hours are Monday to Friday, 08:00 to 18:00 Melbourne local time. New availability periods and quoted windows must each fall inside one such day. Public holidays are not excluded. A saved schedule from before this rule is still loaded; the next edit is checked. This is a team assumption and can be changed in one place, `yowd/operating_hours.py`.
- Window estimation considers request age, operating hours and active workers' availability. The scheduling policy uses a 15-minute lead time and 15-minute priority-rank increments. The estimated delivery duration is 60 minutes within a zone and 90 minutes across zones. A quote does not reserve a worker. Another job in the same window does not, by itself, make a worker unavailable.
- All datetimes are naive local Melbourne times. Enter desktop date/time values as `YYYY-MM-DD HH:MM` and statistics dates as `YYYY-MM-DD`.
- Pickup and handover operate on all required parcels together. Partial collection and partial delivery need a separate agreed design.
- Payments are simulated outcome records. Office authorisation records an entered name and reason; the starter does not authenticate that person.
- A new pickup with a payment mismatch records Picked Up and collected parcels. Office authorisation is required before either delivery outcome. Older saved Allocated requests with existing payment stay uncollected until authorisation and an actual worker confirmation; loading or authorisation alone never invents collection.
- Failed pickup creates no payment record and closes its assignment. An explicit office retry returns it to Accepted while retaining the previous assignment, specific reason and affected-parcel text. A failed pickup cannot discard an existing payment. Failed delivery preserves payment and records its detailed outcome in the ended assignment.
- SQLite stores one versioned JSON application snapshot. Schema 3 adds assignment outcome details; schema 2 supplies addresses and schema 1 can omit them. Unknown old details remain blank. Loading alone does not advance the saved revision or migrate contents. Revision checks prevent silent replacement of a newer snapshot by an older instance. This is local persistence, not a multi-user server.

Implementation rationale is recorded in [Design decisions](docs/DESIGN_DECISIONS.md). [Technical integration notes](docs/TEAM_HANDOFF.md) describe shared interfaces, snapshot compatibility and business invariants. [Verification results](docs/VERIFICATION.md) record the tested environment and checks.

## Code map

```text
run.py                       Terminal entry point
start-yowd.bat               Windows launcher
yowd/__main__.py             Command-line options and startup
yowd/paths.py                Source and packaged-app database locations
yowd/application.py          Application facade for screens and demonstrations
yowd/operating_hours.py       Weekday operating calendar used by availability and quotes
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
tools/build_windows.py       Reproducible Windows build and source/executable ZIP
```

Use [PEP 8](https://peps.python.org/pep-0008/) as the coding standard when extending the project. Keep business validation in the domain/application layer, rather than duplicating it inside a button callback. New business behaviour needs tests for both the intended outcome and rejected operations.

## Windows executable and local package

The Windows package contains `windows/YOWD/YOWD.exe` with its `_internal` runtime folder, plus the current Python project in `source/`. Extract the entire archive and keep those runtime files together. Double-click `YOWD.exe`; Python is not required on the target Windows computer. A console window opens with the desktop application and supports diagnostic commands.

The packaged app creates its database at `%LOCALAPPDATA%\YOWD\yowd.sqlite3`. Running Python source keeps the existing project-relative `data/yowd.sqlite3`. Use `--db` with an explicit path to select another database. Diagnostics `--demo` and `--check-ui` default to disposable memory databases.

Build on Windows using an isolated environment:

```text
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.venv\Scripts\python.exe tools\build_windows.py
```

The build uses [PyInstaller](https://pyinstaller.org/en/stable/usage.html), pinned in the build requirements. It writes `dist/windows/YOWD/YOWD.exe` and `dist/YOWD-Windows-Source.zip`. The ZIP includes source and executable/runtime files while excluding user databases, caches, Git metadata and build environments. Build dependencies are not application runtime requirements.

Run the packaged checks from `windows/YOWD` after extracting:

```text
.\YOWD.exe --demo
.\YOWD.exe --check-ui
```

Current checks and the exact tested platform are recorded in `docs/VERIFICATION.md`. A test on this machine does not replace the group's independent check on another Windows computer.
