"""ChinaTravel 官方 TPCLLM 适配入口。

复制到：chinatravel/agent/tpc_agent/tpc_llm.py

若使用本地 Qwen 等模型，在此类中实现 _get_response。
当前为占位实现，不依赖外部 API（符合比赛离线要求）。
"""

from __future__ import annotations

import os
import sys

_AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = _AGENT_DIR
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

try:
    from agent.llms import AbstractLLM  # type: ignore
except ImportError:

    class AbstractLLM:  # type: ignore[no-redef]
        """独立运行时的 LLM 基类占位。"""

        def __init__(self) -> None:
            self.name = "TPCLLM"


class TPCLLM(AbstractLLM):
    """TPC 比赛 LLM 适配类（占位，可替换为本地模型推理）。"""

    def __init__(self) -> None:
        super().__init__()
        self.name = "TPCLLM"

    def _get_response(self, messages, one_line: bool = False, json_mode: bool = False) -> str:
        """LLM 推理接口（占位）。

        Args:
            messages: 对话消息列表。
            one_line: 是否只返回第一行。
            json_mode: 是否 JSON 模式。

        Returns:
            str: 模型回复文本。
        """
        response = ""
        if json_mode:
            response = "{}"
        if one_line and response:
            response = response.split("\n")[0]
        return response
