"""Derive reporting values from retained requests without copying them."""

import calendar
from datetime import date, datetime, timedelta
from typing import Iterable

from .common import DomainError, RequestStatus
from .delivery_request import DeliveryRequest
from .staff_list import StaffList


REPORTING_PERIODS = ("Day", "Week", "Month", "Year", "Year to date")
FAILED_STATUSES = (RequestStatus.FAILED_PICKUP, RequestStatus.FAILED_DELIVERY)


def _require_calendar_date(value: date, label: str) -> None:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise DomainError(f"{label} must be a calendar date.")


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


class DeliveryStatistics:
    @staticmethod
    def period_range(period_name: str, day: date) -> tuple[date, date]:
        """Return the inclusive start and end dates of a named period.

        Week runs Monday to Sunday. Month and Year are full calendar
        periods. Year to date ends on the given day.
        """
        _require_calendar_date(day, "Reference date")
        if period_name == "Day":
            return day, day
        if period_name == "Week":
            monday = day - timedelta(days=day.weekday())
            return monday, monday + timedelta(days=6)
        if period_name == "Month":
            last_day = calendar.monthrange(day.year, day.month)[1]
            return day.replace(day=1), day.replace(day=last_day)
        if period_name == "Year":
            return date(day.year, 1, 1), date(day.year, 12, 31)
        if period_name == "Year to date":
            return date(day.year, 1, 1), day
        raise DomainError(f"Unknown reporting period: {period_name}.")

    @staticmethod
    def summarise(
        requests: Iterable[DeliveryRequest],
        staff_list: StaffList,
        start: date,
        end: date,
        staff_id: str | None = None,
    ) -> dict:
        """Count delivery outcomes inside an inclusive date range.

        A Delivered request uses its completion date. A failed request uses
        the end date of its latest ended assignment. That assignment also
        decides which worker the outcome belongs to. When staff_id is given,
        only that worker's outcomes are counted.
        """
        _require_calendar_date(start, "Report start")
        _require_calendar_date(end, "Report end")
        if end < start:
            raise DomainError("Report end must be on or after its start.")
        if staff_id is None:
            reported_ids = list(staff_list.staff)
        else:
            staff_list.get(staff_id)  # Raises DomainError if unknown.
            reported_ids = [staff_id]

        counts = {}
        for reported_id in reported_ids:
            counts[reported_id] = {"completed": 0, "failed": 0}
        completed = 0
        failed = 0
        lodgement_minutes = []
        pickup_minutes = []
        seen_ids = set()

        for request in requests:
            if request.request_id in seen_ids:
                continue
            seen_ids.add(request.request_id)

            # The latest ended assignment owns the request's final outcome.
            last_assignment = None
            for assignment in request.assignments:
                if assignment.active:
                    continue
                if (last_assignment is None
                        or assignment.ended_at > last_assignment.ended_at):
                    last_assignment = assignment
            if last_assignment is None:
                worker_id = None
            else:
                worker_id = last_assignment.staff_id
            if staff_id is not None and worker_id != staff_id:
                continue

            if request.status == RequestStatus.DELIVERED:
                if not start <= request.completed_at.date() <= end:
                    continue
                completed += 1
                lodgement_time = request.completed_at - request.created_at
                pickup_time = request.completed_at - request.picked_up_at
                lodgement_minutes.append(lodgement_time.total_seconds() / 60)
                pickup_minutes.append(pickup_time.total_seconds() / 60)
                outcome = "completed"
            elif request.status in FAILED_STATUSES and last_assignment:
                if not start <= last_assignment.ended_at.date() <= end:
                    continue
                failed += 1
                outcome = "failed"
            else:
                continue
            if worker_id is None:
                continue
            if worker_id not in counts:
                counts[worker_id] = {"completed": 0, "failed": 0}
            counts[worker_id][outcome] += 1

        by_staff = {}
        staff_rows = []
        for worker_id, worker_counts in counts.items():
            by_staff[worker_id] = worker_counts["completed"]
            worker = staff_list.staff.get(worker_id)
            name = worker_id
            active = False
            if worker is not None:
                name = worker.name
                active = worker.active
            staff_rows.append({
                "staff_id": worker_id,
                "name": name,
                "active": active,
                "completed": worker_counts["completed"],
                "failed": worker_counts["failed"],
            })

        return {
            "completed": completed,
            "failed": failed,
            "by_staff": by_staff,
            "average_minutes": _average(lodgement_minutes),
            "average_pickup_to_delivery_minutes": _average(pickup_minutes),
            "staff_rows": staff_rows,
        }