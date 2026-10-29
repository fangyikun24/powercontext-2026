"""Pricing rules: customer-tier discounts applied on top of an order subtotal."""

from __future__ import annotations

from decimal import Decimal

from orderflow.models import CustomerTier, Order, money

#: (minimum subtotal, discount rate) pairs, evaluated best-match-wins.
TIER_RULES: dict[CustomerTier, tuple[tuple[Decimal, Decimal], ...]] = {
    CustomerTier.STANDARD: (),
    CustomerTier.SILVER: ((Decimal("100.00"), Decimal("0.05")),),
    CustomerTier.GOLD: ((Decimal("50.00"), Decimal("0.05")), (Decimal("200.00"), Decimal("0.10"))),
}


def discount_rate(tier: CustomerTier, subtotal: Decimal) -> Decimal:
    """Return the discount rate for ``tier`` at ``subtotal``.

    The highest threshold that the subtotal reaches wins. Unknown tiers behave like
    ``STANDARD`` so that adding a tier never breaks existing callers.
    """
    best = Decimal("0")
    for threshold, rate in TIER_RULES.get(tier, ()):
        if subtotal >= threshold:
            best = rate
    return best


def order_total(order: Order, tier: CustomerTier = CustomerTier.STANDARD) -> Decimal:
    """Total payable for ``order`` after the tier discount."""
    subtotal = order.subtotal
    rate = discount_rate(tier, subtotal)
    if rate == 0:
        return subtotal
    return money(subtotal * (Decimal("1") - rate))
