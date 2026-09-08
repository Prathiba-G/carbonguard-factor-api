from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Optional
import json, re

app = FastAPI(
    title="CarbonGuard Factor Lookup API",
    version="1.0.0",
    description="Deterministic lookup of verified UK Government GHG Conversion Factors 2026."
)

with open("factors.json", "r", encoding="utf-8") as f:
    FACTORS = json.load(f)

def norm(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9%./() -]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s

def contains_norm(haystack: str, needle: str) -> bool:
    return norm(needle) in norm(haystack)

def searchable(r):
    return " | ".join(r["category_path"] + [r["activity"]])

class LookupRequest(BaseModel):
    scope: str = Field(..., description="Scope 1, Scope 2, or Scope 3")
    activity: str = Field(..., description="Activity or fuel name. Use the official factor activity when known.")
    unit: str = Field(..., description="Activity data unit, e.g. litres, kWh, km, miles")
    year: int = Field(2026, description="Factor year")
    category: Optional[str] = Field(None, description="Optional official category, e.g. Liquid fuels")
    subtype: Optional[str] = Field(None, description="Optional exact subtype such as 100% mineral diesel")

@app.get("/")
def root():
    return {"service": "CarbonGuard Factor Lookup API", "status": "ok", "factor_records": len(FACTORS)}

@app.post("/lookup-factor")
def lookup_factor(req: LookupRequest):
    # Deterministic filtering: year + scope + unit are hard constraints.
    candidates = [
        r for r in FACTORS
        if r["year"] == req.year
        and norm(r["scope"]) == norm(req.scope)
        and norm(r["unit"]) == norm(req.unit)
    ]

    # Optional category is also a hard constraint.
    if req.category:
        cat = norm(req.category)
        candidates = [
            r for r in candidates
            if any(cat == norm(part) for part in r["category_path"])
        ]

    # Activity matching is deterministic: exact activity/category match first,
    # then exact phrase containment in the official record text.
    activity = norm(req.activity)
    if activity:
        exact = [
            r for r in candidates
            if norm(r["activity"]) == activity
            or any(norm(part) == activity for part in r["category_path"])
        ]
        if exact:
            candidates = exact
        else:
            contained = [
                r for r in candidates
                if activity in norm(searchable(r))
            ]
            candidates = contained

    # Optional subtype is a hard constraint.
    if req.subtype:
        sub = norm(req.subtype)
        candidates = [
            r for r in candidates
            if sub in norm(searchable(r))
        ]

    def public(r):
        return {
            "factor_id": r["factor_id"],
            "scope": r["scope"],
            "category_path": r["category_path"],
            "activity": r["activity"],
            "unit": r["unit"],
            "factor": r["factor"],
            "factor_unit": f"kg CO2e per {r['unit']}",
            "year": r["year"],
            "source": r["source"]
        }

    if len(candidates) == 1:
        return {
            "status": "VERIFIED",
            "reason": "Exactly one factor satisfies all supplied deterministic constraints.",
            "match": public(candidates[0])
        }

    if len(candidates) > 1:
        return {
            "status": "REVIEW_REQUIRED",
            "reason": "Multiple compatible factors remain. CarbonGuard will not guess.",
            "match_count": len(candidates),
            "matches": [public(r) for r in candidates[:20]]
        }

    return {
        "status": "FACTOR_NOT_FOUND",
        "reason": "No factor satisfies the supplied deterministic constraints.",
        "match_count": 0,
        "matches": []
    }

class CalculationRequest(BaseModel):
    quantity: float
    factor_value: float
    factor_unit: str
    factor_status: str


@app.post("/calculate")
def calculate_emissions(req: CalculationRequest):

    # Never calculate with an unverified factor
    if req.factor_status != "VERIFIED":
        return {
            "calculation_status": "BLOCKED",
            "reason": "Emission calculation requires a VERIFIED emission factor.",
            "kg_co2e": None,
            "tco2e": None
        }

    # Deterministic calculation
    kg_co2e = req.quantity * req.factor_value
    tco2e = kg_co2e / 1000

    return {
        "calculation_status": "CALCULATED",
        "formula": f"{req.quantity} × {req.factor_value}",
        "quantity": req.quantity,
        "factor_value": req.factor_value,
        "factor_unit": req.factor_unit,
        "kg_co2e": round(kg_co2e, 6),
        "tco2e": round(tco2e, 6)
    }
