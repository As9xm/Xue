import json

try:
    import redis as _redis
    HAS_REDIS = True
except ImportError:
    _redis = None
    HAS_REDIS = False


class RedisQueue:
    def __init__(self, redis_url="redis://localhost:6379", queue_key="xue:queue", visited_key="xue:visited"):
        if not HAS_REDIS:
            raise ImportError("redis package is required for RedisQueue")
        self.client = _redis.from_url(redis_url, decode_responses=True)
        self.queue_key = queue_key
        self.visited_key = visited_key

    def is_visited(self, url):
        return self.client.sismember(self.visited_key, url)

    def mark_visited(self, url):
        self.client.sadd(self.visited_key, url)

    def enqueue(self, url, depth):
        self.client.rpush(self.queue_key, json.dumps({"url": url, "depth": depth}))

    def dequeue(self):
        item = self.client.lpop(self.queue_key)
        if item:
            data = json.loads(item)
            return (data["url"], data["depth"])
        return None

    def queue_size(self):
        return self.client.llen(self.queue_key)

    def visited_count(self):
        return self.client.scard(self.visited_key)
