# Local development checks

Checked on 22 October 2026 using Windows, Python 3.12.14, Tk 8.6 and SQLite 3.53.1.
These results include the address and parcel-input refinement and describe
the current local development version.

## Automated suite

```text
python -m unittest discover -s tests -v
```

Result: **114 tests passed, none skipped**.

- 21 domain-rule tests.
- 29 application and persistence-integration tests.
- 30 object-graph serialization tests.
- 19 SQLite storage tests.
- 15 desktop integration tests using withdrawn Tk windows and the real application service.

The checks include multiple parcels, quote validation and responses, allocation
eligibility, overlapping-job policy, wrong-worker rejection, payment exceptions,
separate office authorisation, failed pickup and retry, failed delivery, former
workers, completion-date statistics, startup restoration, corrupt-data rejection,
rollback after a failed save and stale-writer protection. Desktop tests also check
input correction, parcel editing/removal and cancellation without saving. The
address checks cover separate street/suburb fields, required addresses for new
requests, Requested-only correction, failed-save rollback, save/reopen and
schema 1 restoration without inventing addresses or rewriting on load. A legacy
Requested record cannot be quoted until its missing addresses are supplied.

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

## Review still needed

Hidden-window tests do not verify visible layout or usability on other computers.
No standalone executable has been built. This package runs from Python source
and needs Python with Tkinter installed.
