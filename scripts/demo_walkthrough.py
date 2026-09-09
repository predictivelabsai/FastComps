#!/usr/bin/env python3
"""Capture the real FastComps workspace and build the public product-tour GIF."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from dotenv import load_dotenv
from itsdangerous import TimestampSigner


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output" / "playwright" / "demo-frames"
GIF_PATH = ROOT / "static" / "product-demo.gif"
BASE_URL = os.getenv("DEMO_BASE_URL", "http://127.0.0.1:5063").rstrip("/")
VIEWPORT = {"width": 1440, "height": 900}
FRAME_WIDTH = 1200
FRAME_MS = 1800


def session_cookie(secret: str) -> str:
    value = base64.b64encode(
        json.dumps(
            {
                "user": {
                    "id": "fastcomps-product-tour",
                    "email": "demo@fastsme.com",
                    "name": "FastComps Demo",
                    "role": "viewer",
                }
            },
            separators=(",", ":"),
        ).encode()
    )
    return TimestampSigner(secret).sign(value).decode()


def wait_for_server() -> None:
    for _ in range(80):
        try:
            with urlopen(f"{BASE_URL}/healthz", timeout=1) as response:  # noqa: S310 - local capture target
                if response.status == 200:
                    return
        except (URLError, TimeoutError):
            time.sleep(.25)
    raise RuntimeError(f"FastComps did not become ready at {BASE_URL}")


def capture(page) -> list[tuple[str, Path]]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    screens = []

    def shot(label: str, name: str) -> None:
        path = OUTPUT / f"{name}.png"
        page.screenshot(path=str(path))
        screens.append((label, path))
        print(f"captured {label}")

    page.goto(f"{BASE_URL}/", wait_until="networkidle")
    shot("Ask the clinic market", "01-chat")
    page.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded")
    page.wait_for_function("document.querySelector('#sync-status')?.textContent?.includes('Connecting') === false", timeout=45000)
    page.wait_for_timeout(1800)
    shot("Treatment price landscape", "02-treemap")
    for index, (button, label, name) in enumerate(
        (
            ("Competitors", "Verified competitors", "03-competitors"),
            ("Coverage", "Coverage across 30 EEA markets", "04-coverage"),
            ("Evidence", "Retained source evidence", "05-evidence"),
        )
    ):
        page.get_by_role("button", name=button, exact=True).click()
        page.wait_for_timeout(900 if index else 450)
        shot(label, name)
    return screens


def build_gif(shots: list[tuple[str, Path]]) -> None:
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    frames = []
    for label, path in shots:
        frame = Image.open(path).convert("RGB")
        frame = frame.resize((FRAME_WIDTH, round(frame.height * FRAME_WIDTH / frame.width)), Image.Resampling.LANCZOS)
        draw = ImageDraw.Draw(frame)
        bar_height = 42
        draw.rectangle((0, frame.height - bar_height, frame.width, frame.height), fill=(16, 34, 27))
        draw.rectangle((0, frame.height - bar_height, 7, frame.height), fill=(23, 115, 87))
        draw.text((18, frame.height - 31), f"FastComps · {label}", font=font, fill=(255, 255, 255))
        frames.append(frame)
    frames[0].save(
        GIF_PATH,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_MS,
        loop=0,
        optimize=True,
    )
    print(f"wrote {GIF_PATH.relative_to(ROOT)} ({GIF_PATH.stat().st_size // 1024} KB)")


def main() -> int:
    load_dotenv(ROOT / ".env")
    if env_file := os.getenv("DEMO_ENV_FILE"):
        load_dotenv(Path(env_file).expanduser(), override=False)
    secret = os.getenv("SESSION_SECRET", "")
    if not secret:
        raise RuntimeError("SESSION_SECRET is required in the environment or .env")
    own_server = BASE_URL.startswith("http://127.0.0.1:5063") or BASE_URL.startswith("http://localhost:5063")
    server = None
    if own_server:
        server = subprocess.Popen(
            [str(ROOT / ".venv" / "bin" / "python"), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "5063"],
            cwd=ROOT,
            env=os.environ.copy(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    try:
        wait_for_server()
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
            context.add_cookies(
                [
                    {
                        "name": "fastcomps_session",
                        "value": session_cookie(secret),
                        "url": BASE_URL,
                        "httpOnly": True,
                        "sameSite": "Lax",
                    }
                ]
            )
            shots = capture(context.new_page())
            browser.close()
        build_gif(shots)
    finally:
        if server:
            server.terminate()
            try:
                server.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server.kill()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ModuleNotFoundError as exc:
        sys.exit(f"Missing demo dependency: {exc.name}. Install playwright and Pillow in the local virtualenv.")
