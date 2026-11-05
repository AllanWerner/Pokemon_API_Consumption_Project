# Pokemon_API_Consumption_Project

Consumption of the [PokéAPI](https://pokeapi.co/) with a Flask REST API, an interactive CLI and a Streamlit front end.

## Features

- **Pokémon stats** — readable summary of a Pokémon (types, size, base stats)
- **Comparison** — two Pokémon stat by stat, stronger one in HP / Attack / overall
- **Type statistics** — number of Pokémon, average / min / max HP, strongest Pokémon, pure vs dual type
- **Battle** — 5-turn fight based on base stats (speed order, type effectiveness, STAB, seeded randomness, KO ends the fight)
- **Q1** — resilient requests: retries with exponential backoff for 429 / 5xx / network errors, immediate failure for 400 / 401 / 403 / 404
- **Q2** — async client (`asyncio` + `aiohttp`) for very high request volumes, load simulation on `api.example.com/data1..3`
- **Q3** — in-memory cache with 1-hour expiry, LRU bound and request coalescing
- **Streamlit** — front end displaying every feature through the Flask API, with an API call log

## Installation

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt      # Windows (Git Bash)
```

## Usage

```bash
# Flask API (http://127.0.0.1:5000)
.venv/Scripts/python app.py

# Streamlit front end (http://localhost:8501) — needs the Flask API running
.venv/Scripts/streamlit run streamlit_app.py

# Interactive command-line menu
.venv/Scripts/python cli.py
```

### Flask routes

| Route | Description |
|---|---|
| `GET /pokemon/<name_or_id>` | Pokémon summary |
| `GET /compare/<first>/<second>` | Comparison of two Pokémon |
| `GET /types` | All available types |
| `GET /type/<type>` | Statistics of a type |
| `GET /battle/<first>/<second>?seed=<int>` | Battle simulation |
| `GET /cache/stats` · `POST /cache/clear` | Cache metrics / reset |
| `GET /demo/resilience` | Q1 simulated failure scenarios |
| `GET /demo/load?total=&concurrency=&cache=0\|1` | Q2/Q3 load test on mock routes |

## Demos and tests

```bash
.venv/Scripts/python -m pytest -q                                   # unit tests
.venv/Scripts/python -m scripts.q1_error_handling_demo              # Q1
.venv/Scripts/python -m scripts.q2_load_simulation --total 1000000  # Q2
.venv/Scripts/python -m scripts.q3_cache_demo                       # Q3
```

## Performance

Measured on a local Windows 11 machine (Python 3.12, 12 logical CPUs). Times against the real PokéAPI
depend on the network; load tests use local mock backends (5–50 ms latency, ~4 % injected 429/500/503 errors).

### Real PokéAPI

| Operation | Without optimisation | Async (Q2) | Cache hit (Q3) |
|---|---|---|---|
| `GET /pokemon/pikachu` | 231 ms | — | **0.15 ms** (×1 500) |
| Type statistics `fire` (~110 API calls) | 2.4 s (sequential) | 0.3 – 0.9 s | **2.4 ms** |
| Streamlit: `GET /type/normal` through Flask | — | 878 ms (cold cache) | **34 ms** (incl. HTTP to Flask) |

### Q1 · Resilience

| Scenario | Attempts | Outcome |
|---|---|---|
| 500 → 503 → 200 | 3 | success after 2 backoff pauses |
| 429 with `Retry-After: 1` → 200 | 2 | success after exactly 1 s |
| Timeout → connection error → 200 | 3 | success |
| 503 persisting | 4 (1 + 3 retries) | `ServerError` |
| 401 / 404 | 1 | immediate failure, no retry |
| Invalid ID (`-5`) | 0 | rejected locally (400) |

### Q2 · High load (`api.example.com/data1..3`, one backend process per route)

| Run | Requests | Duration | Throughput | Result |
|---|---|---|---|---|
| Sequential (Q1 client) | 300 | 17.7 s | 17 req/s | baseline |
| Async, concurrency 300 | 300 | 1.2 s | 252 req/s | **×15 faster** |
| Async, concurrency 300 | **1 000 000** | 158 s | **~6 300 req/s** | 999 997 succeeded (99.9997 %), 41 699 retries, 3 failures after 4 attempts |

Memory stays flat during the 1M run: URLs are generated lazily and consumed by a fixed pool of workers
through a bounded queue; results are streamed to a callback instead of being stored.
From the Streamlit tab (mock server and client in the same Flask process), throughput is ~1 700 req/s.

### Q3 · Cache under load (30 000 requests on 3 routes)

| Mode | Duration | HTTP calls actually sent |
|---|---|---|
| No cache (Q2 client) | 5.75 s | 31 192 |
| Request coalescing only | 5.40 s | 271 |
| **1 h cache + coalescing** | **0.15 s** | **3** |

Cache expiry checked with a simulated clock: reads at 0, 1, 30, 59.9, 60.1 and 75 min → only
**2 HTTP calls** (at 0 min and at 60.1 min, after expiry).

## Project structure

```
app.py                  Flask REST API
cli.py                  Interactive command-line menu
streamlit_app.py        Streamlit front end (consumes the Flask API)
pokemon/
  api_client.py         PokéAPI access (validation, shared cache)
  services.py           Stats, comparison, type statistics
  battle.py             Battle simulation engine
  resilient_http.py     Q1 - retries and error handling
  async_http.py         Q2 - async client for high load
  cache.py              Q3 - TTL cache
  errors.py             Custom exceptions
scripts/                Demo and load-simulation scripts
tests/                  Unit tests
```
