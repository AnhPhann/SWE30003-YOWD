# Local development checks

Checked on 3 November 2026 using Windows, Python 3.12.14, Tk 8.6 and SQLite 3.53.1.
The local Windows executable was built in an isolated environment with
PyInstaller 6.22.3. These results describe this local development/package version.

## Automated suite

```text
python -m unittest discover -s tests -v
```

Result: **186 tests passed, none skipped**.

- 32 application and persistence-integration tests.
- 8 retained-assignment-history tests.
- 18 delivery-outcome tests.
- 21 domain-rule tests.
- 5 source/executable archive tests.
- 7 source/frozen database-path tests.
- 9 legacy-payment recovery tests.
- 2 request-history display tests.
- 33 object-graph serialization tests.
- 15 statistics tests.
- 20 SQLite storage tests.
- 16 desktop integration tests using withdrawn Tk windows and the real application service.

The checks include multiple parcels, quote validation and responses, allocation
eligibility, overlapping-job policy, wrong-worker rejection, payment exceptions,
separate office authorisation, failed pickup and retry, failed delivery, former
workers, completion-date statistics, startup restoration, corrupt-data rejection,
rollback after a failed save and stale-writer protection. Desktop tests also check
input correction, parcel editing/removal and cancellation without saving. The
address checks cover separate street/suburb fields, required addresses for new
requests, Requested-only correction, failed-save rollback, save/reopen and
schema 1/2 restoration without invented addresses, outcome details or pickup
events. A legacy Requested record cannot be quoted until its missing addresses
are supplied. Schema 3 retains detailed assignment outcomes across retry/reopen.

Legacy Allocated records with existing payment can be authorised and then
confirmed by the assigned worker without replacing their payment ID, amount or
received time. New pickups still collect first and wait for office authorisation
before delivery when payment differs. Actual pickup and assignment start/end
times are displayed separately from quoted estimates.

## Startup and demonstration

```text
python run.py --demo
python -m yowd --check-ui
python -m compileall -q yowd run.py
```

The console demonstration completed a two-parcel Richmond-to-Footscray delivery
using a sample AUD 25 quote. Its simulated clock advances to the quoted pickup
and delivery times; it does not change the computer's time or perform payment.
The hidden desktop startup check and Python compilation check both succeeded.

## Windows executable and package checks

```text
YOWD.exe --demo
YOWD.exe --check-ui
YOWD.exe --demo --db "saved records.sqlite3"
YOWD.exe --check-ui --db "saved records.sqlite3"
```

The executable completed these checks from a different working directory with
spaces and with Python removed from PATH. It saved a schema 3 Delivered request,
reopened that database and preserved its stored snapshot/revision. The executable
uses its bundled Python/Tk runtime. Diagnostic modes did not create a default
profile database.

The combined archive contains current source, tests and build instructions, plus
the executable and its complete runtime folder. User databases, caches, Git
metadata and build environments are excluded. The package must be extracted
before running, with YOWD.exe kept beside its _internal folder.

## Review still needed

Hidden-window tests do not verify visible layout or usability on other computers.
The Windows build was exercised on this machine; another member should still
check the extracted application on a separate Windows computer and record the
actual result. Submission screenshots/video and report content are separate
from these automated checks.
