"""The customer owns contact information and references to their requests."""

from dataclasses import dataclass, field

from .common import require_text, validate_contact


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
