"""错误统计。"""

from src.data_layer.schema import VerifierError


def aggregate_errors(errors_list: list[list[VerifierError]]) -> dict[str, int]:
    """汇总多轮 verifier 错误分布。

    Args:
        errors_list: 各轮错误列表。

    Returns:
        dict[str, int]: 错误类型 → 计数。
    """
    raise NotImplementedError
