"""France grid analytics: local Streamlit dashboard.

Run with ``frgrid dashboard`` (or ``streamlit run app/streamlit_app.py``). All data come from the
local store filled by ``frgrid fetch`` or by the "Update from ENTSO-E" button below; the UI only
shows aggregated figures. "LIVE" is shown only after a successful fetch in the current session.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from frgrid import europe_figures as ef
from frgrid.areas import LOCAL_TZ, ZONE_LABELS
from frgrid.dashboard import data as dd
from frgrid.dashboard import figures as ff
from frgrid.forecast import Backtest
from frgrid.style import SOURCE

LIVE_KEY = "live_fetch_at"

st.set_page_config(page_title="France grid analytics", layout="wide")


@st.cache_data(show_spinner=False)
def cached_bundle(signature: str) -> dd.Bundle:
    del signature  # cache key only
    return dd.load_bundle()


@st.cache_data(show_spinner="Running the walk-forward backtest...")
def cached_backtest(signature: str) -> Backtest | None:
    bundle = cached_bundle(signature)
    prices, load = bundle.get("prices"), bundle.get("load")
    if prices is None or load is None:
        return None
    return dd.run_backtest(prices, load)


def show(fig: Any, table: pd.DataFrame) -> None:
    st.pyplot(fig, clear_figure=True)
    plt.close(fig)
    with st.expander("Show table"):
        st.dataframe(table.round(2), width="stretch")


def missing(name: str) -> None:
    st.warning(f"No {name} data stored locally. Fetch it first (see the sidebar).")


def status_panel(bundle: dd.Bundle) -> None:
    live_at = st.session_state.get(LIVE_KEY)
    if live_at is not None:
        st.success(f"LIVE: fetched from ENTSO-E in this session at {live_at}")
    else:
        st.info("Cached data: not fetched in this session.")
    st.caption(f"Data as of {dd.format_as_of(bundle.as_of)}")
    cov = bundle.coverage()
    if cov is not None:
        st.caption(f"Covers {cov[0]:%d %b %Y} - {cov[1]:%d %b %Y}")
    if bundle.missing:
        st.caption("Missing datasets: " + ", ".join(bundle.missing))


def update_panel(bundle: dd.Bundle) -> None:
    with st.expander("Update from ENTSO-E"):
        st.caption(
            "Uses your token from the local .env file and the local cache: settled windows are "
            "read from disk, only recent ones are downloaded."
        )
        cov = bundle.coverage()
        default_start = cov[0].date() if cov is not None else date(2024, 1, 1)
        today = pd.Timestamp.now(tz=LOCAL_TZ).date()
        start = st.date_input("First day", value=default_start, max_value=today)
        end = st.date_input("Day after the last day", value=today + timedelta(days=1))
        if st.button("Fetch", type="primary"):
            with st.spinner("Fetching from ENTSO-E (at most 3 minutes)..."):
                try:
                    dd.refresh(start, end, max_minutes=3.0)
                except dd.DataError as exc:
                    st.error(str(exc))
                    return
            st.session_state[LIVE_KEY] = pd.Timestamp.now(tz=LOCAL_TZ).strftime("%H:%M")
            st.cache_data.clear()
            st.rerun()


def period_selector(bundle: dd.Bundle) -> tuple[pd.Timestamp, pd.Timestamp]:
    months = dd.month_options(bundle)
    if len(months) < 2:
        return months[0], months[0]
    first, last = st.select_slider(
        "Period (months)",
        options=months,
        value=(months[0], months[-1]),
        format_func=lambda m: f"{m:%b %Y}",
    )
    return first, last


def prices_tab(bundle: dd.Bundle, sig: str, first: pd.Timestamp, last: pd.Timestamp) -> None:
    prices = bundle.get("prices")
    if prices is None:
        missing("price")
        return
    period = dd.clip_period(prices, first, last)
    monthly = dd.clip_months(dd.monthly_prices(prices), first, last)
    bt = cached_backtest(sig)
    c1, c2, c3 = st.columns(3)
    c1.metric("Mean day-ahead price", f"{monthly['mean'].mean():.1f} EUR/MWh")
    c2.metric("Hours with a negative price", f"{monthly['negative_share'].mean():.1%}")
    if bt is not None:
        summary = dd.backtest_summary(bt, first, last)
        if not summary.empty:
            mae = summary.loc["MAE"].astype(float).to_dict()
            gain = 1 - mae["model"] / mae["naive_d1"]
            change = f"{gain:.0%} better" if gain > 0 else f"{-gain:.0%} worse"
            c3.metric(
                "Forecast MAE vs naive D-1",
                f"{mae['model']:.1f} EUR/MWh",
                change,
                delta_color="normal" if gain > 0 else "inverse",
            )
    label = f"{first:%b %Y} - {last:%b %Y}"
    show(ff.price_profile(dd.price_profile(period), label), dd.price_profile(period))
    show(ff.monthly_prices(monthly), monthly)
    if bt is None:
        missing("load forecast (needed by the backtest)")
        return
    table = dd.clip_months(dd.backtest_monthly(bt), first, last)
    if table.empty:
        st.info("The backtest starts after a 120-day training period; no forecasts in this range.")
        return
    show(ff.forecast_vs_actual(table), table)
    st.caption(
        "Forecast: one ridge regression per local hour on D-1 and D-7 prices, the TSO's "
        "day-ahead load forecast and the calendar, refitted daily on the previous 365 days. "
        "Monthly aggregates only."
    )


def system_tab(bundle: dd.Bundle, first: pd.Timestamp, last: pd.Timestamp) -> None:
    load, gen = bundle.get("load"), bundle.get("generation")
    if load is None:
        missing("load")
    else:
        table = dd.clip_months(dd.load_monthly(load), first, last)
        show(ff.load_vs_forecast(table), table)
    if gen is None:
        missing("generation")
        return
    if load is not None:
        table = dd.clip_months(dd.residual_monthly(load, gen), first, last)
        show(ff.residual_load(table), table)
    mix = dd.clip_months(dd.generation_monthly(gen), first, last)
    show(ff.generation_mix(mix), mix)
    rc = dd.clip_months(dd.renewables_co2_monthly(gen), first, last)
    show(ff.renewables_co2(rc), rc)


def flows_tab(bundle: dd.Bundle, first: pd.Timestamp, last: pd.Timestamp) -> None:
    flows = bundle.get("flows")
    if flows is None:
        missing("cross-border flow")
        return
    net = dd.clip_months(dd.net_position_monthly(flows), first, last)
    show(ff.net_position(net), net)
    totals = dd.border_flows(dd.clip_period(flows, first, last))
    show(ff.border_flows(totals, f"{first:%b %Y} - {last:%b %Y}"), totals)
    st.caption(
        "Directions follow ENTSO-E: import into France = in_Domain France, export = out_Domain "
        "France. DE = Germany-Luxembourg, IT = Italy North bidding zone."
    )


def europe_tab(bundle: dd.Bundle, first: pd.Timestamp, last: pd.Timestamp) -> None:
    view = dd.europe_view(bundle, first, last)
    if view is None:
        missing("European price")
        return
    label = f"{first:%b %Y} - {last:%b %Y}"
    mean = view.monthly_prices.mean()
    conv = view.convergence_summary
    c1, c2, c3 = st.columns(3)
    c1.metric("Mean French day-ahead price", f"{mean['FR']:.1f} EUR/MWh")
    cheapest = str(mean.idxmin())
    c2.metric("Cheapest zone on average", ZONE_LABELS.get(cheapest, cheapest))
    shares = conv["converged"].astype(float).to_dict()
    if "DE_LU" in shares:
        c3.metric("Time with France = Germany-Lux. price", f"{shares['DE_LU']:.1%}")

    st.subheader("Prices by zone")
    show(ef.price_heatmap(view.monthly_prices), view.monthly_prices)

    st.subheader("Spreads to France")
    show(ef.spread_distribution(view.spread_distribution, label), view.spread_distribution)
    show(ef.spread_by_hour(view.spread_by_hour, label), view.spread_by_hour)
    show(ef.spread_by_month(view.spread_by_month), view.spread_by_month)

    st.subheader("Convergence and congestion")
    show(ef.convergence_by_month(view.convergence_by_month), view.convergence_by_month)
    with st.expander("Convergence summary"):
        st.dataframe(conv.round(3), width="stretch")
    if view.flow_vs_spread is None or view.against_by_spread_size is None:
        missing("cross-border flow")
    else:
        show(ef.flow_vs_spread(view.flow_vs_spread, label), view.flow_vs_spread)
        show(
            ef.against_by_spread_size(view.against_by_spread_size, label),
            view.against_by_spread_size,
        )
        st.caption(
            "Physical flows include loop and transit flows; in the flow-based Core region (FR, BE, "
            "NL, DE-LU) the market can also schedule exchanges against a price difference."
        )
    if view.congestion_by_month is None or view.congestion_check is None:
        missing("cross-border capacity")
    else:
        show(ef.congestion_by_month(view.congestion_by_month), view.congestion_by_month)
        with st.expander("Check: is the border full when prices differ?"):
            st.dataframe(view.congestion_check.round(3), width="stretch")
        st.caption(
            "Day-ahead NTC and day-ahead commercial schedules exist only on the FR-ES and FR-IT "
            "North borders; BE and DE-LU are flow-based and have no bilateral capacity."
        )

    st.subheader("Negative prices")
    show(ef.negative_heatmap(view.negative_by_month), view.negative_by_month)
    if view.solar_profile is None or view.negative_summary is None:
        missing("solar generation")
    else:
        show(
            ef.negative_vs_solar(view.negative_by_hour, view.solar_profile, label),
            view.negative_by_hour,
        )
        with st.expander("When negative prices happen"):
            st.dataframe(view.negative_summary.round(3), width="stretch")
    st.caption(
        "Spread = neighbour price - French price. Convergence = equal prices to the cent. "
        "All shares are per quarter-hour (hourly prices before October 2025 count four times). "
        "Monthly and hour-of-day aggregates only."
    )


def main() -> None:
    sig = dd.store_signature()
    bundle = cached_bundle(sig)
    st.title("France grid analytics")
    st.caption(f"Data as of {dd.format_as_of(bundle.as_of)}. {SOURCE}.")

    with st.sidebar:
        st.header("Data")
        if not bundle.is_empty:
            status_panel(bundle)
        update_panel(bundle)

    if bundle.is_empty:
        st.info(
            "No local data yet. Fetch it from a terminal with "
            "`frgrid fetch --start 2024-01-01 --end 2026-11-01`, or use "
            "**Update from ENTSO-E** in the sidebar (needs your token in the .env file)."
        )
        return

    with st.sidebar:
        first, last = period_selector(bundle)

    prices, system, flows, europe = st.tabs(["Prices", "System", "Cross-border flows", "Europe"])
    with prices:
        prices_tab(bundle, sig, first, last)
    with system:
        system_tab(bundle, first, last)
    with flows:
        flows_tab(bundle, first, last)
    with europe:
        europe_tab(bundle, first, last)
    st.caption(f"{SOURCE}. Not affiliated with or endorsed by ENTSO-E.")


try:
    main()
except Exception as exc:  # last-resort error state without tracebacks or local paths
    st.error(f"Something went wrong while preparing the dashboard ({type(exc).__name__}).")
