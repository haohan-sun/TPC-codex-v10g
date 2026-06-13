"""ChinaTravel 官方 TPCAgent 适配入口。

复制到官方仓库路径：chinatravel/agent/tpc_agent/tpc_agent.py

接口约定（与 run_tpc.py 一致）::

    agent = TPCAgent(env=..., backbone_llm=..., log_dir=...)
    succ, plan = agent.run(query_dict, prob_idx=uid, oralce_translation=False)
"""

from __future__ import annotations

import os
import sys
from typing import Any

# 确保项目根目录在 sys.path 中（独立运行 & 官方目录均可 import src/）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 优先使用 ChinaTravel 官方 BaseAgent；独立运行时使用 shim
try:
    from agent.base import BaseAgent  # type: ignore  # noqa: F401
except ImportError:
    from src.adapter.base_shim import BaseAgent

from src.adapter.runner import run_single_official_query


class TPCAgent(BaseAgent):
    """TPC 比赛 Agent：薄适配层，内部调用 solve_one_query 主流程。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(name="TPCAgent", **kwargs)

    def run(
        self,
        query: dict,
        prob_idx: str,
        oralce_translation: bool = False,
    ) -> tuple[bool, dict]:
        """官方接口：处理单条 query，返回 (succ, plan_dict)。

        Args:
            query: ChinaTravel query 字典。
            prob_idx: 样本 uid（与文件名一致）。
            oralce_translation: 官方参数名保留拼写；
                                  True=本地 debug 可用 hard_logic_py。

        Returns:
            tuple[bool, dict]:
                succ  - 是否生成非空有效 itinerary
                plan  - 符合 output_schema 的 JSON dict
        """
        self.reset_clock()

        succ, plan = run_single_official_query(
            query=query,
            prob_idx=prob_idx,
            oracle_translation=oralce_translation,
            elapsed_sec=0.0,  # 先占位，下面更新
        )
        plan["elapsed_time(sec)"] = round(self.elapsed_sec(), 3)
        return succ, plan
