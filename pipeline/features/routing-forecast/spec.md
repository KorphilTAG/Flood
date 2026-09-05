# Feature spec

- Slug: routing-forecast
- Feature: C05. Muskingum-Cunge routing over the reach network with gauge controls by role, junction inference, and the `trend_relax` boundary forecast, producing a `RoutedSeries` for a cutoff `p` and three members.
- Status: draft
- Product refs: `docs/specs/physics-engine-master.md` sections 6.3 to 6.5; decision 0001 stages 1 to 3; C01 spec (`ForcingView`, `RoutedSeries`, fixture network and forcing).

## Problem

This is the forecasting core. Given what is known at `p`, produce discharge on every reach from `p - 360 min` to `p + max_horizon` so that observed water is carried downstream with realistic lag, gauges are honoured where known, and unknown inflow is extrapolated as an ensemble.

## In scope

- `engine/boundary.py`: `trend_relax`, `persistence`.
- `engine/routing.py`: `route(cube, view, scenario, config) -> RoutedSeries`, Muskingum-Cunge step, topological order, controls, junction inference, source coding.
- Tests on the fixture: mass conservation, lag, control reproduction, member ordering, source codes.

## Out of scope

Mapping to rasters, products, run orchestration, `nwm_short_range` and `blend` methods (C13), rainfall (C14).

## Approach

Precompute topological order from `to_feature_id`. Iterate `tau` on a `dt_minutes` grid; for each reach in order compute inflow as the sum of upstream outflows at `tau` plus lateral inflow, apply one Muskingum-Cunge step with parameters from the rating table at a reference discharge, then apply controls. Repeat for the three members, which differ only in the `trend_relax` multiplier. Downsample to the 5-minute grid on output if `dt_minutes < 5`.

## Files to change

| Path | Action (add/edit) | Why |
|---|---|---|
| `src/flood/engine/boundary.py` | add | Forecast functions |
| `src/flood/engine/routing.py` | add | Routing |
| `tests/test_boundary.py`, `tests/test_routing.py` | add | Tests |

## Acceptance criteria

- [ ] `trend_relax(series: pd.Series, tau: datetime, m: float, relax_minutes: int, trend_window_minutes: int) -> float`: with `t_last = series.index.max()`, `q0 = series.iloc[-1]`, `q_prev = np.interp` of the series at `t_last - trend_window` (or the first value if the series is shorter), `r = (q0 - q_prev) / trend_window_minutes`, `d = (tau - t_last)` in minutes; returns `max(0.0, q0 + m * r * relax_minutes * (1 - exp(-d / relax_minutes)))`; for `tau <= t_last` returns `np.interp` of the series at `tau`. `persistence(series, tau)` equals `trend_relax` with `m = 0`. Tests: `d = 0` returns `q0`; `d -> inf` returns `q0 + m r relax`; `m = 0` is constant.
- [ ] `mc_params(rt, cidx, q_ref, length_m, slope, dt_s) -> (K, X)`: `c = celerity(rt, cidx, q_ref)`, `B = top_width(rt, cidx, stage_from_q(...))`, `K = length_m / c`, `X = clip(0.5 * (1 - q_ref / (B * slope * c * length_m)), 0.0, 0.5)`. Reaches with `representative_cidx == -1` use `c = (1/0.06) * 1.0 ** (2/3) * sqrt(slope) * 5/3` and `B = 10`.
- [ ] `mc_step(q_in_prev, q_in_next, q_out_prev, K, X, dt) -> float`: `denom = 2K(1-X) + dt`; `C0 = (dt - 2KX)/denom`, `C1 = (dt + 2KX)/denom`, `C2 = (2K(1-X) - dt)/denom`; result `max(0, C0 q_in_next + C1 q_in_prev + C2 q_out_prev)`. When `dt > 2K(1-X)`, sub-step `n = ceil(dt / (2K(1-X)))` times with linear interpolation of inflow, so `C2 >= 0`. Test: constant inflow reaches steady state equal to inflow within 1e-6; coefficients sum to 1.
- [ ] `route(cube, view, scenario, config, members=MEMBERS) -> RoutedSeries`:
  - `taus` from `p - 360 min` to `p + max_horizon_minutes` at `STEP_MINUTES`; internal step `config.routing.dt_minutes`.
  - Topological order from `to_feature_id`; cycles raise `ValueError`.
  - Inflow `q_in(tau) = sum(Q_out upstream at tau) + view.qlat(fid, tau)`.
  - Headwater reaches with no gauge: `Q_out` is the routed value of lateral inflow only, `source` `nwm_analysis_scaled` when `view.ratio(fid) != 1.0` else `nwm_analysis`, or `forecast_nwm_sr` when `qlat` came from short range (expose `view.qlat_source(fid, tau)` if available via `getattr`, default analysis).
  - Controls at reaches whose `gauge_site` has role `boundary` or `interior`: while an observation exists at `tau` (`tau <= t_last` of `view.obs_q(site)`), `Q_out(tau) = interp(obs, tau)`, `source = observed`. After `t_last`: `interior` gets `routed(tau) + (obs(t_last) - routed_uncontrolled(t_last)) * exp(-(tau - t_last)/relax)` with `source = routed`; `boundary` gets `trend_relax(obs, tau, m_member)` with `source = forecast_trend`. `validation_only` gauges are ignored.
  - Junction inference when `use_junction_inferences`: for each entry, `Q_out(inferred_reach, tau) = max(0, interp(obs(downstream_gauge), tau + travel) - sum(interp(obs(g), tau)))` while every needed observation exists, `source = mass_balance`; afterwards `trend_relax` on the inferred series so far, `source = forecast_trend`. Inferred reaches are computed before their downstream neighbours regardless of topological ties.
  - Members: `m = config.boundary_forecast.members[name]`; only `trend_relax` calls depend on `m`.
  - `routed_uncontrolled` is the Muskingum-Cunge output before any control, kept per reach for the bias term.
  - Output `q` float32 `[3, R, T]`, `source` int8 `[R, T]` from the mid member, `feature_ids` in `cube.network` row order.
- [ ] Fixture tests (`p = 04:00Z`, `max_horizon 360`):
  - Control reproduction: for reach 101 and 103 at every `tau <= 03:55Z`, `q[mid]` equals the fixture observation within 1e-4.
  - Mass balance: with lateral inflow zeroed via a monkeypatched `qlat` returning 0, the time-integrated outflow of reach 106 over the whole window is within 2 percent of the integrated inflow at 103 plus what was already in storage, computed as the integral of `Q_out(103)` shifted by the summed `K` of 104 to 106.
  - Lag: the peak time of `q[mid]` at reach 106 is later than at 103 by an amount within 30 percent of `sum(length_m / c)` over 104 to 106 at the peak discharge.
  - Members: `q[low] <= q[mid] <= q[high]` at reach 101 for `tau > 03:55Z`; all three equal for `tau <= 03:55Z`.
  - Junction: reach 102 at `03:00Z` equals `obs_90000003(03:10Z) - obs_90000001(03:00Z)` within 1e-3 and has source `mass_balance`.
  - Sources: 101 is `observed` before `t_last` and `forecast_trend` after; 104 is `routed` throughout; 103 is `observed` then `routed`.
- [ ] Hindsight behaviour: with `p = record_end`, no `forecast_trend` code appears anywhere.
- [ ] `pytest -q` green offline. Routing the fixture for one `p` takes under 2 seconds.

## Non-goals and constraints

- No numpy vectorisation across reaches is required; a Python loop in topological order is acceptable. If timing in C06 demands, vectorise by topological level later.
- Do not edit `interfaces.py`.
- No scenario literals.

## Assumptions

- Observation series are dense enough that `np.interp` in time is acceptable.
- Lateral inflow from `view.qlat` already includes the bias ratio.

## Open questions

- None.

## Implementer notes

- Fixture access: `mini_cube`, `mini_scenario`, and `mini_data_dir` fixtures from `tests/conftest.py`; build the view with `ParquetForcingView(mini_scenario, load_forcing_store(mini_scenario, mini_data_dir), p, gauges=mini_cube.gauges)` (signature per C04).
- Work in seconds internally: `dt_s = config.routing.dt_minutes * 60`; convert `taus` to `np.datetime64[s]`.
- Keep per-reach state arrays sized `[n_steps]` for `q_in` and `q_out`; the memory is small (244 reaches by 8641 steps at 1 minute).
- `interp(series, tau)`: `np.interp(tau_s, series.index.view("int64") // 1e9, series.values)` with the series' first value held for `tau` before the first index.
- For interior post-`t_last` bias: store `bias0 = obs(t_last) - routed_uncontrolled(t_last)` once at the first `tau > t_last`.
- Downsample to 5 minutes by taking the exact `tau` samples that fall on the 5-minute grid; do not average.
