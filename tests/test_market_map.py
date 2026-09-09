from io import BytesIO

from PIL import Image

from market_map import HEIGHT, WIDTH, render_market_map_png
from tests.test_newsletter import sample_scan


def test_market_map_is_a_valid_email_sized_png():
    payload = render_market_map_png(sample_scan())
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    image = Image.open(BytesIO(payload))
    assert image.size == (WIDTH, HEIGHT)
    assert image.mode == "RGB"
