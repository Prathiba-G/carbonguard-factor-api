# CarbonGuard Factor Lookup API

Deterministic factor lookup for CarbonGuard AI.

## What it does

The API uses the UK Government GHG Conversion Factors 2026 flat-file data.
It applies hard constraints for:

- Scope
- Factor year
- Activity-data unit
- Optional category
- Optional subtype

It returns:

- `VERIFIED` when exactly one factor matches
- `REVIEW_REQUIRED` when multiple factors match
- `FACTOR_NOT_FOUND` when no factor matches

It never selects a factor using semantic similarity and never invents a factor.

## Local test

```bash
pip install -r requirements.txt
uvicorn app:app --reload
```

Open http://127.0.0.1:8000/docs

## Example request

POST `/lookup-factor`

```json
{
  "scope": "Scope 1",
  "activity": "Diesel",
  "unit": "litres",
  "year": 2026,
  "category": "Liquid fuels"
}
```

Expected behavior: `REVIEW_REQUIRED`, because more than one Scope 1 diesel fuel-volume factor exists.

For an exact subtype:

```json
{
  "scope": "Scope 1",
  "activity": "Diesel (100% mineral diesel)",
  "unit": "litres",
  "year": 2026,
  "category": "Liquid fuels"
}
```

Expected behavior: `VERIFIED`.

Source: UK Government GHG Conversion Factors 2026, revised July 2026 flat file.
