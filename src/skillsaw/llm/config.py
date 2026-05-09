"""LLM configuration — model selection, budget, iteration caps."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class EngineConfig:
    model: str = "minimax/minimax-m2.5:free"
    max_tokens: int = 4096
    max_iterations: int = 5
    max_total_tokens: int = 500_000
    confirm: bool = True

    def __post_init__(self):
        env_model = os.environ.get("SKILLSAW_MODEL")
        if env_model:
            self.model = env_model
