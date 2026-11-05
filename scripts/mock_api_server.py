"""Local mock of 'https://api.example.com' used by the Q2 load simulation.

api.example.com is a reserved placeholder domain that does not serve these routes, and
flooding a real public API would be abusive. This server reproduces realistic conditions
instead: variable latency and random 429 / 500 / 503 errors on /data1, /data2, /data3.

Run standalone:  python -m scripts.mock_api_server --port 8081
"""

import argparse
import asyncio
import random

from aiohttp import web

# Failure probabilities injected on each request (roughly 4% of responses fail).
ERROR_RATES = {429: 0.01, 500: 0.01, 503: 0.02}
LATENCY_RANGE = (0.005, 0.050)  # seconds, simulates network + processing time


async def handle_data(request: web.Request) -> web.Response:
    await asyncio.sleep(random.uniform(*LATENCY_RANGE))

    roll = random.random()
    for status, rate in ERROR_RATES.items():
        if roll < rate:
            # 429 comes with a Retry-After hint, like real rate-limited APIs.
            headers = {"Retry-After": "1"} if status == 429 else None
            return web.json_response({"error": status}, status=status, headers=headers)
        roll -= rate

    route = request.match_info["name"]
    return web.json_response({"route": route, "value": random.randint(0, 1000)})


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/{name:data[1-3]}", handle_data)
    return app


def serve(port: int) -> None:
    web.run_app(build_app(), host="127.0.0.1", port=port, print=None, access_log=None)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8081)
    serve(parser.parse_args().port)
