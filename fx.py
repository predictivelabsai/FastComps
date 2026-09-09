"""Auditable ECB reference-rate ingestion and EUR conversion helpers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

import httpx

from db import SCHEMA, connection


ECB_DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


def parse_ecb_rates(xml: str | bytes) -> tuple[date, dict[str, Decimal]]:
    """Parse units of each currency per EUR from the ECB daily XML feed."""
    root = ElementTree.fromstring(xml)
    effective_date: date | None = None
    rates: dict[str, Decimal] = {"EUR": Decimal("1")}
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "Cube":
            continue
        if element.attrib.get("time"):
            effective_date = date.fromisoformat(element.attrib["time"])
        currency = element.attrib.get("currency", "").upper()
        value = element.attrib.get("rate")
        if not currency or not value:
            continue
        try:
            rate = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid ECB rate for {currency}") from exc
        if rate <= 0:
            raise ValueError(f"Non-positive ECB rate for {currency}")
        rates[currency] = rate
    if effective_date is None or len(rates) < 2:
        raise ValueError("ECB feed did not contain a dated rate table")
    return effective_date, rates


def fetch_ecb_rates() -> tuple[date, dict[str, Decimal]]:
    response = httpx.get(ECB_DAILY_URL, timeout=20, follow_redirects=True)
    response.raise_for_status()
    return parse_ecb_rates(response.content)


def sync_exchange_rates() -> dict[str, object]:
    effective_date, rates = fetch_ecb_rates()
    with connection() as conn, conn.cursor() as cur:
        cur.executemany(
            f"""INSERT INTO {SCHEMA}.exchange_rates
                (currency,units_per_eur,effective_date,source_url)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (currency) DO UPDATE SET
                  units_per_eur=EXCLUDED.units_per_eur,effective_date=EXCLUDED.effective_date,
                  source_url=EXCLUDED.source_url,updated_at=NOW()""",
            [(currency, rate, effective_date, ECB_DAILY_URL) for currency, rate in rates.items()],
        )
        conn.commit()
    return {"effective_date": effective_date.isoformat(), "currencies": len(rates), "source_url": ECB_DAILY_URL}
