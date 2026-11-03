"""The customer owns contact information and references to their requests."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .common import require_text, validate_contact

if TYPE_CHECKING:
    from .delivery_request import DeliveryRequest


@dataclass
class Customer:
    customer_id: str
    name: str
    email: str
    phone: str
    request_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.customer_id = require_text(self.customer_id, "Customer ID")
        self.name, self.email, self.phone = validate_contact(
            self.name, self.email, self.phone
        )
        self.request_ids = list(dict.fromkeys(
            require_text(value, "Request ID") for value in self.request_ids
        ))

    def update_contact(self, name: str, email: str, phone: str) -> None:
        """Replace the contact details after validating all three values.

        Nothing changes if any value is invalid.
        """
        validated_name, validated_email, validated_phone = validate_contact(
            name, email, phone,
        )
        self.name = validated_name
        self.email = validated_email
        self.phone = validated_phone

    def owns_request(self, request_id: str) -> bool:
        """Return whether the given request belongs to this customer."""
        return request_id in self.request_ids

    def request_statuses(
        self, requests: Iterable["DeliveryRequest"],
    ) -> list[tuple[str, str]]:
        """Return (request ID, status) for each of this customer's requests.

        The status is read from each DeliveryRequest, so no copy of it is
        stored here. Requests are listed in the order they were lodged.
        """
        statuses_by_id = {}
        for request in requests:
            if self.owns_request(request.request_id):
                statuses_by_id[request.request_id] = request.status.value
        statuses = []
        for request_id in self.request_ids:
            if request_id in statuses_by_id:
                statuses.append((request_id, statuses_by_id[request_id]))
        return statuses
