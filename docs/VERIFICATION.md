# Local development checks

Checked on 22 October 2026 using Windows, Python 3.12.14, Tk 8.6 and SQLite 3.53.1.
These results describe this starter version, not the team's final submission.

## Automated suite

```text
python -m unittest discover -s tests -v
```

Result: **88 tests passed, none skipped**.

- 16 domain-rule tests.
- 22 application and persistence-integration tests.
- 25 object-graph serialization tests.
- 17 SQLite storage tests.
- 8 desktop integration tests using withdrawn Tk windows and the real application service.

The checks include multiple parcels, quote validation and responses, allocation
eligibility, overlapping-job policy, wrong-worker rejection, payment exceptions,
separate office authorisation, failed pickup and retry, failed delivery, former
workers, completion-date statistics, startup restoration, corrupt-data rejection,
rollback after a failed save and stale-writer protection. Desktop tests also check
input correction, parcel removal and cancellation without saving.

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

The team should inspect the desktop layout and usability on its own computers,
agree the sample business policies, and record final execution evidence after
making its changes. No standalone executable has been built. This package runs
from Python source and needs Python with Tkinter installed.
