# orderflow — sample business project

A deliberately small but real order-management service used as the **business project**
for the SDD task. It has runnable behaviour, real validation, and a pytest suite that
needs no network, no database, and no external service.

## Layout

```
sample-project/
├── src/orderflow/
│   ├── models.py      # OrderLine / Order / money quantisation
│   ├── pricing.py     # customer-tier discount rules
│   ├── inventory.py   # stock ledger (reserve / release / receive)
│   ├── service.py     # OrderService: add / get / list / place / cancel
│   └── errors.py      # exception types
├── specs/             # authoritative requirement documents (SDD input)
│   ├── orders.md
│   └── pricing.md
├── tests/             # pytest suite (also the SDD verification material)
├── snapshots/
│   ├── before/        # source snapshot before the SDD task was applied
│   └── after/         # source snapshot after the SDD task was applied
└── pyproject.toml
```

## Run the tests

```bash
python -m pytest -q            # from sample-project/
```

Expected: the suite passes in the delivered (post-change) state.

## Reproduce the pre-change state

```bash
# copy the recorded "before" sources over the working tree
cp -R snapshots/before/src/orderflow/. src/orderflow/
python -m pytest -q
```

Expected: `tests/test_min_total_filter.py` fails (the feature is absent), while every
other test file passes. Restore with `cp -R snapshots/after/src/orderflow/. src/orderflow/`.

## The SDD task

Add an optional `min_total` filter to `OrderService.list_orders` as specified by
`specs/orders.md` → `SPEC-ORD-004`. See `../docs/验证样例.md` for the full task definition.
