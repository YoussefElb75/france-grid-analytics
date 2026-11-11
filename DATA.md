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
| Day-ahead prices (12.1.D) | **No**: general Terms of Use apply; the exchange's rights must be respected |

Both documents are linked from the Transparency Platform help centre, article "Legal Terms and
Conditions". Check the current versions before any re-use: the Terms of Use make that the data
user's responsibility.

## What this repository contains and does not contain

* **No raw or processed data files.** Every user downloads the data with their own token into the
  git-ignored `data/` folder (`frgrid fetch`). Nothing under `data/` is ever committed.
* **Test fixtures**: `tests/fixtures/` holds twelve small excerpts (one or two days each) of real
  responses, used only to test parsing; identifiers are replaced by placeholders (see
  `tests/fixtures/README.md`).
* **Charts** in `docs/img/` show derived, aggregated statistics (monthly means, average daily
  profiles, error metrics of a forecast backtest), not the underlying time series. Each chart
  carries the source line "Source: ENTSO-E Transparency Platform; analysis: france-grid-analytics".

Attribution for the data shown or derived here: *Source: ENTSO-E Transparency Platform
(transparency.entsoe.eu). Data processed (aggregated, resampled to hourly averages) by
france-grid-analytics.*

## Data handling notes

* Timestamps are UTC interval starts as published; profiles are shown in Europe/Paris time.
* Day-ahead prices are hourly until 30 September 2025 and quarter-hourly from 1 October 2025 on;
  hourly series are repeated onto a 15-minute grid, and the native resolution is kept.
* ENTSO-E does not check the data it publishes (Terms of Use, clause 3.2); values are used as
  published. Recent days can still be revised, so only windows older than seven days are cached.
* CO2 emission factors are life-cycle medians from IPCC AR5 WGIII Annex III (Table A.III.2) where
  available; the remaining ones are flagged as assumptions in `src/frgrid/analytics.py`.
