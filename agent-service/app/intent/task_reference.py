import re


_CONTEXTUAL_TASK_REFERENCE_PATTERN = re.compile(
    r'(刚才(?:说的|提到的)?任务|上面(?:(?:说的|提到的|这个|那个))?任务|'
    r'那个任务|这个任务|该任务|那项任务|这项任务|它(?!们))'
)
_CONTEXTUAL_TASK_REFERENCES = {
    '那个',
    '这个',
    '刚才的任务',
    '刚才说的任务',
    '刚才提到的任务',
    '上面的任务',
    '上面说的任务',
    '上面提到的任务',
    '上面这个任务',
    '上面那个任务',
    '那个任务',
    '这个任务',
    '该任务',
    '那项任务',
    '这项任务',
    '它',
}


def is_contextual_task_reference(
    reference: str | None,
    message: str,
) -> bool:
    """Return whether a task reference requires short-term context."""

    if reference is not None:
        normalized = re.sub(r'[\s，,。！？!?]', '', reference).casefold()
        return normalized in _CONTEXTUAL_TASK_REFERENCES
    return _CONTEXTUAL_TASK_REFERENCE_PATTERN.search(message) is not None
