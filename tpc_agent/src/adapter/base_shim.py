"""官方 Agent 基类兼容层。

当本项目独立运行时，提供与 ChinaTravel `agent.base.BaseAgent` 兼容的最小接口；
代码被复制到 `chinatravel/agent/tpc_agent/` 后，会优先使用官方 BaseAgent。
"""

from __future__ import annotations

import os
import time
from typing import Any


class BaseAgent:
    """与 ChinaTravel BaseAgent 兼容的最小实现。"""

    def __init__(self, name: str = "TPC", **kwargs: Any) -> None:
        self.name = name
        self.lang = kwargs.get("lang", "zh")
        self.env = kwargs.get("env", None)
        self.log_dir = kwargs.get("log_dir", "logs")
        self.cache_dir = kwargs.get("cache_dir", "cache")
        self.backbone_llm = kwargs.get("backbone_llm", None)
        self.model_name = getattr(self.backbone_llm, "name", "TPCLLM")

        os.makedirs(self.log_dir, exist_ok=True)

        self.llm_inference_time_count = 0
        self.start_clock = 0.0

    def reset_clock(self) -> None:
        """重置计时器（官方 run_tpc 用于统计 elapsed_time）。"""
        self.start_clock = time.time()

    def elapsed_sec(self) -> float:
        """返回自 reset_clock 以来经过的秒数。"""
        if self.start_clock <= 0:
            return 0.0
        return time.time() - self.start_clock

    def run(self, query: dict, prob_idx: str, oralce_translation: bool = False) -> tuple[bool, dict]:
        """子类必须实现。返回 (succ, plan_dict)。"""
        raise NotImplementedError
