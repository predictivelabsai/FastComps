"""Evidence-grounded public market assistant."""

from __future__ import annotations

import json

import httpx

from config import XAI_API_KEY, XAI_BASE_URL, XAI_MODEL
from repository import assistant_context


def _fallback(context: dict) -> str:
    stats = context["overview"]
    place = context["country"]
    answer = (f"For {place}, FastComps currently tracks {stats['competitors']} verified competitors, "
              f"{stats['locations']} clinic locations and {stats['observations']} source-backed observations. ")
    if context["observations"]:
        priced = [o for o in context["observations"] if o["price_min"] is not None]
        if priced:
            low = min(priced, key=lambda x: x["price_min"])
            answer += (f"A recent price example is {low['competitor']} — {low['offering']} at "
                       f"{low['price_type']} {low['price_min']:g} {low['currency'] or ''}. ")
    answer += "Use the cited evidence links to verify each claim; incomplete countries remain marked as such."
    return answer


def answer(question: str, country: str | None = None) -> dict:
    context = assistant_context(question, country)
    observations = context["observations"][:8]
    citations = [{"label": f"{o['competitor']} — {o['offering']}", "url": o["source_url"]}
                 for o in observations if o.get("source_url")]
    # Keep unique URLs while retaining ranking.
    citations = list({c["url"]: c for c in citations}.values())[:6]
    if not XAI_API_KEY:
        return {"answer": _fallback(context), "citations": citations, "model": "deterministic"}
    system = """You are the FastComps clinics competitive-intelligence analyst. Answer only from the JSON evidence supplied. Distinguish exact, from, range and unavailable prices. Never imply complete market coverage when coverage_status is not covered. Be concise, state uncertainty, and do not provide medical advice. Do not invent URLs or facts."""
    payload = {
        "model": XAI_MODEL,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False, default=str)},
        ],
    }
    try:
        response = httpx.post(f"{XAI_BASE_URL}/chat/completions", headers={
            "Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json",
        }, json=payload, timeout=35)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return {"answer": content, "citations": citations, "model": XAI_MODEL}
    except Exception:
        return {"answer": _fallback(context), "citations": citations, "model": "deterministic-fallback"}
