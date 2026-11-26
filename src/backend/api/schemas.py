"""Pydantic v2 request schemas matching schemas/openapi.yaml."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.backend.config import MAX_BROWSER_FRAME_B64_CHARS


class BrowserDualFrameRequest(BaseModel):
    """Request payload for /api/camera/browser-frame."""

    model_config = ConfigDict(extra="forbid")

    cam1_image: str | None = Field(
        default=None,
        max_length=MAX_BROWSER_FRAME_B64_CHARS,
    )
    cam2_image: str | None = Field(
        default=None,
        max_length=MAX_BROWSER_FRAME_B64_CHARS,
    )


class ResolveAlertRequest(BaseModel):
    """Request payload for /api/camera/resolve-alert."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject"]
