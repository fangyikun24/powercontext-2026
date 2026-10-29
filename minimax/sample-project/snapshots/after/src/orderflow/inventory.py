"""Stock tracking for the orderflow sample service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from orderflow.errors import InsufficientStockError


@dataclass
class StockLedger:
    """Tracks on-hand and reserved quantity per SKU."""

    on_hand: dict[str, int] = field(default_factory=dict)
    reserved: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for sku, quantity in self.on_hand.items():
            if quantity < 0:
                raise ValueError(f"on_hand for {sku} must not be negative")
        for sku, quantity in self.reserved.items():
            if quantity < 0:
                raise ValueError(f"reserved for {sku} must not be negative")

    def available(self, sku: str) -> int:
        return self.on_hand.get(sku, 0) - self.reserved.get(sku, 0)

    def reserve(self, sku: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")
        available = self.available(sku)
        if quantity > available:
            raise InsufficientStockError(sku, quantity, available)
        self.reserved[sku] = self.reserved.get(sku, 0) + quantity

    def release(self, sku: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")
        current = self.reserved.get(sku, 0)
        if quantity > current:
            raise ValueError(f"cannot release {quantity} of {sku}, only {current} reserved")
        self.reserved[sku] = current - quantity

    def receive(self, sku: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")
        self.on_hand[sku] = self.on_hand.get(sku, 0) + quantity

    def snapshot(self) -> Mapping[str, int]:
        return {sku: self.available(sku) for sku in sorted(set(self.on_hand) | set(self.reserved))}
