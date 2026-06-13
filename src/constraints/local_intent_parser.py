"""本地意图解析器接口（离线）。

设计原则：
- 默认使用规则引擎 (RuleIntentParser)，不依赖外部 API。
- 可选接入本地小模型或 sentence-transformers 时，必须离线运行。
- 输出统一为 ConstraintCard 列表。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.data_layer.schema import ConstraintCard


class LocalIntentParser(ABC):
    """离线意图解析器基类。

    子类实现 parse()，返回约束卡片列表。
    """

    @abstractmethod
    def parse(self, text: str) -> list[ConstraintCard]:
        """将自然语言查询解析为约束卡片列表。"""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """解析器名称（用于日志/调试）。"""
        ...

    def batch_parse(self, texts: list[str]) -> list[list[ConstraintCard]]:
        """批量解析，默认依次调用 parse()。"""
        return [self.parse(t) for t in texts]


class RuleIntentParser(LocalIntentParser):
    """基于规则/词典的本地 NL 解析器。

    从 lexicons/ 加载词典，使用正则 + 关键字匹配提取约束卡片。
    是当前默认解析器，不依赖任何外部模型或 API。
    """

    def __init__(self) -> None:
        self._name = "RuleIntentParser"

    @property
    def name(self) -> str:
        return self._name

    def parse(self, text: str) -> list[ConstraintCard]:
        from src.constraints.nl_parser import parse_nature_language

        return parse_nature_language(text)


class FallbackIntentParser(LocalIntentParser):
    """兜底解析器：返回空卡片列表。

    当模型路径不可用或加载失败时使用。
    """

    def __init__(self) -> None:
        self._name = "FallbackIntentParser"

    @property
    def name(self) -> str:
        return self._name

    def parse(self, text: str) -> list[ConstraintCard]:
        return []


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

def get_intent_parser(backend: str = "rule", **kwargs: Any) -> LocalIntentParser:
    """根据配置创建意图解析器。

    Args:
        backend: "rule" | "fallback" | 未来扩展 "sentence-transformers"
        **kwargs: 传给具体解析器的参数。

    Returns:
        LocalIntentParser 实例。
    """
    if backend == "rule":
        return RuleIntentParser()
    if backend == "fallback":
        return FallbackIntentParser()
    # 未来扩展：sentence-transformers / local-llm
    raise ValueError(f"Unknown intent parser backend: {backend}")


def get_default_parser() -> LocalIntentParser:
    """返回默认解析器（规则引擎）。"""
    return RuleIntentParser()
