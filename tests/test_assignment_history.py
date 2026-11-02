"""Retained assignment facts survive retries without inventing past details."""

from datetime import timedelta
import unittest

from yowd.models import DeliveryAssignment, DomainError, RequestStatus
from yowd.serialization import decode_state, encode_state
from tests.test_serialization import START, make_graph


class AssignmentHistoryTests(unittest.TestCase):
    def test_legacy_positional_assignment_has_optional_details_and_end_records_note(self):
        assignment = DeliveryAssignment("A1", "R1", "S1", START, None, "")
        self.assertEqual(getattr(assignment, "outcome_details", None), "")
        assignment.end(START + timedelta(hours=1), "Delivered", "  Left with reception  ")
        self.assertEqual(assignment.outcome_details, "Left with reception")
        self.assertEqual(assignment.outcome, "Delivered")

    def test_invalid_details_do_not_end_or_change_assignment(self):
        assignment = DeliveryAssignment("A1", "R1", "S1", START)
        self.assertEqual(getattr(assignment, "outcome_details", None), "")
        with self.assertRaisesRegex(DomainError, "details.*text"):
            assignment.end(START + timedelta(hours=1), "Failed pickup", None)
        self.assertTrue(assignment.active)
        self.assertEqual((assignment.outcome, assignment.outcome_details), ("", ""))

    def test_active_assignment_cannot_hold_final_details(self):
        self.assertIn("outcome_details", DeliveryAssignment.__dataclass_fields__)
        with self.assertRaisesRegex(DomainError, "active assignment"):
            DeliveryAssignment("A1", "R1", "S1", START, outcome_details="Unknown result")

    def test_parcel_failure_survives_retry_reallocation_and_round_trip(self):
        graph = make_graph("Allocated")
        request, worker = graph[2]["R1"], graph[1].get("S1")
        request.record_pickup("S1", False, None, START + timedelta(minutes=40),
                              failure="Parcel damaged", parcel_id="P1")
        first = request.assignments[0]
        self.assertEqual(getattr(first, "outcome_details", None),
                         "Failed Pickup: Parcel damaged - Books (P1).")
        request.retry_pickup()
        self.assertEqual(request.failure_reason, "")
        request.allocate(worker, "A2", START + timedelta(minutes=45))
        restored = decode_state(encode_state(*graph))[2]["R1"]
        self.assertEqual(restored.status, RequestStatus.ALLOCATED)
        self.assertEqual(restored.assignments[0].outcome_details,
                         "Failed Pickup: Parcel damaged - Books (P1).")
        self.assertEqual(restored.assignments[0].ended_at, START + timedelta(minutes=40))
        self.assertEqual(restored.assignments[1].outcome_details, "")

    def test_retry_preserves_known_legacy_reason_without_overwriting_older_details(self):
        graph = make_graph("Failed pickup", history=True)
        request = graph[2]["R1"]
        self.assertEqual(getattr(request.assignments[-1], "outcome_details", None),
                         "Required parcels were not all collected in acceptable condition.")
        request.assignments[0].outcome_details = "Earlier customer absence"
        request.assignments[-1].outcome_details = ""
        request.failure_reason = "Legacy report: missing Books (P1)."
        request.retry_pickup()
        self.assertEqual(request.assignments[-1].outcome_details,
                         "Legacy report: missing Books (P1).")
        self.assertEqual(request.assignments[0].outcome_details, "Earlier customer absence")
        self.assertEqual(request.failure_reason, "")

    def test_retry_keeps_existing_details_and_leaves_unknown_older_attempt_blank(self):
        graph = make_graph("Failed pickup", history=True)
        request = graph[2]["R1"]
        self.assertIsNotNone(getattr(request.assignments[-1], "outcome_details", None))
        request.assignments[0].outcome_details = ""
        request.assignments[-1].outcome_details = "Original retained report"
        request.failure_reason = "Current report wording"
        request.retry_pickup()
        self.assertEqual(request.assignments[-1].outcome_details, "Original retained report")
        self.assertEqual(request.assignments[0].outcome_details, "")

    def test_failed_delivery_records_affected_parcel_and_details(self):
        graph = make_graph("Picked Up")
        request = graph[2]["R1"]
        request.record_delivery("S1", False, "Box opened", START + timedelta(hours=2),
                                failure="Parcel damaged", parcel_id="P1")
        self.assertEqual(getattr(request.assignments[-1], "outcome_details", None),
                         "Failed delivery: Parcel damaged - Books (P1). Details: Box opened.")
        restored = decode_state(encode_state(*graph))[2]["R1"]
        self.assertEqual(restored.assignments[-1].outcome_details, request.failure_reason)

    def test_successful_delivery_retains_note(self):
        request = make_graph("Picked Up")[2]["R1"]
        request.record_delivery("S1", True, "  Left with reception  ", START + timedelta(hours=2))
        self.assertEqual(getattr(request.assignments[-1], "outcome_details", None),
                         "Left with reception")
        self.assertEqual(request.failure_reason, "")


if __name__ == "__main__":
    unittest.main()
