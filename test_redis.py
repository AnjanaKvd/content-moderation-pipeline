import redis.asyncio as redis
import asyncio


async def test():
    r = redis.Redis(
        host="ContentModerate.redis.cache.windows.net",
        port=6380,
        password="[PASSWORD]",
        ssl=True,
        ssl_cert_reqs=None,
    )
    try:
        res = await r.ping()
        print(f"Ping result: {res}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await r.aclose()


asyncio.run(test())
