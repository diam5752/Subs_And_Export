"""Shared types for subtitle processing."""

from __future__ import annotations

from dataclasses import dataclass

TimeRange = tuple[float, float, str]


@dataclass(slots=True)
class WordTiming:
    start: float
    end: float
    text: str


@dataclass(slots=True)
class Cue:
    start: float
    end: float
    text: str
    words: list[WordTiming] | None = None
