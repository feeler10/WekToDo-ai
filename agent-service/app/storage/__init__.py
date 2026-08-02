'''External storage clients.'''

from app.storage.redis_client import create_redis_client

__all__ = ['create_redis_client']
