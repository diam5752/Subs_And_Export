"""Shared types for subtitle processing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


TimeRange = Tuple[float, float, str]


@dataclass
class WordTiming:
    start: float
    end: float
    text: str


@dataclass
class Cue:
    start: float
    end: float
    text: str
    words: Optional[List[WordTiming]] = None
