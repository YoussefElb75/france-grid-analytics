# Test fixtures

Small excerpts (one or two days each) of the structure of ENTSO-E Transparency Platform responses for France
and the other bidding zones compared in the European analysis,
used only by the offline tests. Source: ENTSO-E Transparency Platform, https://transparency.entsoe.eu
(see `DATA.md` for terms and attribution).

They were produced with `scripts/scrub_fixture.py`, which replaces document and time-series
`mRID` identifiers with placeholders, can drop time series to keep files small, and refuses to
write any file containing a token-like string. **Every value is synthetic**
(`base + step * position`): only the document *structure* is real (periods, resolutions, the
positions ENTSO-E omits in A03 curves, acknowledgement texts), so no real data series are stored
in the repository. No request credentials are ever part of an
ENTSO-E response: the token travels in a request header only.

| File | Content |
|---|---|
| `prices_pt15m.xml` | FR day-ahead prices, 1 Nov 2026, PT15M, A03 (95 points for 96 slots) |
| `prices_pt60m.xml` | FR day-ahead prices, 15 Jun 2025, PT60M |
| `prices_transition.xml` | FR day-ahead prices, 30 Sep - 1 Oct 2025 (two time series) |
| `prices_de_lu_two_sequences.xml` | DE-LU day-ahead prices, 1 Nov 2026: classification sequence 2 (separate 15-min auction) listed before sequence 1 (SDAC) |
| `prices_es_with_intraday.xml` | ES prices, 1 Nov 2026: one day-ahead series (contract A01) and three intraday auction series (A07) |
| `prices_nl_transition.xml` | NL day-ahead prices, 30 Sep (PT60M) - 1 Oct 2025 (PT15M) |
| `load_actual.xml`, `load_forecast.xml` | FR total load, realised (A16) and day-ahead forecast (A01), 1 Nov 2026 |
| `solar_nl_with_consumption.xml` | NL solar (A75, B16), 15 Jun 2025: a consumption series (outBiddingZone) and the generation series (inBiddingZone) |
| `generation.xml` | FR generation per type, 1 Nov 2026, six PSR types incl. pumped-storage pumping |
| `flows_*.xml` | FR physical flows with BE (both directions), CH import (single point), GB export (PT60M) |
| `ack_no_data.xml` | acknowledgement "No matching data found" (reason 999) |
| `ack_interval_too_large.xml` | acknowledgement for a real error, also reason 999, sent with HTTP 400 |
