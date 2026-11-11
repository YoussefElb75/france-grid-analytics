# france-grid-analytics

Analytics on the French power system built directly on the
[ENTSO-E Transparency Platform](https://transparency.entsoe.eu) API: day-ahead prices at their
native 15-minute resolution, load and the TSO's load forecast, generation by type, and
cross-border physical flows. On top of that sit a small set of transparent indicators and a
day-ahead price forecast that is backtested honestly against naive baselines.

![Average day-ahead price by hour of day](docs/img/price_profile.png)

## What is in here

| Module | Purpose |
|---|---|
| `frgrid.client` | HTTP client: token in a header only, retries with back-off, rate limiting, local cache |
| `frgrid.parse` | XML parser: A01/A03 curves (A03 omits repeated values), mixed PT15M/PT60M periods |
| `frgrid.datasets` | France datasets on a uniform 15-minute UTC grid |
| `frgrid.analytics` | daily profiles, residual load, renewable share, CO2 intensity, net imports |
| `frgrid.forecast` | walk-forward backtest of a day-ahead price model vs naive baselines |
| `frgrid.charts` | the charts and tables in this README |

## Quick start

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env            # put your own ENTSO-E token in .env
git config core.hooksPath .githooks

frgrid fetch --start 2024-01-01 --end 2026-11-01   # resumable, stops cleanly after 9 minutes
frgrid report                                       # charts -> docs/img, tables -> docs/results.md
```

Get a token by registering on the Transparency Platform and asking for "Restful API access"
(see the platform's help article "How to get security token?"). Dates are Europe/Paris days and
`--end` is exclusive. Downloads are cached per calendar quarter in the git-ignored `data/`
folder, so rerunning the same command resumes where it stopped. 34 months take 192 requests.

## Security model for the API token

* The token is read from `ENTSOE_API_TOKEN` or a git-ignored `.env`, and kept in a wrapper whose
  `repr`/`str` never show it.
* It is sent **only in the `SECURITY_TOKEN` HTTP header**, never in the URL, and only to
  `https://web-api.tp.entsoe.eu`; system proxy settings are ignored and redirects are not
  followed. Error messages, logs and cache keys are built without it (and tests check that).
* `scripts/check_secrets.py` blocks token-shaped strings (UUIDs), literal `securityToken=` values,
  the local token itself and `.env` files. It runs as a git pre-commit hook and in CI.
* CI needs no secret: all tests run offline on scrubbed sample responses.

## Definitions

* **Time**: ENTSO-E timestamps are UTC interval starts; profiles are in Europe/Paris local time.
  Hourly values are means of the four quarter-hours (an hour with a missing quarter is missing).
* **Day-ahead price**: hourly until 30 September 2025, quarter-hourly from 1 October 2025
  (SDAC 15-minute market time unit). Hourly prices are repeated onto the 15-minute grid; the
  native resolution is kept in a `resolution_min` column.
* **Generation**: sum of production types, excluding storage output (pumped-storage turbining,
  "Energy storage") and all consumption series (pumping, storage charging). A timestamp where a
  core type (nuclear, gas, run-of-river, reservoir, solar, onshore wind) is missing is missing;
  minor types not reported (e.g. hard coal after its last plant stopped) count as zero.
* **Renewable share**: biomass, geothermal, run-of-river and reservoir hydro, marine, other
  renewable, solar and wind over generation. Waste is excluded (only partly biogenic).
* **Residual load**: actual load minus solar, onshore and offshore wind.
* **CO2 intensity**: production-based, life-cycle gCO2eq/kWh of domestic generation, imports
  excluded. Factors are IPCC AR5 WGIII Annex III (Table A.III.2) medians where they exist; oil,
  waste and "other" are flagged assumptions (together about 1% of output). Life-cycle values are
  higher than the direct-emission figures published by RTE, by construction.
* **Flows**: physical flows (A11). Import into France = `in_Domain` France; export = `out_Domain`
  France. Germany and Italy are the DE-LU and IT-North bidding zones.

## Results (January 2024 - October 2026)

![Monthly generation mix](docs/img/generation_mix.png)

Nuclear supplies 34-53 GW as a monthly average; total generation peaks in winter at up to 75 GW.

![Price vs residual load](docs/img/residual_load_price.png)

The merit order shows up directly: hourly prices rise with the load left after wind and solar
(correlation 0.53), with negative prices concentrated at low residual load.

![Renewable share and CO2 intensity](docs/img/renewables_co2.png)

![Net exports by border](docs/img/net_exports.png)

France exported on every border on average; Spain is the border where it turns net importer
in winter and spring months.

### Day-ahead price forecast, backtested

Target: the hourly French day-ahead price of day D. Inputs are restricted to what is public
before the auction on D-1: prices of D-1 and D-7, the mean price of D-1, the TSO's day-ahead load
forecast for D, and Monday/Saturday/Sunday dummies. One ridge regression per local hour, refitted
every day on the previous 365 days (walk-forward, no look-ahead; a test checks this). The design
and penalty were fixed before running the backtest; nothing was tuned on it.

![Forecast error by month](docs/img/forecast_mae.png)

Backtest: 891 delivery days, 10 May 2024 - 31 Oct 2026, 21,384 hourly forecasts.

| | Ridge model | Naive D-1 | Naive D-7 |
|---|---:|---:|---:|
| MAE (EUR/MWh) | 20.6 | 23.7 | 34.3 |
| RMSE (EUR/MWh) | 28.2 | 35.0 | 47.7 |
| bias (EUR/MWh) | -2.0 | -0.1 | -1.5 |
| MAE 2024 | 18.3 | 23.1 | 30.3 |
| MAE 2025 | 17.6 | 20.0 | 31.1 |
| MAE 2026 | 26.0 | 28.5 | 41.3 |

MAE reduction vs naive D-1: 13%; vs naive D-7: 40%. Diebold-Mariano test on daily mean absolute
errors (Newey-West, 7 lags): -8.7 vs D-1 and -12.5 vs D-7, p < 0.001 for both.

**Reading it honestly**: the model is a modest, statistically clear improvement over "same hour
yesterday", not a trading signal. It does not win every month: May 2025 is a tie and in July 2026
it is 2.1 EUR/MWh worse than the naive D-1 forecast. Its error rises with price levels in 2026, and
it has a small negative bias. It uses no weather, fuel or carbon prices, nor wind and solar forecasts.

### Data quirks seen

* ENTSO-E reports a few odd consumption series for France (e.g. "Wind Onshore (consumption)",
  April 2025 - January 2026). Consumption series never enter generation here.
* Nuclear is missing for 122 quarter-hours; those timestamps are treated as missing.
* ENTSO-E answers "no matching data" and real errors (e.g. "interval too long") with the same
  reason code 999; the client tells them apart by the reason text.

## Data and licence

Code: MIT (see `LICENSE`). Data: not included. See [DATA.md](DATA.md) for the ENTSO-E terms,
which datasets are under CC BY 4.0 and which are not (day-ahead prices, actual load and actual
generation are not on ENTSO-E's free re-use list), and attribution.

Source of all data shown: ENTSO-E Transparency Platform. This project is not affiliated with or
endorsed by ENTSO-E.

## Development

```bash
python scripts/check_secrets.py --all
ruff check . && ruff format --check .
mypy            # strict
pytest          # offline
```
