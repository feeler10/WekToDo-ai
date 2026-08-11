import re

from app.schemas.subtask import SubtaskPlan, SubtaskPlanDraft
from app.schemas.task import Task, TaskStatus


class SubtaskPlanValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__('; '.join(errors))


def validate_subtask_plan(
    *,
    parent: Task,
    draft: SubtaskPlanDraft,
    existing_children: list[Task],
    minimum_items: int = 3,
    maximum_items: int = 8,
) -> SubtaskPlan:
    errors: list[str] = []
    warnings: list[str] = []
    items = sorted(draft.items, key=lambda item: item.order)

    if parent.parent_id is not None:
        errors.append('当前版本不支持继续拆解子任务')
    if parent.status == TaskStatus.CANCELLED:
        errors.append('已取消的父任务不能拆解')
    if not minimum_items <= len(items) <= maximum_items:
        errors.append(
            f'子任务数量必须在 {minimum_items} 到 {maximum_items} 之间'
        )

    step_keys = [item.step_key for item in items]
    if len(set(step_keys)) != len(step_keys):
        errors.append('step_key 必须唯一')
    orders = [item.order for item in items]
    if len(set(orders)) != len(orders):
        errors.append('执行顺序必须唯一')
    if orders and orders != list(range(1, len(orders) + 1)):
        errors.append('执行顺序必须从 1 开始且连续')

    normalized_titles = [_normalize_title(item.title) for item in items]
    if len(set(normalized_titles)) != len(normalized_titles):
        errors.append('拆解方案包含重复标题')
    existing_titles = {
        _normalize_title(task.title)
        for task in existing_children
        if task.status != TaskStatus.CANCELLED
    }
    duplicates = sorted(set(normalized_titles).intersection(existing_titles))
    if duplicates:
        errors.append('拆解方案与已有有效子任务重复')

    order_by_key = {item.step_key: item.order for item in items}
    dependency_graph: dict[str, list[str]] = {}
    for item in items:
        dependency_graph[item.step_key] = list(item.depends_on)
        for dependency in item.depends_on:
            dependency_order = order_by_key.get(dependency)
            if dependency_order is None:
                errors.append(
                    f'子任务 {item.step_key} 引用了不存在的依赖 {dependency}'
                )
            elif dependency_order >= item.order:
                errors.append(
                    f'子任务 {item.step_key} 的依赖必须位于它之前'
                )
        if (
            parent.deadline is not None
            and item.deadline is not None
            and item.deadline > parent.deadline
        ):
            errors.append(f'子任务 {item.step_key} 的截止时间晚于父任务')

    if _has_cycle(dependency_graph):
        errors.append('子任务依赖关系不能形成循环')

    estimated = [
        item.estimated_minutes
        for item in items
        if item.estimated_minutes is not None
    ]
    if parent.estimated_minutes and len(estimated) == len(items):
        total = sum(estimated)
        deviation = abs(total - parent.estimated_minutes) / parent.estimated_minutes
        if deviation > 0.5:
            warnings.append(
                '子任务预计总耗时与父任务预计耗时相差超过 50%'
            )

    if errors:
        raise SubtaskPlanValidationError(list(dict.fromkeys(errors)))
    return SubtaskPlan(
        parent_task_id=parent.id,
        parent_version=parent.version,
        summary=draft.summary,
        items=items,
        warnings=warnings,
    )


def _normalize_title(value: str) -> str:
    return re.sub(r'[\W_]+', '', value, flags=re.UNICODE).casefold()


def _has_cycle(graph: dict[str, list[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited or node not in graph:
            return False
        visiting.add(node)
        if any(visit(dependency) for dependency in graph[node]):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)
