from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class TaskIntent(str, Enum):
    CREATE_TASK = 'CREATE_TASK'
    QUERY_TASK = 'QUERY_TASK'
    UPDATE_TASK = 'UPDATE_TASK'
    UNKNOWN = 'UNKNOWN'


@dataclass(frozen=True)
class IntentClassification:
    intent: TaskIntent
    confidence: float


class IntentClassifier(Protocol):
    def classify(self, user_message: str) -> IntentClassification: ...


class KeywordIntentClassifier:
    _QUERY_KEYWORDS = (
        '查询',
        '查看',
        '哪些',
        '还有什么',
        '什么任务',
        '今天的任务',
        '今日任务',
        '逾期任务',
    )
    _UPDATE_KEYWORDS = (
        '完成了',
        '做完了',
        '更新状态',
        '标记为',
        '阻塞了',
        '取消了',
        '开始了',
        '重新开始',
    )
    _CREATE_KEYWORDS = ('创建', '新增', '添加', '安排', '新任务')

    def classify(self, user_message: str) -> IntentClassification:
        message = user_message.strip()
        if not message:
            return IntentClassification(TaskIntent.UNKNOWN, 0.0)
        if any(keyword in message for keyword in self._QUERY_KEYWORDS):
            return IntentClassification(TaskIntent.QUERY_TASK, 1.0)
        if any(keyword in message for keyword in self._UPDATE_KEYWORDS):
            return IntentClassification(TaskIntent.UPDATE_TASK, 1.0)
        if any(keyword in message for keyword in self._CREATE_KEYWORDS):
            return IntentClassification(TaskIntent.CREATE_TASK, 1.0)
        return IntentClassification(TaskIntent.UNKNOWN, 0.0)
