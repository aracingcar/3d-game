# 3d-game

A realistic 3D map of the Murray–Darling Basin region, forked from `mdb-model`. Climate and hydrology modelling are out of scope here; only the geography is used: the SDL unit outlines, terrain and river network for the Murrumbidgee, ACT, Lachlan, Lower Darling, NSW and Victorian Murray, Goulburn–Broken, Loddon and Wimmera–Mallee (`DISPLAY_SYSTEMS` in `1_masking/config.py`).

Play it at https://aracingcar.github.io/3d-game/game/ (page and code in `docs/game/`). Rebuild its data in `docs/game/data/` with `python game/build_map.py` (needs the DEM tile cache, SDL outlines and OSM waterways in `data/input/`, see the download scripts).

The original model README follows.

---

# MDB model

Daily climate-to-ecology chain for Murray–Darling Basin surface water SDL resource units, currently the Murrumbidgee (SS15), ACT (SS1), Lachlan (SS16), Lower Darling (SS18), NSW Murray (SS14), Victorian Murray (SS2), Goulburn (SS6) and Broken (SS5), run with `python main.py`.

1. `1_masking`: NARCliM2.0 4 km P and PET (ACCESS-ESM1-5, SSP2-4.5) area-weighted over terrain-derived reaches (HydroBASINS) inside the MDBA SDL unit outlines.
2. `2a_rainfall_runoff`: GR4J per basin, with one parameter set per river system calibrated on unregulated headwater gauges (see below).
3. `3a_routing`: Muskingum routing with channel rainfall, evaporation, seepage, miscellaneous losses and optional flow splits.
   `2b_calibration` and `3b_calibration` (not run by `main.py`): GR4J calibration on the BoM Hydrologic Reference Station gauges, and the observed gauge flow that routing and the Observed view are checked against (see below).
   `downloads`: the scripts that fetch inputs (SDL outlines, AWO climate, gauge flow, OSM waterways, roads and storages; the NARCliM download stays in `1_masking`, which runs it). `tests`: the Python (`python -m unittest discover -s tests -p 'test_*.py'`) and JavaScript (`node --test tests/*.test.cjs`) tests.
4. `4_ecology`: fish cease-to-flow refuge survival, colonial waterbird breeding trigger, river red gum condition, at each unit's outlet.
5. `5_outputs`: stores geometry and results in `data/results.db` (SQLite, git-ignored), one row per SDL unit, climate run and method pair.
6. `6_display`: builds the River Pulse page, published at `docs/index.html`, with every unit's reaches and SDL boundary on one map.

SDL units that share a river network are modelled together as a river system (`SYSTEMS` in `1_masking/config.py`): the upper Murrumbidgee flows into the ACT and the ACT drains back into SS15, so both are routed as one network, and every place a river crosses a unit border ends a reach. Each basin belongs to the unit holding most of its area. Per system the config sets the main-stem reach count, routing calibration (`loss_regions`, `target_outlet_m3s`; `None` leaves flow uncalibrated) and flow splits (a share of a basin's outflow sent to another basin or out of the river); per unit (`SDL_UNITS`) it sets the ecology thresholds (`None`, or a missing indicator, skips it). `main.py` runs each system in its own process (`SYSTEM=lachlan python main.py` runs one) and then builds the page from the database. Rows from before the SDL outlines, built on the CEWO Murrumbidgee valley, are kept under the key `CEWO-MBG`.

Rivers that leave one system and enter another are joined by `LINKS` in `1_masking/config.py` (from HydroBASINS' downstream links, each annotated with its landmark): the Goulburn, the Murray stub at its mouth and the Campaspe enter the Murray at Echuca, upstream of Torrumbarry Weir; the Murray (at Tooleybuc, with the Edward–Wakool) and the Murrumbidgee (at Balranald, near Boundary Bend) enter the Lower Darling system's Murray reach, upstream of Wentworth; the Lachlan spills into the Murrumbidgee at the Lowbidgee only above `spill_above_ML_d`, otherwise it ends in the Great Cumbung swamp. A link adds the routed outflow of its source basin to the outlet node of the target basin, so systems run in `RUN_ORDER` (a system after those feeding it; a loop is refused), each source's flow is kept in the `link_flows` table of `results.db`, and `docs/engine.js` and the page apply the links the same way. A downstream system fails with a clear message if the upstream system has no stored flow for the run, so run a climate run through `main.py` (all systems, in order) rather than one system alone. `joins` and `keep_links` in a system's config bridge a river that runs through basins outside the system, and keep a main-stem link whose mapped channel has gaps. Offtakes in the Murray are `splits` of shares of the flow: the Mulwala Canal and Yarrawonga Main Channel 17% at Lake Mulwala (Goulburn-Murray Water's ~1,900 GL a year) and the National Channel 6% (~500 GL a year) at Torrumbarry, all consumptive (they leave the system; the canal's escapes to the Edward are in the Edward's measured share); they are not allocation data. The Edward River takes 24.9% of the Murray's flow at Tocumwal into the Barmah–Millewa Forest (the Edward at Toonalook over the Murray at Tocumwal, 2012–2026) and runs past Deniliquin and Moulamein to the Wakool. A link with `fraction` (and `lag_days`) returns part of what a split sends out of its system: the Great Darling Anabranch takes 20.6% of the Darling below Menindee (Wycot over Weir 32 plus Wycot) and 54% of that reaches the Murray below Wentworth 68 days later; Yanco Creek's water reaches the Edward at Moulamein as 3.7% of the Murrumbidgee's flow (Billabong Creek's gain from Walbundrie to Darlot over Wagga), 37 days later. The rest of a split is lost on the way. Not modelled: Lake Mulwala and the weirs as storages, routing along the Anabranch and Billabong Creek (a return arrives as a lagged share), and the Billabong's own catchment, which needs NARCliM climate for its basins.

The MDB Model driving controls live in `6_display/car/`. Their browser-ready files are copied to `docs/car/` by `python 6_display/car/build.py` and whenever the display build runs.

The model is uncalibrated and indicative only. The Lachlan has no calibration gauge yet, so its losses use provisional defaults and terminal-river flow remains unvalidated. The Lower Darling carries its own local runoff plus the Murray and Murrumbidgee flowing in (see below), but not the Darling's inflow from the Barwon–Darling and the northern Basin, which is not modelled. The Murray's main terrain network (and so its calibration outlet) is the Barmah reach; the Edward–Wakool and the NSW catchments that drain straight into the Murray (such as the upper Murray) are reaches of their own (`min_network_km2`), and the Snowy releases and regulation are not routed in.

The Victorian pilot adds `vic_murray` (SS2) and `goulburn_broken` (SS6 + SS5), using the same MDBA outlines, HydroBASINS terrain and NARCliM climate sources. Goulburn and Broken route together across their unit boundaries; the Goulburn-Broken passes its outflow into the Murray (see below). Victorian Murray retains secondary networks of at least 500 km², so its selected unit outlet is not the sum of all drainage outlets or the full Murray discharge. Both systems are uncalibrated, with ecology indicators disabled pending appropriate local thresholds. No NSW/Victorian Murray network merger or Basin-wide climate download is included. The default pilot run remains ACCESS-ESM1-5/ssp245/WRF412R5; `run_climates.py` without selectors will request all known runs for the expanded set, so use an explicit selector when testing.

To run only the new systems (after fetching their waterways), use `SYSTEM=vic_murray python main.py` and `SYSTEM=goulburn_broken python main.py`, then `python 6_display/run_display.py`. Validate their stored inputs and routing with `SYSTEM=vic_murray python validate_victoria.py` and `SYSTEM=goulburn_broken python validate_victoria.py`; run `python 6_display/engine_parity.py` after building the display. See `plans/victoria_pilot.md` for validation findings and limitations.

Climate runs are stored once per SDL unit, reduced, in `data/results.db` (`climate` table: unit, reach and basin P/PET series plus the display's 4 km evaporation anomaly field). If a run is not in the database, `main.py` downloads its NARCliM subsets to `data/input/narclim/<system>/<global_model>/<scenario>/<regional_config>/`, reduces them, stores the result and deletes the raw `.nc` files (set `KEEP_RAW=1` to keep them). Choose the run with the `GLOBAL_MODEL`, `SCENARIO` and `REGIONAL_CONFIG` environment variables (defaults `ACCESS-ESM1-5`, `ssp245`, `WRF412R5`). Later runs read straight from the database, so a full run takes seconds.
Calibration data and GR4J calibration (after `main.py` has stored the basins): `python 3b_calibration/load_observed_flow.py` copies quality-filtered daily gauge flow per system from `mdb-river-pulse/data/river.db`; `python downloads/download_public_data.py` then `python downloads/download_hrs_flow.py` fetch BoM Hydrologic Reference Station flow (unregulated gauges with catchment areas); `SYSTEM=<system> python downloads/download_awo_climate.py` fetches BoM AWO observed daily rainfall and PET per model basin, 2012–2026 (NARCliM projections do not follow observed weather, so calibration needs it). `python 2b_calibration/calibrate_gr4j.py` fits GR4J to each HRS gauge (KGE, calibration 2013–2019, validation 2020–2026) and picks a regional set per system, writing `data/calibration/`. `gr4j.py` runs each system's highland basins on its regional set (`CALIBRATED`; the Lower Darling, with no HRS gauge, keeps the median set) and every system's plains on one set (`PLAINS`), and the page ships them per system and zone to `docs/engine.js`; copy a new calibration into `CALIBRATED` to adopt it. A basin's zone (`1_masking/aridity.py`) is plains if its observed aridity index (AWO rainfall over PET, 2012–2026) is under 0.7, so it does not change with the climate run. `python 2b_calibration/calibrate_gr4j.py --zones` picks the plains set from the saved fits: the set with the best median validation KGE over the 16 gauges under that aridity, Molonglo River at Burbong (410705). Scored leave-one-out, those gauges' median validation KGE rises from 0.13 with their system's set to 0.29 (13 of 16 better). The plains basins (aridity down to 0.13) are drier than every gauge (0.37), so the set is extrapolated there; the highland basins keep their system's set. The Lower Darling, all plains and with no gauge of its own local runoff, keeps the median set (`NO_PLAINS_SET`): the plains set cut its mean outlet flow by 91%, which no gauge supports. Routing uses the zones too: the plains wave speed is 0.65 m/s (the median lag between plains main-stem gauges, 2012–2026; Wagga to Redbank, 740 km, takes 12.2 days), the highland's stays ~1 m/s.
Inputs fetched by scripts: SDL unit outlines (`python downloads/download_sdl_units.py`), OpenStreetMap waterways per system (`SYSTEM=<system> python downloads/download_osm_waterways.py`) and display roads (`python downloads/fetch_roads.py`).
Rainfall-runoff and routing methods are modules in `2a_rainfall_runoff/` and `3a_routing/`; add a module name to `AVAILABLE_MODELS` in the matching `run_*.py` to offer it.
The display's Climate model panel lists the climate cases of `CLIMATE_CASES` in `1_masking/config.py` (best, median, worst). The median is the default run; every other case stored in the database for all units is built into `docs/data/<case>/` (sharing the default's geometry), and choosing it reloads the page on that run (`?case=best`). Cases not yet stored are listed as not built: `python run_climates.py NorESM2-MM/ssp126/WRF412R3` stores the best case and rebuilds the page.
The page opens on Observed (`?source=model` opens the climate model, as do links that pick a climate case, the full series or an editor). The panel at the top of the model controls picks the flow source: the climate model (with its rainfall-runoff and routing), Observed, or Your data. Observed and uploaded flows have no rainfall or evaporation, so the weather, evaporation shading and ecology go, the timeline runs over the record, and every river's flow is interpolated from the gauges (log-flow of the nearest three with a reading, within 150 km, weighted by inverse squared distance and favouring a gauge on the same named river); the gauge panel charts EWRs worked out from the flow. Observed is the BoM gauge records of `data/input/routing/*_observed_flow_daily.csv` at the EWR gauges that have one, over whole water years (`python 5_outputs/gauge_ewr.py evaluate observed`, then `export observed`). Your data takes a CSV of daily flow in ML/d (a `Date` column and `<gauge>_flow` columns, the EWR tool's standard time-series format); the page runs py_ewr on it in a worker under Pyodide (loaded from jsDelivr and PyPI on first use, nothing uploaded) and builds the results with `5_outputs/ewr_export.py`, the same code the Python export uses; `run_display.py` copies it to `docs/ewr/`. Gauges are placed from `data/input/routing/ewr_gauges.csv`; one not listed there is ignored.
Other global models require their own source member identifiers before downloading; changing the model name alone is insufficient.
Running `python main.py` (or `python 6_display/run_display.py` alone) rebuilds `docs/index.html` and `docs/data/`. The page opens on a small demo bundle (`docs/data/demo/`: 2027–2036 only, 2 km terrain, each basin's main channel and full-run evaporation normals, about 8 MB compressed). Zooming in on a river system, or picking one of its units, fetches its detail (`docs/data/demo/detail_<system>.json`: 1 km terrain and its other rivers, about 0.1–0.2 MB compressed), and the page rebuilds the terrain on a 1 km grid, interpolating the systems not yet loaded. Choosing other years or another method reloads it with `?data=full` on the full 2015–2100 series (`docs/data/full/`, 1 km terrain, about 60 MB compressed); the basin forcing the browser engine needs (`docs/data/engine_*.json`) and the roads (`docs/data/roads.json`) are fetched only when needed. Set the demo years with `DEMO_YEARS` in `6_display/run_display.py`. View it with `python -m http.server --directory docs`.
Only the default method pair is precomputed. Choosing another pair in the page re-runs the hydrology in the browser (`docs/engine.js`, in a Web Worker, one river system at a time) and saves the result in IndexedDB. `engine.js` implements the `gr4j` and `muskingum` algorithms; a method that only changes parameters needs no JavaScript, because its `ALGORITHM` and `PARAMS` are shipped to the page. A method with a new algorithm needs a JavaScript implementation in `engine.js` too. Bump `ENGINE_VERSION` in `6_display/template.html` when `engine.js` changes results. `python 6_display/engine_parity.py` checks that the engine matches the Python for every method pair and river system.
Data: NARCliM2.0 (CC BY 4.0), MDBA surface water SDL resource units (CC BY 4.0), HydroBASINS, OpenStreetMap contributors (ODbL). `data/input/catchment/` holds the CEWO MDB valleys (CC BY-SA 4.0) used before the SDL outlines.

### Channel water balance (provisional)

Routing now requires the same daily basin P/PET forcing as rainfall-runoff (`basin_forcing=`).
Each physical node uses its channel length and a **10 m fixed width** to estimate surface area,
capped at its allocated catchment area. The channel footprint is excluded proportionally from
GR4J runoff before delivery is applied, avoiding duplication when direct channel rainfall is added.
Synthetic LOWLAND runoff sources have no modelled channel footprint or channel losses.

Parameters in `3a_routing/muskingum.py` (shared by the alternate method) are initial guesses:

- `channel_width_m = 10`: representative fixed width, not surveyed geometry.
- `pet_factor = 1`: evaporation depth = PET times this factor; not an established conversion
  of NARCliM potential evaporation or AWO reference PET to open-water evaporation.
- `seepage_ML_day_km = 0.02`: potential losing-channel seepage per kilometre per day.
- `misc_loss_per_km = 0.001`: residual loss coefficient; fraction removed is
  `1 - exp(-coefficient * length_km)`, about 9.5% over 100 km.

After Muskingum routing, add rainfall (`P_mm * surface_km2` ML/day), then remove evaporation
(`PET_mm * pet_factor * surface_km2` ML/day) and seepage. If their combined demand exceeds
available routed water plus rain, reduce both proportionally. Apply miscellaneous loss to the
remainder, then operate the reservoir release cap, then split downstream flows. Rain can rewet
an otherwise dry channel; no evaporation or seepage occurs without available water.
These are daily outlet adjustments, not an explicit channel depth/storage or aquifer model:
they do not withdraw water from implicit routing storage or reservoir storage. Fixed width,
no floodplain/reservoir evaporation, no groundwater gains or bank-storage returns are limitations.

Where a mean outlet target exists, fit the miscellaneous coefficient in [0, 1]/km at the existing
selected basin outlet nodes after explicit fluxes; other nodes retain the provisional default.
If a target is outside the attainable range, warn and use the corresponding bound. A loss cannot
raise flow to a target. This residual fit can still compensate for runoff/input errors and is not
observational calibration of physical seepage, evaporation or routing parameters. Without a target,
all physical reaches use the default miscellaneous coefficient. Existing runoff delivery remains separate.

`basin_flow.attrs['channel_budget_ML']` contains per-node simulation totals for routed water,
rainfall, actual evaporation, actual seepage, miscellaneous loss and after-flux volumes in ML.
Reservoir storage/release is reported separately in `attrs['storages']`. Budgets are in-memory
diagnostics, not persisted in results.db; each pipeline run prints system totals. For small diagnostic
runs, `route_network(record_budget=True)` returns daily per-node budgets; the main pipeline uses
`record_budget="totals"` to avoid large memory costs. The browser routing API can return daily budgets
with its optional `recordBudget=true` argument. The worker omits these large diagnostics.
`attrs['stranded_ML']` holds, per basin, the delivered runoff of watersheds whose streams end off the
river system (on the plains or in terminal lakes; `nodes.connected` drops them): it leaves the water
balance there and is printed per system: over the three climate cases, 11–13% of the Lachlan's delivered
runoff, 37–41% of the Lower Darling's (from about 14% of its area) and 2–3% of the Murrumbidgee's.

Each reach's travel time is K = channel length / wave speed. A daily Muskingum reach is stable only for
K up to about 2.5 days at x = 0.2, so a reach with K over 2.4 days (over ~207 km at 1 m/s) is routed as
ceil(K / 2.4) equal sub-reaches in series, which keeps its whole travel time (Muskingum's mean lag is K)
and adds attenuation. Before, K was capped at 2.4 days, so the Lachlan below Hillston (273 km) and the
Talyawalka reach arrived early.

Network checks: `nodes.check_network` refuses a network with repeated node IDs, connections to missing
nodes or loops when it is built. `tests/test_network.py` checks the built engine data: every system
is a DAG ending at its outlet, `LINKS` leave from system outlets into basins that have a node, the linked
systems form one DAG ending at the Murray at the South Australian border, and long reaches and a
headwater-to-outlet network conserve water.

Fast full-record routing parity (all systems and method pairs):
`.venv/bin/python 3a_routing/check_flux_parity.py` uses the exported network and P/PET.

Validation: `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'` and
`.venv/bin/python 6_display/engine_parity.py`. Re-run `main.py` to refresh stored results and the page.

### Interactive network editing

Open **Routing → Edit** in the display and select a river node. Drag the selected node (or use **Move node** and a map click) to move it; every reach touching it becomes a straight line. Drag any reach line to reshape it: a reach still following the mapped river becomes its broad bends, and the press grabs the nearest bend or adds one. Moved, joined and reshaped reaches route over their drawn length. Use **Add tributary** followed by a map click to create an upstream branch, or **Reconnect downstream** followed by a node click to change its destination. New tributaries take the chosen percentage (25% by default) of the selected node's existing catchment area and runoff share, using the same basin rainfall/PET. They do not delineate a new catchment or introduce additional water. Changed connections use the length of their drawn path for the existing routing calculations.

**Join channel** fixes a branch whose runoff enters the river too far downstream: a new junction appears just below the selected node; drag it onto the channel it should join (it snaps to the nearest line). That channel's reach is split at the junction, keeping its length, and the junction takes the share of the reach's local runoff above it. Nodes left below with no inflow are deleted.

**Detach inflow** reroutes a reach flowing into the selected node past it, on down the channel to the node below (its length the two reaches combined): a river reach becomes a runoff entry, and a junction left with one inflow becomes a river reach. With more than one inflow, click the reach (or its upstream node) to detach.

Nodes show their role on the river (runoff entry, reach, junction); a basin outlet looks like any other node and its status line names the basin whose flow it reports. **System link** marks where another river system's water enters or leaves. **Delete node** bypasses a node: its runoff share goes to the node below within the same basin, or else joins that node directly as a watershed of its own basin, so every basin's runoff total is kept. Deleting a basin outlet moves that basin's flow reporting to the node below. System links, dams and calibration nodes cannot be deleted or reconnected, preserving river-system connections, calibration and operating rules. Flow-split nodes and the nodes that receive a split are ordinary nodes: moving one redraws its diversion, deleting a node that receives a split sends that share to the node below (or ends it where that is the splitting node's own main channel), deleting a splitting node ends its splits, and reconnecting a node onto its split target removes the redundant split. Connections that create loops are refused. **Undo** reverses edits during the editing session; **Reset network** restores the selected system and can itself be undone.

To make edits part of the model, **Export draft** (it downloads as `<system>-network.json`) and replace that system's file in `river_systems/`, then rerun `main.py`; see `river_systems/README.md`. Edits are saved locally per system and engine-data version. **Apply & recalculate flows** runs all systems in dependency order through the unchanged browser hydrology functions, including their existing calibration procedure. The quick demo first loads the full climate record for correct forcing and model initialisation. The flow series and ecological indicators update; existing mapped river geometry is retained underneath the editable network overlay. **Export draft** downloads the edited graph and catchment shares as JSON. Edits do not overwrite Python inputs, calibration settings, published data or the result cache for the original network.

Run the network editor checks with `node tests/network-editor.test.cjs`. These include runoff-share conservation, protected nodes, cycle rejection, joining a channel, deleting basin outlets, persistence, undo and integration calculations with the unchanged hydrology engine.
