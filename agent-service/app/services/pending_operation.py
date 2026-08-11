import re
from collections.abc import Iterable, Sequence


_COMMON_CANCELLATIONS = frozenset({'取消', '算了', '不用了'})
_EXPLICIT_NEW_REQUEST_PATTERN = re.compile(
    r'^\s*(查询|查看|列出|删除|删掉|移除|彻底删除|拆解|分解|你好|帮助)'
)
_EXPLICIT_STATUS_REQUEST_PATTERN = re.compile(
    r'^\s*(把|将).+(标记为|设为)(待办|进行中|完成|已完成|阻塞|取消)'
)


def format_pending_operation_inputs(
    user_inputs: Sequence[str],
    *,
    operation_label: str,
) -> str:
    normalized = [item.strip() for item in user_inputs if item.strip()]
    if not normalized:
        return ''
    if len(normalized) == 1:
        return normalized[0]
    lines = [
        f'以下是用户对同一个{operation_label}的连续补充。请综合全部信息，'
        '后面轮次中的明确修正覆盖前面冲突内容：'
    ]
    lines.extend(
        f'[第{index}轮] {message}'
        for index, message in enumerate(normalized, start=1)
    )
    return '\n'.join(lines)


def is_pending_operation_cancellation(
    message: str,
    *,
    additional_messages: Iterable[str] = (),
) -> bool:
    normalized = re.sub(r'[\s，,。！？!?]', '', message)
    return normalized in (_COMMON_CANCELLATIONS | frozenset(additional_messages))


def looks_like_explicit_new_operation(
    message: str,
    *,
    replacement_prefixes: Sequence[str] = (),
) -> bool:
    normalized = message.strip()
    return bool(
        _EXPLICIT_NEW_REQUEST_PATTERN.search(normalized)
        or _EXPLICIT_STATUS_REQUEST_PATTERN.search(normalized)
        or '有哪些任务' in normalized
        or '什么任务' in normalized
        or normalized.startswith(tuple(replacement_prefixes))
    )
