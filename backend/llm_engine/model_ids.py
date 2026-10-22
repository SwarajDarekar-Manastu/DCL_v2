"""Gemini model ids by tier, read from the settings each time a call is made.

`GEMINI_MODEL` (default gemini-3.8-flash) is the main model; `GEMINI_LITE_MODEL` (default
gemini-3.1-flash-lite, decision 2026-10-22) serves cheap triage and classification. Code names a tier,
never a model id, so switching a model is an environment change.
"""

from enum import StrEnum

from backend.config import get_settings


class Tier(StrEnum):
    FLASH = "flash"
    LITE = "lite"


def model_id(tier: Tier = Tier.FLASH) -> str:
    settings = get_settings()
    return settings.gemini_lite_model if tier is Tier.LITE else settings.gemini_model
