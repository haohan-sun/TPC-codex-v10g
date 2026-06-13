"""错误分类。"""

from src.data_layer.schema import ErrorType, TypedError, VerifierError


def parse_errors(errors: list[VerifierError]) -> list[TypedError]:
    """将 verifier 错误转为类型化错误。"""
    return [
        TypedError(
            error_type=e.error_type,
            message=e.message,
            location=e.location,
            repair_hint=f"repair_{e.error_type.value}",
        )
        for e in errors
    ]
