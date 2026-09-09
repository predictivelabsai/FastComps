from datetime import date
from decimal import Decimal

import pytest

from fx import parse_ecb_rates


ECB_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube><Cube time="2026-09-08"><Cube currency="HUF" rate="393.20"/>
  <Cube currency="SEK" rate="10.80"/></Cube></Cube>
</gesmes:Envelope>"""


def test_parse_ecb_rates_uses_units_per_eur_and_includes_eur():
    effective, rates = parse_ecb_rates(ECB_SAMPLE)
    assert effective == date(2026, 9, 8)
    assert rates == {"EUR": Decimal("1"), "HUF": Decimal("393.20"), "SEK": Decimal("10.80")}
    assert (Decimal("29000") / rates["HUF"]).quantize(Decimal("0.01")) == Decimal("73.75")


def test_parse_ecb_rates_rejects_empty_feed():
    with pytest.raises(ValueError, match="dated rate table"):
        parse_ecb_rates("<Envelope><Cube/></Envelope>")
