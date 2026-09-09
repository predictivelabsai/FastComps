"""Session-based UI internationalisation for English, Estonian and Lithuanian."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


DEFAULT_LANG = "en"
LANGUAGES = {
    "en": {"name": "English", "native": "English", "flag": "🇬🇧"},
    "et": {"name": "Estonian", "native": "Eesti", "flag": "🇪🇪"},
    "lt": {"name": "Lithuanian", "native": "Lietuvių", "flag": "🇱🇹"},
}
SUPPORTED_LANGS = frozenset(LANGUAGES)
LOCALES_DIR = Path(__file__).resolve().parent / "locales"


@lru_cache(maxsize=None)
def catalog(lang: str) -> dict[str, str]:
    if lang == DEFAULT_LANG or lang not in SUPPORTED_LANGS:
        return {}
    try:
        value = json.loads((LOCALES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def detect_language(request) -> str:
    header = (getattr(request, "headers", {}) or {}).get("accept-language", "")
    preferences: list[tuple[float, int, str]] = []
    for index, item in enumerate(header.split(",")):
        parts = item.strip().split(";")
        code = parts[0].split("-")[0].lower()
        quality = 1.0
        for parameter in parts[1:]:
            if parameter.strip().startswith("q="):
                try:
                    quality = float(parameter.strip()[2:])
                except ValueError:
                    quality = 0.0
        if quality > 0:
            preferences.append((quality, -index, code))
    for _, _, code in sorted(preferences, reverse=True):
        if code in SUPPORTED_LANGS:
            return code
    return DEFAULT_LANG


def get_lang(session: dict[str, Any], request=None) -> str:
    code = str(session.get("lang") or "").lower()
    if code in SUPPORTED_LANGS:
        return code
    code = detect_language(request) if request is not None else DEFAULT_LANG
    session["lang"] = code
    return code


def set_lang(session: dict[str, Any], lang: str) -> str:
    if (code := (lang or "").lower()) in SUPPORTED_LANGS:
        session["lang"] = code
    return get_lang(session)


def safe_return_path(value: str | None) -> str:
    value = value or "/"
    parsed = urlsplit(value)
    decoded = unquote(parsed.path)
    decoded_value = unquote(value)
    if (parsed.scheme or parsed.netloc or not decoded.startswith("/") or decoded.startswith("//")
            or "\\" in decoded_value or any(ord(char) < 32 for char in decoded_value)):
        return "/"
    suffix = (f"?{parsed.query}" if parsed.query else "") + (f"#{parsed.fragment}" if parsed.fragment else "")
    return parsed.path + suffix


def t(text: str, lang: str = DEFAULT_LANG, **values: Any) -> str:
    translated = text if lang == DEFAULT_LANG else catalog(lang).get(text, text)
    if not values:
        return translated
    try:
        return translated.format(**values)
    except (KeyError, ValueError):
        return text.format(**values)


def js_catalog(lang: str) -> dict[str, str]:
    return dict(catalog(lang))


def localize_tree(value: Any, lang: str) -> Any:
    """Translate only catalogued literals, preserving all source and user data."""
    if lang == DEFAULT_LANG:
        return value
    translations = catalog(lang)
    try:
        from fastcore.basics import NotStr
        from fastcore.xml import FT
    except ImportError:  # pragma: no cover
        return value

    def walk(node: Any) -> Any:
        if isinstance(node, FT):
            node.children = tuple(walk(child) for child in node.children)
            for attr in ("placeholder", "title", "alt", "aria-label", "aria_label"):
                raw = node.attrs.get(attr)
                if isinstance(raw, str) and raw in translations:
                    node.attrs[attr] = translations[raw]
            return node
        if isinstance(node, NotStr):
            return node
        if isinstance(node, str):
            return translations.get(node, node)
        if isinstance(node, tuple):
            return tuple(walk(item) for item in node)
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(value)
