from contextlib import AbstractAsyncContextManager

from langgraph.checkpoint.redis.aio import AsyncRedisSaver


def create_redis_checkpointer(
    redis_url: str,
    *,
    key_prefix: str = 'wektodo',
) -> AbstractAsyncContextManager[AsyncRedisSaver]:
    return AsyncRedisSaver.from_conn_string(
        redis_url,
        checkpoint_prefix=f'{key_prefix}:checkpoint',
        checkpoint_write_prefix=f'{key_prefix}:checkpoint_write',
    )
