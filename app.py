from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Optional
import json
import re
import math


app = FastAPI(
    title="CarbonGuard Factor Lookup API",
    version="1.0.0",
    description=(
        "Deterministic lookup of verified UK Government "
        "GHG Conversion Factors 2026 and deterministic CO2e calculation."
    )
)


# ============================================================
# LOAD VERIFIED EMISSION FACTORS
# ============================================================

with open("factors.json", "r", encoding="utf-8") as f:
    FACTORS = json.load(f)


# ============================================================
# NORMALIZATION HELPERS
# ============================================================

def norm(s: Optional[str]) -> str:
    """
    Normalize text for deterministic comparisons.
    """
    if not s:
        return ""

    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9%./() -]+", " ", s)
    s = re.sub(r"\s+", " ", s)

    return s


def contains_norm(haystack: str, needle: str) -> bool:
    """
    Deterministic normalized substring check.
    """
    return norm(needle) in norm(haystack)


def searchable(r):
    """
    Build deterministic searchable text from the official
    category path and activity.
    """
    return " | ".join(
        r["category_path"] + [r["activity"]]
    )


# ============================================================
# FACTOR LOOKUP REQUEST
# ============================================================

class LookupRequest(BaseModel):
    scope: str = Field(
        ...,
        description="Scope 1, Scope 2, or Scope 3"
    )

    activity: str = Field(
        ...,
        description=(
            "Activity or fuel name. "
            "Use the official factor activity when known."
        )
    )

    unit: str = Field(
        ...,
        description=(
            "Activity data unit, e.g. litres, kWh, km, miles"
        )
    )

    year: int = Field(
        2026,
        description="Factor year"
    )

    category: Optional[str] = Field(
        None,
        description=(
            "Optional official category, "
            "e.g. Liquid fuels"
        )
    )

    subtype: Optional[str] = Field(
        None,
        description=(
            "Optional exact subtype such as "
            "100% mineral diesel"
        )
    )

    fuel_subtype: Optional[str] = Field(
        None,
        description=(
            "Optional fuel subtype supplied by "
            "external tools such as Lyzr"
        )
    )


# ============================================================
# ROOT / HEALTH ENDPOINT
# ============================================================

@app.get("/")
def root():
    return {
        "service": "CarbonGuard Factor Lookup API",
        "status": "ok",
        "factor_records": len(FACTORS)
    }


# ============================================================
# DETERMINISTIC EMISSION FACTOR LOOKUP
# ============================================================

@app.post("/lookup-factor")
def lookup_factor(req: LookupRequest):

    # --------------------------------------------------------
    # STEP 1: HARD CONSTRAINTS
    # Year + Scope + Unit
    # --------------------------------------------------------

    candidates = [
        r
        for r in FACTORS
        if r["year"] == req.year
        and norm(r["scope"]) == norm(req.scope)
        and norm(r["unit"]) == norm(req.unit)
    ]


    # --------------------------------------------------------
    # STEP 2: CATEGORY CONSTRAINT
    # --------------------------------------------------------

    if req.category:

        cat = norm(req.category)

        candidates = [
            r
            for r in candidates
            if any(
                cat == norm(part)
                for part in r["category_path"]
            )
        ]


    # --------------------------------------------------------
    # STEP 3: ACTIVITY MATCHING
    #
    # Exact activity/category match is preferred.
    # If no exact match exists, deterministic phrase
    # containment is used.
    # --------------------------------------------------------

    activity = norm(req.activity)

    if activity:

        exact = [
            r
            for r in candidates
            if (
                norm(r["activity"]) == activity
                or any(
                    norm(part) == activity
                    for part in r["category_path"]
                )
            )
        ]

        if exact:
            candidates = exact

        else:

            contained = [
                r
                for r in candidates
                if activity in norm(searchable(r))
            ]

            candidates = contained


    # --------------------------------------------------------
    # STEP 4: SUBTYPE CONSTRAINT
    #
    # Supports BOTH:
    #   subtype
    #   fuel_subtype
    #
    # This makes the API compatible with Lyzr's
    # "fuel_subtype" parameter.
    # --------------------------------------------------------

    subtype_value = req.subtype or req.fuel_subtype

    if subtype_value:

        sub = norm(subtype_value)

        candidates = [
            r
            for r in candidates
            if (
                sub in norm(r["activity"])
                or any(
                    sub in norm(part)
                    for part in r["category_path"]
                )
            )
        ]


    # --------------------------------------------------------
    # PUBLIC FACTOR REPRESENTATION
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # STEP 5: EXACTLY ONE MATCH
    # --------------------------------------------------------

    if len(candidates) == 1:

        return {
            "status": "VERIFIED",
            "reason": (
                "Exactly one factor satisfies all "
                "supplied deterministic constraints."
            ),
            "match": public(candidates[0])
        }


    # --------------------------------------------------------
    # STEP 6: MULTIPLE MATCHES
    # --------------------------------------------------------

    if len(candidates) > 1:

        return {
            "status": "REVIEW_REQUIRED",
            "reason": (
                "Multiple compatible factors remain. "
                "CarbonGuard will not guess."
            ),
            "match_count": len(candidates),
            "matches": [
                public(r)
                for r in candidates[:20]
            ]
        }


    # --------------------------------------------------------
    # STEP 7: NO MATCH
    # --------------------------------------------------------

    return {
        "status": "FACTOR_NOT_FOUND",
        "reason": (
            "No factor satisfies the supplied "
            "deterministic constraints."
        ),
        "match_count": 0,
        "matches": []
    }


# ============================================================
# DETERMINISTIC CALCULATOR REQUEST
# ============================================================

class CalculationRequest(BaseModel):

    quantity: float = Field(
        ...,
        description="Activity quantity."
    )

    factor_value: float = Field(
        ...,
        description="Verified emission factor value."
    )

    factor_unit: str = Field(
        ...,
        description="Unit of the verified emission factor."
    )

    factor_status: str = Field(
        ...,
        description=(
            "Factor verification status. "
            "Calculation is permitted only for VERIFIED."
        )
    )


# ============================================================
# DETERMINISTIC EMISSIONS CALCULATOR
# ============================================================

@app.post("/calculate")
def calculate_emissions(req: CalculationRequest):

    # --------------------------------------------------------
    # SAFETY CHECK 1:
    # FACTOR MUST BE VERIFIED
    # --------------------------------------------------------

    if req.factor_status != "VERIFIED":

        return {
            "calculation_status": "BLOCKED",
            "reason": (
                "Emission calculation requires "
                "a VERIFIED emission factor."
            ),
            "kg_co2e": None,
            "tco2e": None
        }


    # --------------------------------------------------------
    # SAFETY CHECK 2:
    # QUANTITY MUST BE FINITE AND NON-NEGATIVE
    # --------------------------------------------------------

    if not math.isfinite(req.quantity):

        return {
            "calculation_status": "BLOCKED",
            "reason": "Quantity must be a finite number.",
            "kg_co2e": None,
            "tco2e": None
        }


    if req.quantity < 0:

        return {
            "calculation_status": "BLOCKED",
            "reason": "Quantity cannot be negative.",
            "kg_co2e": None,
            "tco2e": None
        }


    # --------------------------------------------------------
    # SAFETY CHECK 3:
    # FACTOR MUST BE FINITE AND NON-NEGATIVE
    # --------------------------------------------------------

    if not math.isfinite(req.factor_value):

        return {
            "calculation_status": "BLOCKED",
            "reason": "Emission factor must be a finite number.",
            "kg_co2e": None,
            "tco2e": None
        }


    if req.factor_value < 0:

        return {
            "calculation_status": "BLOCKED",
            "reason": "Emission factor cannot be negative.",
            "kg_co2e": None,
            "tco2e": None
        }


    # --------------------------------------------------------
    # DETERMINISTIC CALCULATION
    # --------------------------------------------------------

    kg_co2e = req.quantity * req.factor_value

    tco2e = kg_co2e / 1000


    # --------------------------------------------------------
    # CALCULATION RESULT
    # --------------------------------------------------------

    return {

        "calculation_status": "CALCULATED",

        "formula": (
            f"{req.quantity} × {req.factor_value}"
        ),

        "quantity": req.quantity,

        "factor_value": req.factor_value,

        "factor_unit": req.factor_unit,

        "kg_co2e": round(
            kg_co2e,
            6
        ),

        "tco2e": round(
            tco2e,
            6
        )
    }
