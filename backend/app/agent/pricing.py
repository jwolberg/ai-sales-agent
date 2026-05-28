"""Price table — deterministic, leaf-keyed price lookup (IR1-T1, R6, R6b).

The intent router's endpoint is quoting a price. Prices are an **exact lookup keyed by the
classification leaf** — never retrieved fuzzily, never generated. ``quote_price`` returns the
authoritative :class:`PriceRecord` for a leaf, or ``None`` (the caller then gives the honest
fallback / asks one more question — R6b). The numbers loaded here are also the source of truth the
mis-quote guardrail (IR1-T2) checks the agent's output against.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.agent.taxonomy import Leaf, is_valid_leaf_id

# backend/app/agent/pricing.py -> repo root is four levels up.
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PRICING = REPO_ROOT / "data" / "pricing" / "pricing.yaml"


@dataclass(frozen=True)
class PriceRecord:
    """One leaf's authoritative price."""

    leaf_id: str
    amount: float
    unit: str
    currency: str
    summary: str
    approved: bool

    @property
    def display(self) -> str:
        """A short canonical money string, e.g. '$85'."""
        # Whole dollars render without a trailing .0; keep cents otherwise.
        if float(self.amount).is_integer():
            return f"${int(self.amount)}"
        return f"${self.amount:.2f}"

    def spoken(self) -> str:
        """What the agent says — the curated summary if present, else a built phrase."""
        return self.summary or f"That's {self.display} {self.unit}."


class PriceBook:
    """The leaf -> PriceRecord table, loaded from YAML."""

    def __init__(self, records: dict[str, PriceRecord]) -> None:
        self._records = records

    @classmethod
    def load(cls, path: Path | str = DEFAULT_PRICING) -> PriceBook:
        data = yaml.safe_load(Path(path).read_text()) or {}
        currency = data.get("currency", "USD")
        approved = bool(data.get("approved", False))
        records: dict[str, PriceRecord] = {}
        for leaf_id, row in (data.get("leaves") or {}).items():
            if not is_valid_leaf_id(leaf_id):
                # Guard against a price keyed to a leaf the taxonomy doesn't define.
                raise ValueError(f"pricing.yaml has unknown leaf id: {leaf_id!r}")
            records[leaf_id] = PriceRecord(
                leaf_id=leaf_id,
                amount=float(row["amount"]),
                unit=str(row["unit"]),
                currency=currency,
                summary=str(row.get("summary", "")),
                approved=approved,
            )
        return cls(records)

    def get(self, leaf_id: str) -> PriceRecord | None:
        """Exact lookup. Returns None for a leaf with no priced entry (R6b)."""
        return self._records.get(leaf_id)

    def leaf_ids(self) -> list[str]:
        return list(self._records.keys())


@lru_cache
def get_pricebook() -> PriceBook:
    """Process-wide singleton price table."""
    return PriceBook.load()


def quote_price(leaf: Leaf | str, *, pricebook: PriceBook | None = None) -> PriceRecord | None:
    """Return the authoritative price for a fully-resolved leaf, or None.

    Accepts a :class:`Leaf` or its id. None means "no priced record" — the caller must give the
    honest fallback rather than invent a number (R6b). A non-leaf / unknown id also yields None.
    """
    leaf_id = leaf.id if isinstance(leaf, Leaf) else str(leaf)
    if not is_valid_leaf_id(leaf_id):
        return None
    book = pricebook or get_pricebook()
    return book.get(leaf_id)
