"""Regression tests for the stock ledger."""

from __future__ import annotations

import pytest

from orderflow import InsufficientStockError
from orderflow.inventory import StockLedger


def test_available_is_on_hand_minus_reserved():
    ledger = StockLedger(on_hand={"SKU-1": 10}, reserved={"SKU-1": 4})
    assert ledger.available("SKU-1") == 6


def test_unknown_sku_has_zero_available():
    assert StockLedger().available("NOPE") == 0


def test_reserve_beyond_available_raises():
    ledger = StockLedger(on_hand={"SKU-1": 2})
    with pytest.raises(InsufficientStockError) as excinfo:
        ledger.reserve("SKU-1", 3)
    assert (excinfo.value.sku, excinfo.value.requested, excinfo.value.available) == ("SKU-1", 3, 2)


def test_reserve_rejects_non_positive_quantity():
    with pytest.raises(ValueError):
        StockLedger(on_hand={"SKU-1": 5}).reserve("SKU-1", 0)


def test_release_cannot_exceed_reserved():
    ledger = StockLedger(on_hand={"SKU-1": 5}, reserved={"SKU-1": 1})
    with pytest.raises(ValueError):
        ledger.release("SKU-1", 2)


def test_receive_increases_on_hand():
    ledger = StockLedger()
    ledger.receive("SKU-1", 7)
    assert ledger.available("SKU-1") == 7


def test_negative_on_hand_is_rejected():
    with pytest.raises(ValueError):
        StockLedger(on_hand={"SKU-1": -1})


def test_snapshot_is_sorted_and_covers_all_skus():
    ledger = StockLedger(on_hand={"B": 2, "A": 1}, reserved={"C": 0})
    assert list(ledger.snapshot()) == ["A", "B", "C"]
