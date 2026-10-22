"""Derive reporting values from retained requests instead of copying their state."""

from datetime import date, datetime
from typing import Iterable

from .common import DomainError, RequestStatus
from .delivery_request import DeliveryRequest
from .staff_list import StaffList


class DeliveryStatistics:
    @staticmethod
    def summarise(
        requests: Iterable[DeliveryRequest], staff_list: StaffList, start: date, end: date
    ) -> dict:
        """Count completion dates inclusively and attribute each request once.

        Failed outcomes use the latest ended assignment's date. Average elapsed
        minutes measures request creation to successful completion, not driving.
        Former workers remain in the roster and therefore remain in the results.
        """
        if not isinstance(start, date) or isinstance(start, datetime):
            raise DomainError("Report start must be a calendar date.")
        if not isinstance(end, date) or isinstance(end, datetime) or end < start:
            raise DomainError("Report end must be a calendar date on or after its start.")
        by_staff = {staff_id: 0 for staff_id in staff_list.staff}
        completed = failed = 0
        elapsed_minutes: list[float] = []
        seen: set[str] = set()
        for request in requests:
            if request.request_id in seen:
                continue
            seen.add(request.request_id)
            if request.status == RequestStatus.DELIVERED and request.completed_at:
                if not start <= request.completed_at.date() <= end:
                    continue
                completed += 1
                elapsed_minutes.append((request.completed_at - request.created_at).total_seconds() / 60)
                ended = [assignment for assignment in request.assignments if not assignment.active]
                if ended:
                    assignment = max(ended, key=lambda item: item.ended_at)
                    by_staff[assignment.staff_id] = by_staff.get(assignment.staff_id, 0) + 1
            elif request.status in (RequestStatus.FAILED_PICKUP, RequestStatus.FAILED_DELIVERY):
                ended = [assignment for assignment in request.assignments if not assignment.active]
                if ended and start <= max(item.ended_at for item in ended).date() <= end:
                    failed += 1
        return {
            "completed": completed,
            "failed": failed,
            "by_staff": by_staff,
            "average_minutes": round(sum(elapsed_minutes) / completed, 2) if completed else 0.0,
        }
