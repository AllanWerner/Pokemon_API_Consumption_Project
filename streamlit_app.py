"""Streamlit front end: displays every feature by calling the Flask REST API.

Run (two terminals, from the project root):
    python app.py                       # Flask API on http://127.0.0.1:5000
    streamlit run streamlit_app.py      # front end on http://localhost:8501

The Flask URL can be changed with the POKEMON_API_URL environment variable.
"""

import os
import time
from dataclasses import dataclass
from datetime import datetime

import altair as alt
import pandas as pd
import requests
import streamlit as st

API_URL = os.environ.get("POKEMON_API_URL", "http://127.0.0.1:5000").rstrip("/")

STAT_LABELS = {
    "hp": "HP",
    "attack": "Attack",
    "defense": "Defense",
    "special-attack": "Sp. Atk",
    "special-defense": "Sp. Def",
    "speed": "Speed",
}

# Official-style colours used for the type badges.
TYPE_COLORS = {
    "normal": "#A8A77A", "fire": "#EE8130", "water": "#6390F0", "electric": "#F7D02C",
    "grass": "#7AC74C", "ice": "#96D9D6", "fighting": "#C22E28", "poison": "#A33EA1",
    "ground": "#E2BF65", "flying": "#A98FF3", "psychic": "#F95587", "bug": "#A6B91A",
    "rock": "#B6A136", "ghost": "#735797", "dragon": "#6F35FC", "dark": "#705746",
    "steel": "#B7B7CE", "fairy": "#D685AD",
}

st.set_page_config(page_title="PokéAPI Explorer", page_icon="⚡", layout="wide")


# --------------------------------------------------------------------------- API access


@dataclass
class ApiResponse:
    ok: bool
    status: int
    data: dict
    elapsed_ms: float
    method: str
    path: str


def call_api(path: str, method: str = "GET", params: dict | None = None, timeout: float = 120) -> ApiResponse:
    """Call the Flask API, measure the response time and record the call in the session log."""
    start = time.perf_counter()
    try:
        response = requests.request(method, f"{API_URL}{path}", params=params, timeout=timeout)
    except requests.ConnectionError:
        st.error(
            f"The Flask API is not reachable at **{API_URL}**. "
            "Start it in another terminal with `python app.py`, then refresh this page."
        )
        st.stop()
    elapsed_ms = (time.perf_counter() - start) * 1000

    try:
        data = response.json()
    except ValueError:
        data = {"error": response.text[:300]}

    result = ApiResponse(response.ok, response.status_code, data, elapsed_ms, method, response.url[len(API_URL):])
    st.session_state.setdefault("api_log", []).append(
        {
            "time": datetime.now().strftime("%H:%M:%S"),
            "method": method,
            "route": result.path,
            "status": result.status,
            "ms": round(elapsed_ms, 1),
        }
    )
    return result


def show_call_details(result: ApiResponse) -> None:
    """Small footer under each result: route, status, latency and the raw JSON."""
    st.caption(f"`{result.method} {result.path}` · status **{result.status}** · {result.elapsed_ms:,.1f} ms")
    with st.expander("Raw API response"):
        st.json(result.data)


def show_error(result: ApiResponse) -> None:
    error_type = result.data.get("type", "Error")
    st.error(f"**{result.status} · {error_type}** — {result.data.get('error', 'Unknown error')}")


def type_badges(types: list[str]) -> str:
    """HTML badges coloured by Pokémon type."""
    return " ".join(
        f"<span style='background:{TYPE_COLORS.get(t, '#888')};color:white;padding:2px 10px;"
        f"border-radius:12px;font-size:0.85em;font-weight:600'>{t.upper()}</span>"
        for t in types
    )


# --------------------------------------------------------------------------- charts


def stats_chart(stats: dict) -> alt.Chart:
    df = pd.DataFrame({"Stat": [STAT_LABELS[k] for k in STAT_LABELS], "Value": [stats[k] for k in STAT_LABELS]})
    base = alt.Chart(df).encode(
        y=alt.Y("Stat:N", sort=None, title=None),
        x=alt.X("Value:Q", scale=alt.Scale(domain=[0, max(160, df.Value.max() + 20)]), title="Base value"),
    )
    bars = base.mark_bar(cornerRadiusEnd=4).encode(
        color=alt.Color("Value:Q", scale=alt.Scale(scheme="goldorange"), legend=None)
    )
    return (bars + base.mark_text(align="left", dx=4).encode(text="Value:Q")).properties(height=230)


def comparison_chart(pokemon: list[dict]) -> alt.Chart:
    rows = [
        {"Stat": STAT_LABELS[k], "Pokémon": p["name"], "Value": p["stats"][k]}
        for p in pokemon
        for k in STAT_LABELS
    ]
    return (
        alt.Chart(pd.DataFrame(rows))
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            x=alt.X("Stat:N", sort=list(STAT_LABELS.values()), title=None),
            xOffset="Pokémon:N",
            y=alt.Y("Value:Q", title="Base value"),
            color=alt.Color("Pokémon:N", legend=alt.Legend(orient="top")),
            tooltip=["Pokémon", "Stat", "Value"],
        )
        .properties(height=320)
    )


def battle_hp_chart(result: dict) -> alt.Chart:
    """HP of both fighters after each attack."""
    hp = {f["label"]: f["max_hp"] for f in result["fighters"]}
    rows = [{"Step": "Start", "Order": 0, "Pokémon": name, "HP": value} for name, value in hp.items()]
    order = 0
    for turn in result["turns"]:
        for action in turn["actions"]:
            order += 1
            hp[action["defender"]] = action["defender_hp"]
            step = f"T{turn['turn']} · {action['attacker']}"
            rows += [{"Step": step, "Order": order, "Pokémon": n, "HP": v} for n, v in hp.items()]

    return (
        alt.Chart(pd.DataFrame(rows))
        .mark_line(point=True, interpolate="step-after")
        .encode(
            x=alt.X("Step:N", sort=alt.SortField("Order"), title=None, axis=alt.Axis(labelAngle=-30)),
            y=alt.Y("HP:Q", scale=alt.Scale(domainMin=0)),
            color=alt.Color("Pokémon:N", legend=alt.Legend(orient="top")),
            tooltip=["Step", "Pokémon", "HP"],
        )
        .properties(height=300)
    )


# --------------------------------------------------------------------------- tabs


def pokemon_tab() -> None:
    with st.form("pokemon_form"):
        identifier = st.text_input("Pokémon name or ID", value="pikachu")
        submitted = st.form_submit_button("Search", type="primary")
    if submitted:
        st.session_state["pokemon"] = call_api(f"/pokemon/{identifier.strip()}")

    result: ApiResponse | None = st.session_state.get("pokemon")
    if result is None:
        return
    if not result.ok:
        show_error(result)
        return

    p = result.data
    left, right = st.columns([1, 2])
    with left:
        if p.get("sprite"):
            st.image(p["sprite"], width=240)
    with right:
        st.subheader(f"#{p['id']} {p['name'].capitalize()}")
        st.markdown(type_badges(p["types"]), unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("Height", f"{p['height']} m")
        c2.metric("Weight", f"{p['weight']} kg")
        c3.metric("Total base stats", sum(p["stats"].values()))
        st.altair_chart(stats_chart(p["stats"]), width="stretch")
    show_call_details(result)


def compare_tab() -> None:
    with st.form("compare_form"):
        c1, c2 = st.columns(2)
        first = c1.text_input("First Pokémon", value="charizard")
        second = c2.text_input("Second Pokémon", value="blastoise")
        submitted = st.form_submit_button("Compare", type="primary")
    if submitted:
        st.session_state["compare"] = call_api(f"/compare/{first.strip()}/{second.strip()}")

    result: ApiResponse | None = st.session_state.get("compare")
    if result is None:
        return
    if not result.ok:
        show_error(result)
        return

    data = result.data
    a, b = data["pokemon"]
    cols = st.columns(2)
    for col, p in zip(cols, (a, b)):
        with col:
            st.image(p["sprite"], width=160)
            st.markdown(f"**{p['name'].capitalize()}** &nbsp; {type_badges(p['types'])}", unsafe_allow_html=True)

    m1, m2, m3 = st.columns(3)
    m1.metric("Stronger in HP", data["hp_winner"].capitalize())
    m2.metric("Stronger in Attack", data["attack_winner"].capitalize())
    m3.metric("Overall (HP + Attack)", data["overall_winner"].capitalize())

    st.altair_chart(comparison_chart([a, b]), width="stretch")
    table = pd.DataFrame(
        [
            {"Stat": STAT_LABELS[k], a["name"]: row[a["name"]], b["name"]: row[b["name"]], "Winner": row["winner"]}
            for k, row in data["comparison"].items()
        ]
    )
    st.dataframe(table, hide_index=True, width="stretch")
    show_call_details(result)


def types_tab() -> None:
    # The type list is fetched once per session (it never changes).
    if "types" not in st.session_state:
        response = call_api("/types")
        st.session_state["types"] = response.data.get("types", []) if response.ok else []

    with st.form("type_form"):
        type_name = st.selectbox("Pokémon type", st.session_state["types"], index=None, placeholder="Choose a type")
        submitted = st.form_submit_button("Compute statistics", type="primary")
    with st.expander(f"All available types ({len(st.session_state['types'])})"):
        st.markdown(type_badges(st.session_state["types"]), unsafe_allow_html=True)

    if submitted and type_name:
        with st.spinner(f"Fetching every {type_name} Pokémon (concurrent calls + cache)..."):
            st.session_state["type_stats"] = call_api(f"/type/{type_name}")

    result: ApiResponse | None = st.session_state.get("type_stats")
    if result is None:
        return
    if not result.ok:
        show_error(result)
        return

    s = result.data
    st.markdown(f"### {type_badges([s['type']])} &nbsp; {s['count']} Pokémon", unsafe_allow_html=True)
    if s["count"] == 0:
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Average HP", s["average_hp"])
    c2.metric("Min HP", s["min_hp"]["hp"], help=s["min_hp"]["name"])
    c3.metric("Max HP", s["max_hp"]["hp"], help=s["max_hp"]["name"])
    c4.metric("Strongest (total stats)", s["strongest"]["total_stats"])
    st.caption(
        f"Lowest HP: **{s['min_hp']['name']}** · Highest HP: **{s['max_hp']['name']}** · "
        f"Strongest: **{s['strongest']['name']}**"
    )

    donut = (
        alt.Chart(pd.DataFrame({"Typing": ["Pure type", "Dual type"],
                                "Count": [s["pure_type_count"], s["dual_type_count"]]}))
        .mark_arc(innerRadius=60)
        .encode(
            theta="Count:Q",
            color=alt.Color("Typing:N", scale=alt.Scale(range=[TYPE_COLORS.get(s["type"], "#888"), "#bbbbbb"])),
            tooltip=["Typing", "Count"],
        )
        .properties(height=260, title="Pure vs dual type")
    )
    st.altair_chart(donut, width="stretch")
    show_call_details(result)


def battle_tab() -> None:
    st.markdown(
        "Speed decides who attacks first · damage = simplified official formula × type effectiveness "
        "× STAB × random · **a KO ends the fight**, otherwise the most total damage after **5 turns** wins."
    )
    with st.form("battle_form"):
        c1, c2, c3 = st.columns([2, 2, 1])
        first = c1.text_input("Pokémon 1", value="pikachu")
        second = c2.text_input("Pokémon 2", value="squirtle")
        seed = c3.text_input("Seed (optional)", help="Same seed = same fight. Leave empty for a random fight.")
        submitted = st.form_submit_button("Fight!", type="primary")
    if submitted:
        params = {"seed": seed.strip()} if seed.strip().isdigit() else None
        st.session_state["battle"] = call_api(f"/battle/{first.strip()}/{second.strip()}", params=params)

    result: ApiResponse | None = st.session_state.get("battle")
    if result is None:
        return
    if not result.ok:
        show_error(result)
        return

    r = result.data
    a, b = r["fighters"]
    left, middle, right = st.columns([2, 1, 2])
    for col, f in ((left, a), (right, b)):
        with col:
            st.image(f["sprite"], width=180)
            st.markdown(f"**{f['label'].capitalize()}** &nbsp; {type_badges(f['types'])}", unsafe_allow_html=True)
            st.progress(f["remaining_hp"] / f["max_hp"], text=f"HP {f['remaining_hp']} / {f['max_hp']}")
            st.metric("Total damage dealt", f["total_damage"])
    with middle:
        st.markdown("<h1 style='text-align:center;margin-top:60px'>VS</h1>", unsafe_allow_html=True)

    if r["reason"] == "ko":
        st.success(f"🏆 **{r['winner'].capitalize()}** wins — {r['ko']} is KO after {r['turns_played']} turn(s).")
    elif r["reason"] == "damage":
        st.success(f"🏆 **{r['winner'].capitalize()}** wins on total damage after 5 turns.")
    else:
        st.info("Perfect tie: same total damage after 5 turns.")
    st.caption(f"Seed **{r['seed']}** — enter it above to replay exactly this fight.")

    st.altair_chart(battle_hp_chart(r), width="stretch")

    effectiveness_label = {0: "no effect", 0.25: "×0.25", 0.5: "×0.5 (not very)", 1: "×1", 2: "×2 (super)", 4: "×4 (super)"}
    log = pd.DataFrame(
        [
            {
                "Turn": t["turn"],
                "Attacker": act["attacker"],
                "Move": f"{act['move_type']} · {act['category']}",
                "Effectiveness": effectiveness_label.get(act["effectiveness"], act["effectiveness"]),
                "Damage": act["damage"],
                "Target": act["defender"],
                "Target HP left": act["defender_hp"],
            }
            for t in r["turns"]
            for act in t["actions"]
        ]
    )
    st.dataframe(log, hide_index=True, width="stretch")
    show_call_details(result)


def robustness_tab() -> None:
    # ---- Q1
    st.subheader("Q1 · Error handling, retries and pauses")
    st.markdown(
        "Transient errors (429, 5xx, timeouts) are **retried with exponential backoff** (429 honours "
        "`Retry-After`); client errors (400/401/403/404) **fail immediately**."
    )
    c1, c2, c3 = st.columns(3)
    if c1.button("Run simulated failures", type="primary"):
        st.session_state["q1"] = call_api("/demo/resilience")
    if c2.button("Real call: unknown Pokémon"):
        st.session_state["q1_real"] = call_api("/pokemon/pikachuuu")
    if c3.button("Real call: invalid ID"):
        st.session_state["q1_real"] = call_api("/pokemon/-5")

    if (q1 := st.session_state.get("q1")) is not None and q1.ok:
        df = pd.DataFrame(q1.data["scenarios"])
        df["pauses_s"] = df["pauses_s"].apply(lambda p: ", ".join(f"{x:.2f}s" for x in p) or "—")
        st.dataframe(df, hide_index=True, width="stretch")
    if (real := st.session_state.get("q1_real")) is not None:
        show_error(real)
        st.caption(f"`{real.method} {real.path}` · status **{real.status}** · {real.elapsed_ms:,.1f} ms")

    st.divider()

    # ---- Q2
    st.subheader("Q2 · High load with asyncio")
    st.markdown(
        "Requests to the mock routes `api.example.com/data1`, `/data2` and `/data3` (random latency, "
        "~4 % injected errors) through the async client: shared connection pool, bounded concurrency, worker pool."
    )
    with st.form("load_form"):
        c1, c2 = st.columns(2)
        total = c1.slider("Number of requests", 1_000, 50_000, 10_000, step=1_000)
        concurrency = c2.slider("Concurrency", 10, 500, 200, step=10)
        submitted = st.form_submit_button("Run load test", type="primary")
    if submitted:
        with st.spinner(f"Sending {total:,} requests..."):
            st.session_state["q2"] = call_api("/demo/load", params={"total": total, "concurrency": concurrency})

    if (q2 := st.session_state.get("q2")) is not None and q2.ok:
        d = q2.data
        m = st.columns(5)
        m[0].metric("Duration", f"{d['duration_s']:.2f} s")
        m[1].metric("Throughput", f"{d['throughput_rps']:,} req/s")
        m[2].metric("HTTP calls", f"{d['http_calls']:,}")
        m[3].metric("Retries", f"{d['retries']:,}")
        m[4].metric("Success rate", f"{d['succeeded'] / d['total']:.2%}")
        st.caption(
            "In-process test (mock server and client share one CPU). The full script "
            "`python -m scripts.q2_load_simulation --total 1000000` uses separate backend processes "
            "and reached ~6 300 req/s on 1 million requests."
        )

    st.divider()

    # ---- Q3
    st.subheader("Q3 · Cache with 1-hour expiry")
    c1, c2, c3 = st.columns(3)
    if c1.button("Refresh cache statistics"):
        st.session_state["q3_stats"] = call_api("/cache/stats")
    if c2.button("Clear cache"):
        st.session_state["q3_stats"] = call_api("/cache/clear", method="POST")
        st.toast("Cache cleared")
    if (stats := st.session_state.get("q3_stats")) is not None and stats.ok:
        s = stats.data
        m = st.columns(5)
        m[0].metric("Entries", s["entries"])
        m[1].metric("Hits", s["hits"])
        m[2].metric("Misses", s["misses"])
        m[3].metric("Hit rate", f"{s['hit_rate']:.0%}")
        m[4].metric("TTL", f"{s['ttl_seconds'] // 60} min")

    st.markdown("**Cold vs warm cache** — the cache is cleared, then the same route is called twice.")
    with st.form("cache_form"):
        route_type = st.selectbox("Type statistics to measure", st.session_state.get("types") or ["fire"])
        submitted = st.form_submit_button("Measure", type="primary")
    if submitted:
        call_api("/cache/clear", method="POST")
        cold = call_api(f"/type/{route_type}")
        warm = call_api(f"/type/{route_type}")
        st.session_state["q3_measure"] = (route_type, cold.elapsed_ms, warm.elapsed_ms)

    if (measure := st.session_state.get("q3_measure")) is not None:
        route_type, cold_ms, warm_ms = measure
        c1, c2 = st.columns([1, 2])
        c1.metric("1st call (API)", f"{cold_ms:,.0f} ms")
        c1.metric("2nd call (cache)", f"{warm_ms:,.1f} ms", delta=f"×{cold_ms / warm_ms:,.0f} faster", delta_color="off")
        chart = (
            alt.Chart(pd.DataFrame({"Call": ["1st (API)", "2nd (cache)"], "ms": [cold_ms, warm_ms]}))
            .mark_bar(cornerRadiusEnd=4)
            .encode(y=alt.Y("Call:N", title=None), x=alt.X("ms:Q", title="Response time (ms)"),
                    color=alt.Color("Call:N", legend=None, scale=alt.Scale(range=["#EE8130", "#7AC74C"])))
            .properties(height=150, title=f"GET /type/{route_type}")
        )
        c2.altair_chart(chart, width="stretch")

    if c3.button("Load test: without vs with cache"):
        with st.spinner("Running both load tests..."):
            runs = [call_api("/demo/load", params={"total": 10_000, "concurrency": 200, "cache": c}) for c in (0, 1)]
        st.session_state["q3_load"] = [r.data for r in runs if r.ok]
    if (runs := st.session_state.get("q3_load")) and len(runs) == 2:
        df = pd.DataFrame(
            [
                {"Mode": "Without cache" if not r["cache"] else "1h cache", "Duration (s)": r["duration_s"],
                 "HTTP calls sent": r["http_calls"], "Cache hits": r["cache_hits"], "Throughput (req/s)": r["throughput_rps"]}
                for r in runs
            ]
        )
        st.markdown("**10 000 requests on data1/2/3 — without vs with cache**")
        st.dataframe(df, hide_index=True, width="stretch")


# --------------------------------------------------------------------------- layout

st.title("⚡ PokéAPI Explorer")
st.caption(f"Streamlit front end · every figure below comes from the Flask API at `{API_URL}`")

tabs = st.tabs(["Pokémon", "Compare", "Types", "Battle", "Robustness & performance"])
with tabs[0]:
    pokemon_tab()
with tabs[1]:
    compare_tab()
with tabs[2]:
    types_tab()
with tabs[3]:
    battle_tab()
with tabs[4]:
    robustness_tab()

# Rendered last so it includes the calls made during this run.
with st.sidebar:
    st.header("API call log")
    log = st.session_state.get("api_log", [])
    if log:
        st.metric("Calls this session", len(log))
        st.dataframe(pd.DataFrame(log[::-1]), hide_index=True, width="stretch", height=420)
        if st.button("Clear log"):
            st.session_state["api_log"] = []
            st.rerun()
    else:
        st.info("No call yet.")
