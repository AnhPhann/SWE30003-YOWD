"""A validated offer and the customer's recorded response."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .common import DomainError, QuoteDecision, local_datetime, money, require_text


@dataclass
class DeliveryQuote:
    quote_id: str
    request_id: str
    amount: Decimal
    pickup_at: datetime
    delivery_at: datetime
    issued_at: datetime
    decision: QuoteDecision = QuoteDecision.PENDING

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Check the offer without reserving a worker or creating an assignment."""
        quote_id = require_text(self.quote_id, "Quote ID")
        request_id = require_text(self.request_id, "Request ID")
        amount = money(self.amount, "Quoted amount")
        local_datetime(self.pickup_at, "Estimated pickup")
        local_datetime(self.delivery_at, "Estimated delivery")
        local_datetime(self.issued_at, "Quote issue time")
        if self.delivery_at < self.pickup_at:
            raise DomainError("Estimated delivery cannot be before pickup.")
        if self.pickup_at < self.issued_at:
            raise DomainError("Estimated pickup cannot be before the quote is issued.")
        try:
            decision = QuoteDecision(self.decision)
        except (ValueError, TypeError):
            raise DomainError("Unknown quote decision.") from None
        self.quote_id, self.request_id = quote_id, request_id
        self.amount, self.decision = amount, decision

    def record_response(self, accepted: bool) -> None:
        """Record one decision; an incompatible later response is not allowed."""
        if not isinstance(accepted, bool):
            raise DomainError("Quote response must be acceptance or decline.")
        decision = QuoteDecision.ACCEPTED if accepted else QuoteDecision.DECLINED
        if self.decision not in (QuoteDecision.PENDING, decision):
            raise DomainError("The quote already has a different recorded decision.")
        self.decision = decision
