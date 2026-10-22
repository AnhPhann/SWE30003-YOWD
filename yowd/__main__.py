"""Command-line entry point; graphical mode has no dependency on a web server."""

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .application import YowdApplication


@dataclass
class DemoClock:
    """Advance demonstration time without changing the computer's clock."""

    now: datetime

    def __call__(self) -> datetime:
        return self.now


def run_demo(app: YowdApplication, clock: DemoClock) -> None:
    """Exercise the four connected business areas in a disposable database."""
    app.seed_demo()
    request_id = next(iter(app.requests))
    staff_id = next(iter(app.staff_list.staff))
    amount = app.prepare_quote(request_id)
    app.respond_quote(request_id, True)
    app.allocate(request_id, staff_id)
    print("Demonstration uses a simulated clock and an outcome-only payment record.")
    print(f"Quote prepared and accepted: AUD {amount}")
    clock.now = app.requests[request_id].quote.pickup_at
    print(app.pickup(request_id, staff_id, str(amount)))
    clock.now = app.requests[request_id].quote.delivery_at
    print(app.deliver(request_id, staff_id, True))
    print()
    print(app.request_details(request_id))
    today = app.requests[request_id].completed_at.date()
    print("\nStatistics:", app.statistics(today, today))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="YOWD local delivery-management foundation")
    parser.add_argument("--db", help="SQLite file; use :memory: for disposable data")
    parser.add_argument("--demo", action="store_true", help="Run a disposable end-to-end console demonstration")
    parser.add_argument("--check-ui", action="store_true", help="Initialise the GUI without displaying a window")
    args = parser.parse_args(argv)
    if args.demo and args.check_ui:
        parser.error("Choose --demo or --check-ui, not both.")
    default_db = Path(__file__).resolve().parent.parent / "data" / "yowd.sqlite3"
    db_path = args.db or (":memory:" if args.demo or args.check_ui else default_db)
    app = None
    try:
        clock = DemoClock(datetime.now()) if args.demo else None
        app = YowdApplication(db_path, clock=clock)
        if args.demo:
            run_demo(app, clock)
            app.close()
        elif args.check_ui:
            import tkinter as tk
            from .ui import MainWindow

            root = tk.Tk()
            root.withdraw()
            try:
                MainWindow(root, app)
                root.update_idletasks()
                print("Tkinter interface initialised successfully (window hidden).")
            finally:
                root.destroy()
                app.close()
        else:
            from .ui import launch

            launch(app)
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        if app is not None:
            app.close()
        print(f"YOWD: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
