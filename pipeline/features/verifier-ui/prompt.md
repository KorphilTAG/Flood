Implement exactly the spec at the path below. Read it in full first, then read `docs/specs/physics-engine-cycles.md` (sections "File ownership" and "Interface freeze"), `docs/contracts/contract-1-physics-products.md` section 9, `docs/contracts/examples/state-response.json`, `docs/contracts/examples/reaches.sample.json`, `docs/contracts/examples/gauges.sample.json`, `src/flood/interfaces.py` (for `RASTER_BANDS`), and `pipeline/features/clock-service/spec.md` (for the clock JSON shape and WebSocket message). Follow "Files to change" and "Implementer notes" literally. You own only `src/flood/verifier/**`, `tests/test_verifier_static.py`, and one added line in `pyproject.toml`. Do not touch anything else; if you need a change elsewhere, record it under Residual risk in changes.md. Do not commit, stage, or run any git command that changes state.

Spec: pipeline/features/verifier-ui/spec.md

Environment:
- You are at the root of a git worktree on branch `feature/verifier-ui`. Windows 11; use PowerShell syntax for shell commands.
- First create the environment: `py -3.12 -m venv .venv` then `.venv\Scripts\python.exe -m pip install -e ".[dev]"`. Use `.venv\Scripts\python.exe` for everything, including `-m pytest -q`.
- Copy `pipeline/templates/changes.md` to `pipeline/features/verifier-ui/changes.md`, fill the Slug and Spec lines, and keep it updated as you work.
- The API (cycle C07) is being written concurrently and does not exist in this worktree, so you cannot run the page against a live server. Build it strictly against the contract. Put every endpoint template in one `API` object at the top of `app.js`, exactly these, with `{run}` substituted client side:
  - `GET /scenarios`, `GET /scenarios/{scenario_id}`
  - `GET /runs`, `GET /runs/{run}`
  - `GET /runs/{run}/state?p=&t=` (also `p=hindsight`)
  - `GET /runs/{run}/reaches?p=&t=`
  - `GET /runs/{run}/gauges?p=`
  - `GET /runs/{run}/overlay.png?p=&t=&band=&max_px=2048` with response header `X-Bounds-3857: xmin,ymin,xmax,ymax` in Web Mercator metres
  - `GET /runs/{run}/skill` (404 with `{"error":{"code":"skill_not_computed"}}` until computed)
  - `GET /clock`, `POST /clock` with a JSON subset of `{t, speed, playing}`, `POST /clock/reset`, WebSocket `/clock/ws` that sends `{mode, t, speed, playing, record_start, record_end}` on connect and on every change or tick
- Response shapes are exactly the three example files named above; timestamps are ISO strings ending in `Z`. Errors are `{"error": {"code", "message"}}`; render them in the banner, never throw.
- Libraries: Leaflet 1.9.4 and Chart.js 4.4.x from `https://cdnjs.cloudflare.com/ajax/libs/...` with pinned versions and `integrity` attributes copied from cdnjs. No other network dependencies, no build step, no framework. Basemap: OpenStreetMap standard tiles with attribution.
- Convert `X-Bounds-3857` to a Leaflet bounds with `L.CRS.EPSG3857.unproject(L.point(x, y))` for the two corners. Fetch overlays with `fetch` so the header is readable, then `URL.createObjectURL(blob)` for the `ImageOverlay`.
- `src/flood/verifier/__init__.py` must exist so the static directory ships; add `"flood.verifier" = ["static/*"]` under `[tool.setuptools.package-data]` in `pyproject.toml` and record that single-line cross-owner edit in changes.md.
- `tests/test_verifier_static.py`: assert the three static files exist in the package, that `index.html` references `app.js` and `style.css`, and that every URL template in the `API` object of `app.js` (parse with a regex over the file text) appears in a fixed list of contract paths written in the test. Guard the server checks with `pytest.importorskip("flood.api.app")` so they skip here and run once C07 merges.
- The manual checklist in the spec cannot be executed in this worktree. Copy it into changes.md with every item marked "deferred to fix-up" and say why.
- Acceptance criteria are the definition of done for everything you can execute. Run pytest until green.
- Finish: run `.venv\Scripts\python.exe -m pytest -q` and paste the output into changes.md under "How to verify".

Work order: `index.html` layout; `style.css`; `app.js` state object, `API` object, clock WebSocket, mode derivation (nowcast `p=t`; forecast `p=clockT, t=p+h`; stale `t=clockT, p=t-lag`), debounce and `AbortController`, overlay, gauge charts, reach table, skill table, timing readout, error banner; `tests/test_verifier_static.py`; `pyproject.toml` line.
