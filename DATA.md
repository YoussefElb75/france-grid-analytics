# Data: source, terms and what this repository contains

## Source

All data come from the **ENTSO-E Transparency Platform** (https://transparency.entsoe.eu), queried
through its RESTful API with each user's own security token. This project is not affiliated with,
sponsored or endorsed by ENTSO-E.

| Dataset | ENTSO-E item (Regulation (EU) 543/2013) | API document | Primary owner of the data |
|---|---|---|---|
| Day-ahead prices, France | 12.1.D | A44 | the power exchange(s) coupling the French bidding zone (SDAC) |
| Actual total load | 6.1.A | A65 / A16 | RTE (French TSO) |
| Day-ahead total load forecast | 6.1.B | A65 / A01 | RTE |
| Actual generation per production type | 16.1.B&C | A75 / A16 | RTE |
| Cross-border physical flows | 12.1.G | A11 | TSOs / interconnector operators of each border |
| Day-ahead prices, DE-LU, BE, NL, ES, IT-North | 12.1.D | A44 | the power exchanges (NEMOs) coupling each bidding zone (SDAC) |
| Actual solar generation, six zones | 16.1.B&C | A75 / A16, psrType B16 | the TSOs of each zone |
| Day-ahead NTC, FR-ES and FR-IT North | 11.1.A | A61, contract A01 | the TSOs of each border |
| Day-ahead scheduled commercial exchanges, FR-ES and FR-IT North | 12.1.F | A09, contract A01 | the TSOs of each border |

## Terms (checked on 11 November 2026)

* **Terms of Use** of the Transparency Platform, version approved 29/03/2023 and applicable from
  1 November 2023, clause 3.1 "Use of the Transparency Platform Data". A Data User must, for any
  purpose:
  * use the data in good faith and follow good business practices for re-using public data;
  * **mention the ENTSO-E Transparency Platform as the source** of the data;
  * not use the ENTSO-E name in a way that suggests sponsorship or endorsement;
  * **not prejudice the copyright or related rights of the primary owner of the data**, and seek
    that owner's prior agreement where there is such a risk.
* **List of data available for free re-use**, version of 18 October 2023. Items on this list may be
  copied, redistributed and adapted for any purpose under **CC BY 4.0** (attribution, and
  indicating changes), without asking the primary owner. Exceptions include data provided by the
  interconnectors *Interconnexion France-Angleterre* (IFA) and *Nemo Link*.

Where the datasets used here stand:

| Dataset | On the CC BY 4.0 list? |
|---|---|
| Day-ahead load forecast (6.1.B) | **Yes** (item 1) |
| Physical flows (12.1.G) | **Yes** (item 18), except data provided by IFA (France-Great Britain) |
| Actual total load (6.1.A) | No: general Terms of Use apply |
| Actual generation per type (16.1.B&C) | No: general Terms of Use apply |
| Day-ahead prices (12.1.D), all six zones | **No**: general Terms of Use apply; the exchanges' rights must be respected |
| Actual solar generation (16.1.B&C), six zones | No: general Terms of Use apply |
| Day-ahead NTC (11.1.A) and scheduled commercial exchanges (12.1.F) | **Not verified** (the current list could not be retrieved on 13 November 2026): treated like the items above, under the general Terms of Use, aggregates only |

Both documents are linked from the Transparency Platform help centre, article "Legal Terms and
Conditions". Check the current versions before any re-use: the Terms of Use make that the data
user's responsibility.

## What this repository contains and does not contain

* **No raw or processed data files.** Every user downloads the data with their own token into the
  git-ignored `data/` folder (`frgrid fetch`). Nothing under `data/` is ever committed.
* **Test fixtures**: `tests/fixtures/` holds seventeen small response excerpts (one or two days
  each) used only to test parsing. Their structure is real but **every value is synthetic** and
  identifiers are placeholders (see `tests/fixtures/README.md`).
* **Charts and screenshots** in `docs/img/` (README charts, dashboard screenshots and the demo
  GIF) show derived, aggregated statistics only: monthly means and percentiles, average
  hour-of-day profiles, binned counts of hours, and error metrics of a forecast backtest. They
  never show a raw time series. In particular, **day-ahead prices appear only as monthly or
  average-profile aggregates**, because prices are not on the CC BY 4.0 list.
* Every chart carries the line "Source: ENTSO-E Transparency Platform; analysis:
  france-grid-analytics", and the dashboard repeats the source in its header and footer.
* **The dashboard** reads only the user's own locally downloaded data (fetched with their own
  token) and, like the images, displays aggregates only.

Attribution for the data shown or derived here: *Source: ENTSO-E Transparency Platform
(transparency.entsoe.eu). Data processed (aggregated, resampled to hourly averages) by
france-grid-analytics.*

## European zones (v2)

| Zone | EIC | Day-ahead resolution as published | Notes |
|---|---|---|---|
| France (FR) | 10YFR-RTE------C | PT60M to 29 Sep 2025, PT15M from 30 Sep 2025 | 30 Sep 2025 is PT15M with hourly values |
| Germany-Luxembourg (DE_LU) | 10Y1001A1001A82H | PT60M to 30 Sep 2025, PT15M from 1 Oct 2025 | a second, separate 15-minute day-ahead auction is published as classification sequence 2 and dropped |
| Belgium (BE) | 10YBE----------2 | PT60M to 29 Sep 2025, PT15M from 30 Sep 2025 | 30 Sep 2025 is PT15M with hourly values |
| Netherlands (NL) | 10YNL----------L | PT60M to 30 Sep 2025, PT15M from 1 Oct 2025 | solar series covers only a small part of the PV fleet (peaks near 0.3 GW); not used |
| Spain (ES) | 10YES-REE------0 | PT60M to 30 Sep 2025, PT15M from 1 Oct 2025 | intraday auction prices (contract A07) come in the same answer and are dropped |
| Italy North (IT_NORTH) | 10Y1001A1001A73I | PT60M to 31 Dec 2024, PT15M from 1 Jan 2025 | Jan-Sep 2025: PT15M format, hourly values; no price below 0 EUR/MWh |

* All six zones are on Europe/Paris local time (CET/CEST), so hour-of-day profiles are comparable.
* Hourly prices are repeated onto the 15-minute grid, as for France; every share is per
  quarter-hour.
* Only France's two NTC borders (Spain, Italy North) have day-ahead capacity and schedule data;
  the Core borders (Belgium, Germany-Luxembourg) are flow-based.
* **What the repository contains for these zones**: the same rules as above. No downloaded data
  are committed; the four European README charts (`docs/img/eu_*.png`) and
  `docs/europe_results.md` show monthly means, hour-of-day means, shares of time and yearly
  counts only; test fixtures for these zones (`prices_de_lu_two_sequences.xml`,
  `prices_es_with_intraday.xml`, `prices_nl_transition.xml`, `solar_nl_with_consumption.xml`,
  `ntc_es_to_fr.xml`) keep the response structure with synthetic values.

## Data handling notes

* Timestamps are UTC interval starts as published; profiles are shown in Europe/Paris time.
* Day-ahead prices are hourly until 30 September 2025 and quarter-hourly from 1 October 2025 on;
  hourly series are repeated onto a 15-minute grid, and the native resolution is kept.
* ENTSO-E does not check the data it publishes (Terms of Use, clause 3.2); values are used as
  published. Recent days can still be revised, so only windows older than seven days are cached.
* CO2 emission factors are life-cycle medians from IPCC AR5 WGIII Annex III (Table A.III.2) where
  available; the remaining ones are flagged as assumptions in `src/frgrid/analytics.py`.
