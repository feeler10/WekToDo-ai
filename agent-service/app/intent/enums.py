from enum import Enum


class IntentType(str, Enum):
    CREATE_TASK = 'CREATE_TASK'
    QUERY_TASKS = 'QUERY_TASKS'
    UPDATE_TASK = 'UPDATE_TASK'
    UPDATE_TASK_STATUS = 'UPDATE_TASK_STATUS'
    DECOMPOSE_TASK = 'DECOMPOSE_TASK'
    GENERAL_CHAT = 'GENERAL_CHAT'
    UNKNOWN = 'UNKNOWN'


class IntentClassifierProvider(str, Enum):
    LLM = 'llm'
    RULE = 'rule'
    SEMANTIC = 'semantic'
    HYBRID = 'hybrid'
