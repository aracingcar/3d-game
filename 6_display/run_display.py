"""Build the River Pulse page, docs/dashboard.html, for every SDL unit of the displayed river systems, from results.db.

The page shows every unit's reaches and SDL boundary on one map. Its data files in docs/data/ are split so each stays
well under GitHub's file size limit: geometry, a shared evaporation pixel index, and per river system the climate
series (with each unit's evaporation values), the flow results and the browser engine's forcing.
"""
import base64
import hashlib
import json
import re
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy.ndimage import binary_dilation

for folder in ("1_masking", "2a_rainfall_runoff", "3a_routing", "5_outputs"):  # also runs on its own: python 6_display/run_display.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / folder))

from aridity import basin_zones
from catchment import buffer_outline
from config import CLIMATE_CASES, DEFAULT_RUN, DISPLAY_SYSTEMS, LINKS, SDL_UNITS, SYSTEMS, waterways_file
from evap_grid import PIXEL_DEG
from nodes import basin_outlets, build_nodes, connected
from results_db import load_climate, load_geometry, load_results
from run_rainfall_runoff import RAINFALL_RUNOFF_MODEL, model_specs as runoff_specs
from run_routing import ROUTING_MODEL, model_specs as routing_specs
from terrain import Dem
from car.build import publish_assets

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
DISPLAY_FILE = HERE.parent / "docs" / "dashboard.html"
DATA_DIR = HERE.parent / "docs" / "data"
CONTEXT_RIVERS = 120  # per river system: longest other named rivers drawn as thin context lines


def _rings(geom, dem=None, ndigits=4):
    """Exterior rings as [lon, lat] points, with the ground elevation (m) as a third value if a DEM is given."""
    out = []
    for p in shapely.get_parts(geom):
        if p.geom_type != "Polygon":  # a repaired geometry can be a collection of collections, or carry stray lines
            out += _rings(p, dem, ndigits) if hasattr(p, "geoms") else []
            continue
        if p.is_empty:
            continue
        pts = np.array(p.exterior.coords)[:, :2]
        z = np.round(dem.at(pts[:, 0], pts[:, 1])).astype(int) if dem is not None else None
        out.append([[round(x, ndigits), round(y, ndigits), *([int(z[i])] if z is not None else [])] for i, (x, y) in enumerate(pts)])
    return out


def _drop_duplicate_borders(rivers, tol_m=100):
    """A river along the border between two systems is kept by both (each keeps rivers up to OUTLINE_BUFFER_KM past its
    own border). Where the same named river is drawn twice, remove the copy that carries no flow (share 0), or the later
    one if neither does, so each stretch is drawn once and a routed copy wins over an unrouted one."""
    metric = rivers.to_crs("EPSG:3577")
    geoms = metric.geometry.copy()
    for i in metric.index[metric["share"] == 0]:
        other = metric.index[(metric["name"] == metric.at[i, "name"]) & (metric.index != i) & ((metric["share"] > 0) | (metric.index < i))]
        if len(other) == 0:
            continue
        near = shapely.union_all(geoms.loc[other].values).buffer(tol_m)
        geoms.at[i] = geoms.at[i].difference(near)
    kept = ~geoms.is_empty & (geoms.length > 0)
    out = rivers.copy()
    out["geometry"] = gpd.GeoSeries(geoms, crs=metric.crs).to_crs(rivers.crs)
    return out[kept].reset_index(drop=True)


def _ribbon(line, mean_flow, peak, dem):
    width = 0.0018 + 0.0115 * np.sqrt(mean_flow / peak)
    ribbon = line.buffer(width, cap_style=2, join_style=2).simplify(0.001)
    return None if ribbon.is_empty else _rings(ribbon, dem)


GAP_DEG = 0.4  # main-stem mapping gaps up to this (~45 km, Lake Hume) are drawn across


def _gap_links(rivers, max_deg=GAP_DEG):
    """Straight pieces across the gaps in a main stem's mapping (OSM has none across lakes, forests and anabranches): for each
    main-stem river, the nearest ends of unjoined pieces within max_deg are linked, nearest first.
    Returns [(line, river_id of one side, river_id of the other)]."""
    links = []
    for name in {s["mainstem"] for s in SYSTEMS.values()}:
        parts = [(g, r.river_id) for r in rivers[rivers["name"] == name].itertuples() for g in shapely.get_parts(r.geometry)]
        lines = np.array([g for g, _ in parts], dtype=object)
        parent = list(range(len(parts)))

        def root(i):
            while parent[i] != i:
                i = parent[i]
            return i

        for i, j in shapely.STRtree(lines).query(lines, predicate="dwithin", distance=1e-4).T:
            parent[root(i)] = root(j)
        ends = [(shapely.Point(c), i) for i, g in enumerate(lines) for c in (g.coords[0][:2], g.coords[-1][:2])]
        pairs = sorted((a.distance(b), n, m) for n, (a, i) in enumerate(ends) for m, (b, j) in enumerate(ends) if n < m and i != j and a.distance(b) <= max_deg)
        for _, n, m in pairs:
            (a, i), (b, j) = ends[n], ends[m]
            if root(i) != root(j):
                parent[root(i)] = root(j)
                links.append((shapely.LineString([a, b]), parts[i][1], parts[j][1]))
    return links


def _rivers(rivers, mean_flow, dem):
    """Ribbons (width grows with mean flow) for every river segment, plus thin context lines for unrouted rivers."""
    peak = mean_flow.max()
    reaches = []
    for r in rivers.itertuples():
        rings = _ribbon(r.geometry, mean_flow[r.river_id], peak, dem)
        if rings:
            reaches.append({"unit": r.river_id, "name": r.name, "kind": r.kind, "rings": rings})
    for line, a, b in _gap_links(rivers):  # drawn with the flow of whichever side carries more
        rings = _ribbon(line, max(mean_flow[a], mean_flow[b]), peak, dem)
        if rings:
            side = rivers[rivers["river_id"] == a].iloc[0]
            reaches.append({"unit": a, "name": side["name"], "kind": side["kind"], "rings": rings})
    ways = pd.concat([gpd.read_file(waterways_file(s)) for s in DISPLAY_SYSTEMS], ignore_index=True)
    ways = ways[(ways.waterway == "river") & (ways.name != "") & (~ways.name.isin(set(rivers["name"])))].drop_duplicates("osm_id")
    top = ways.assign(len=ways.length).sort_values("len", ascending=False).head(CONTEXT_RIVERS * len(DISPLAY_SYSTEMS))
    context = [_rings(g.buffer(0.0025, cap_style=2).simplify(0.001), dem) for g in top.geometry if not g.is_empty]
    return reaches, [r for rings in context for r in rings]


GRID_STEP = 0.01  # degrees (~1 km) for the terrain cells
DEMO_GRID_STEP = 0.02  # coarser terrain (~2 km) for the demo bundle the page opens on
DEMO_YEARS = (2027, 2036)  # the years the page opens on
LEAD_DAYS = 120  # the page's longest look-back (the 120-day evaporation bars; rain rolls over 60); the demo bundle starts this much early
ROLL_EVAP = 30  # the page's rolling evaporation window


def _terrain(units, dem, step=GRID_STEP):
    """Ground cells inside the modelled units: position, elevation, owning subcatchment and hillshade, plus per-unit stats."""
    minx, miny, maxx, maxy = units.total_bounds
    lons = np.arange(minx, maxx + step, step)
    lats = np.arange(maxy, miny - step, -step)  # north to south
    gx, gy = np.meshgrid(lons, lats)
    elev = dem.at(gx, gy)
    owner = np.full(gx.shape, -1)
    for i, geom in enumerate(units.geometry):
        owner[shapely.contains_xy(geom, gx, gy)] = i
    rows, cols = np.nonzero(binary_dilation(owner >= 0, iterations=3))  # a margin of ground beyond the valley, trimmed smoothly by the page
    stats = []
    for i in range(len(units)):
        e = elev[owner == i]
        stats.append({"mean": int(e.mean()), "min": int(e.min()), "max": int(e.max())} if e.size else {"mean": 0, "min": 0, "max": 0})
    return {"x0": round(float(lons[0]), 4), "y0": round(float(lats[0]), 4), "step": step,
            "col": cols.tolist(), "row": rows.tolist(), "elev": np.round(elev[rows, cols]).astype(int).tolist(),
            "unit": owner[rows, cols].tolist()}, stats


def _quantised(basin_forcing, names, var):
    """Basin series as base64 little-endian uint16 in hundredths of a mm/day, basin-major."""
    a = np.stack([basin_forcing[f"{n}_{var}"].to_numpy() for n in names])
    return base64.b64encode(np.clip(np.round(a * 100), 0, 65535).astype("<u2").tobytes()).decode()


LONG_FLOAT = re.compile(r"(?<![\w.])(-?\d+\.\d{7,})(?![\w.])")


def compact_floats(text):
    """float32 values arrive as 17-digit doubles (0.20000000298023224); six decimals is finer than any display or
    routing use, and shrinks the climate and engine files several-fold."""
    return LONG_FLOAT.sub(lambda m: repr(round(float(m.group(1)), 6)), text)


AREA_SIMPLIFY_DEG = 0.004  # ~400 m: the runoff editor's node areas keep their shared borders but not every vertex of the HydroBASINS outline


DOT_DISC_DEG, DOT_BRIDGE_DEG, DOT_SPOT_DEG = 0.01, 0.002, 0.0005  # ~1 km disc round a dot that falls outside its area, the ~200 m strip joining it to the area, and the ~50 m spot every dot keeps


def _contain_dots(areas, dots):
    """Give every node an area that holds its dot (a point on the river): an area that misses it takes in a small disc round the
    dot and a strip to the area (a node with no watershed, such as an added junction, gets the disc alone). The patch is carved
    from the neighbours it crosses but never from the spot round another dot nor an earlier patch, so the areas still do not overlap."""
    areas, held = list(areas), shapely.Polygon()
    spots = [shapely.buffer(d, DOT_SPOT_DEG) for d in dots]
    for k, dot in enumerate(dots):
        if not areas[k].is_empty and areas[k].covers(dot):
            continue
        disc = shapely.buffer(dot, DOT_DISC_DEG)
        patch = disc if areas[k].is_empty else shapely.union(shapely.buffer(shapely.shortest_line(areas[k], dot), DOT_BRIDGE_DEG), disc)
        patch = shapely.union(shapely.difference(patch, shapely.union_all([held, *spots[:k], *spots[k + 1:]])), spots[k])
        areas = [shapely.union(g, patch) if j == k else g if g.is_empty else shapely.difference(g, patch) for j, g in enumerate(areas)]
        held = shapely.union(held, patch)
    return areas


def _areas(nodes, basins):
    """The runoff areas the page's editor starts from: each node's watershed inside its basin, as {node id: rings of [lon, lat]}.
    Neighbouring areas are simplified together, so a shared border stays shared and its vertices can be dragged as one.
    Every node has an area, and it holds the node's dot."""
    watersheds = nodes.attrs["watersheds"]
    parent = basins.set_index("subcatchment").geometry.make_valid()
    empty = shapely.Polygon()
    rows = [(n.id, shapely.intersection(shapely.make_valid(watersheds[n.id]), parent[n.basin]) if n.id in watersheds.index else empty) for n in nodes.itertuples()]
    polygonal = [shapely.union_all([p for p in shapely.get_parts(g) if p.geom_type == "Polygon"]) if not g.is_empty else g for _, g in rows]
    simple = shapely.coverage_simplify(np.array(polygonal, dtype=object), AREA_SIMPLIFY_DEG, simplify_boundary=False)
    dots = nodes.set_index("id").loc[[i for i, _ in rows]]
    simple = _contain_dots(simple, shapely.points(dots["lon"].to_numpy(), dots["lat"].to_numpy()))
    return {"cells": {i: [r for r in _rings(g) if len(r) > 3] for (i, _), g in zip(rows, simple) if not g.is_empty}}


def _engine(system, basins, basin_forcing, regions, rivers, nodes):
    """Everything the browser needs to re-run one river system's rainfall-runoff, routing, river flows and ecology on another method pair."""
    names = list(basins["subcatchment"])
    splits = SYSTEMS[system]["splits"]
    storages = SYSTEMS[system].get("storages", {})
    outlet = basin_outlets(nodes)
    zones = basin_zones(system, basins)  # rainfall-runoff and routing parameter zone
    return {
        "system": system,
        "scale": 100,
        "basins": [{"id": b.subcatchment, "area": float(b.area_km2), "next": b.next_id, "lossRank": int(b.from_outlet), "zone": zones[b.subcatchment],
                    "lon": round(b.geometry.representative_point().x, 4), "lat": round(b.geometry.representative_point().y, 4)}
                   for b in basins.itertuples()],
        # routing nodes: where each basin's runoff (its area share) joins the river. River nodes (river: true) are linked along the river by ``path``; the others join the river node below them directly
        "nodes": [{"id": n.id, "basin": n.basin, "share": float(n.share), "area": float(n.area_km2), "length": None if pd.isna(n.length_km) else float(n.length_km),
                   "next": n.next, "lon": n.lon, "lat": n.lat, "outlet": bool(n.outlet), "lossRank": int(n.loss_rank),
                   **({"river": True, **({"path": n.path} if isinstance(n.path, list) else {}), **({"straight": True} if n.straight else {})} if n.river else {}),
                   **({"splitPath": n.split_path} if isinstance(n.split_path, list) else {}),
                   **({"reports": n.reports} if isinstance(n.reports, list) else {}),  # basins whose flow is read here (an applied editor draft)
                   **({"storage": n.storage, "maxRelease": storages[n.storage]["max_release_ML_d"]} if n.storage else {}),
                   **({"splits": {(outlet[to] if to else ""): f for to, f in splits[n.basin].items()}} if n.outlet and n.basin in splits else {})}
                  for n in nodes.itertuples()],
        "calibration": SYSTEMS[system]["routing"],
        # water other river systems send in (config.LINKS): their routed outflow of `basin` enters node `node`; and the basins of this system others take from
        "inflows": [{"node": outlet[l["into"]], "from": l["from"], "basin": l["basin"], **({"above": l["spill_above_ML_d"]} if "spill_above_ML_d" in l else {}),
                     **({"fraction": l["fraction"]} if "fraction" in l else {}), **({"lag": l["lag_days"]} if "lag_days" in l else {})}
                    for l in LINKS if l["to"] == system],
        "exports": sorted({l["basin"] for l in LINKS if l["from"] == system}),
        "P": _quantised(basin_forcing, names, "P"),
        "PET": _quantised(basin_forcing, names, "PET"),
        "reachOutlet": {r.subcatchment: r.outlet_basin for r in regions.itertuples()},
        "rivers": [[r.river_id, r.basin, r.kind, r.share] for r in rivers.itertuples()],
        "units": {u: {"outlet": regions.loc[regions["sdl_unit"] == u, "unit_outlet"].iloc[0], "ecology": SDL_UNITS[u]["ecology"]}
                  for u in SYSTEMS[system]["units"]},
    }


def _evap(grids):
    """One pixel index over every unit's evaporation raster (they share a PIXEL_DEG lattice), each unit's 4 km cells
    numbered after the previous unit's; returns (index, {unit: base64 values}). Where rasters overlap the first unit wins."""
    first = next(iter(grids.values()))
    assert all(g["dates"] == first["dates"] and g["scale"] == first["scale"] for g in grids.values())
    minx, miny = min(g["bbox"][0] for g in grids.values()), min(g["bbox"][1] for g in grids.values())
    maxx, maxy = max(g["bbox"][2] for g in grids.values()), max(g["bbox"][3] for g in grids.values())
    nx, ny = round((maxx - minx) / PIXEL_DEG), round((maxy - miny) / PIXEL_DEG)
    idx, weights = np.full((ny, nx, 4), -1), np.zeros((ny, nx, 2), dtype="float32")
    parts, offset = [], 0
    for u, g in grids.items():
        r0, c0 = round((maxy - g["bbox"][3]) / PIXEL_DEG), round((g["bbox"][0] - minx) / PIXEL_DEG)
        gi, gw = g["idx"].reshape(g["ny"], g["nx"], 4), g["weights"].reshape(g["ny"], g["nx"], 2)
        sub_i, sub_w = idx[r0:r0 + g["ny"], c0:c0 + g["nx"]], weights[r0:r0 + g["ny"], c0:c0 + g["nx"]]
        take = (gi[..., 0] >= 0) & (sub_i[..., 0] < 0)
        sub_i[take], sub_w[take] = gi[take] + offset, gw[take]
        parts.append([u, int(g["values"].shape[1])])
        offset += g["values"].shape[1]
    assert offset < 65535, "too many 4 km cells for the page's uint16 index"
    index = {"bbox": [round(v, 4) for v in (minx, miny, maxx, maxy)], "nx": nx, "ny": ny, "dates": first["dates"], "scale": first["scale"],
             "cells": offset, "parts": parts,
             "idx": base64.b64encode(np.where(idx < 0, 65535, idx).astype("<u2").tobytes()).decode(),
             "weights": base64.b64encode(np.round(weights * 255).astype("uint8").tobytes()).decode()}
    return index, {u: base64.b64encode(g["values"].tobytes()).decode() for u, g in grids.items()}


def _label_point(geom, dem):
    p = geom.representative_point()
    return [round(p.x, 4), round(p.y, 4), int(dem.at(p.x, p.y))]


def _table(df):
    return None if df is None else df.reset_index().round(3).to_dict("list")


def _birds(df):
    if df is None:
        return None
    return {**df.reset_index().drop(columns="trigger_date").to_dict("list"), "trigger_date": [None if v != v else str(v) for v in df["trigger_date"]]}


def _evap_normals(sub, names, keys):
    """Per unit, the rolling 30-day PET (mm / 30 days) averaged for each day of the year over the whole run, computed
    as the page does (from the same 0.1 mm series), so a page holding only a few years still measures its anomalies
    against the full-run normal. Returned in the order of ``sorted(set(keys))``."""
    out = {}
    for n in names:
        a = sub[f"{n}_PET"].round(1).to_numpy(float)
        c = np.cumsum(a)
        s = c - np.concatenate([np.zeros(ROLL_EVAP), c[:-ROLL_EVAP]])
        r = s * ROLL_EVAP / np.minimum(np.arange(1, len(a) + 1), ROLL_EVAP)
        out[n] = pd.Series(r).groupby(keys).mean().round(2).tolist()
    return out


def _payloads(units, geo, climate, results, regions, rivers, river_flow, dem, terrain_step, window, demo, fringe):
    """The page's data files for one time window (a slice of the run's days): geometry, the shared evaporation index,
    and per river system its climate series and flow results.

    ``demo`` makes the small bundle the page opens on: it adds the full-run evaporation normals and draws only each
    basin's main channel, and per river system a detail file (1 km terrain cells, its other rivers and their flows)
    that the page fetches when it zooms in on that system."""
    first = next(iter(geo))
    all_days = climate[first][1].index
    days = all_days[window]
    reaches, context = _rivers(rivers, river_flow.mean(), dem)
    shown = {r["unit"] for r in reaches if r["kind"] == "channel" or not demo}
    mids = {r.subcatchment: (r.geometry.centroid if r.geometry.contains(r.geometry.centroid) else r.geometry.representative_point()) for r in regions.itertuples()}
    terrain, stats = _terrain(regions, dem, terrain_step)
    lo, hi = days[0].strftime("%Y-%m-%d"), days[-1].strftime("%Y-%m-%d")
    grids = {}
    for u in geo:  # keep only the stored evaporation fields inside the window
        g = climate[u][3]
        steps = [i for i, d in enumerate(g["dates"]) if lo <= d <= hi]
        grids[u] = {**g, "dates": [g["dates"][i] for i in steps], "values": np.ascontiguousarray(g["values"][steps])}
    evap_index, evap_values = _evap(grids)
    years = range(int(days[0].year + (days[0].month >= 7)), int(days[-1].year + (days[-1].month >= 7)) + 1)  # water years touched
    wy = lambda df: None if df is None else df[df.index.isin(years)]
    names = {u: SDL_UNITS[u]["name"] for u in geo}
    common = {"days": days.strftime("%Y-%m-%d").tolist(), "evap": evap_index}
    if demo:
        common["normalKeys"] = sorted(set(all_days.strftime("%m-%d")))
    files = {"geometry.json": {
        "units": [{"id": r.subcatchment, "sdl": r.sdl_unit, "name": r.region_name, "area": round(r.area_km2),
                   "mid": [round(mids[r.subcatchment].x, 4), round(mids[r.subcatchment].y, 4), int(dem.at(mids[r.subcatchment].x, mids[r.subcatchment].y))],
                   "rings": _rings(r.geometry.simplify(0.004), dem), "elev": stats[i]} for i, r in enumerate(regions.itertuples())],
        "terrain": terrain,
        "outline": _rings(regions.geometry.union_all().simplify(0.003), dem),
        "outlineBuffer": _rings(fringe.simplify(0.003), dem),  # the SDL outlines grown by OUTLINE_BUFFER_KM: rivers are kept within it
        "sdlBounds": [{"id": u, "name": names[u], "fullName": geo[u]["outline"]["sdl_name"].iloc[0], "system": s,
                       "mid": _label_point(geo[u]["outline"].geometry.iloc[0], dem),
                       "rings": _rings(geo[u]["outline"].geometry.iloc[0].simplify(0.003), dem)} for s, us in units.items() for u in us],
        "reaches": [r for r in reaches if r["unit"] in shown],
        "context": context,
    }, "climate.json": common}
    for s, us in units.items():
        full_sub = pd.concat([climate[u][1] for u in us], axis=1)
        sub = full_sub.iloc[window]
        ids = list(regions.loc[regions["sdl_unit"].isin(us), "subcatchment"])
        files[f"climate_{s}.json"] = {
            "P": {n: sub[f"{n}_P"].round(1).tolist() for n in ids},
            "PET": {n: sub[f"{n}_PET"].round(1).tolist() for n in ids},
            "evapParts": {u: evap_values[u] for u in us},
            **({"petNormal": _evap_normals(full_sub, ids, all_days.strftime("%m-%d"))} if demo else {}),
        }
        files[f"flow_{s}.json"] = {
            "reachFlow": {n: v.iloc[window].round(0).astype(int).tolist() for u in us for n, v in results[u][1].items()},
            "riverFlow": {n: base64.b64encode(np.clip(v.iloc[window].round(0).to_numpy(), 0, 65535).astype("<u2").tobytes()).decode()
                          for u in us for n, v in results[u][2].items() if n in shown},
            "sdl": {u: {"flow": results[u][0].iloc[window].round(0).astype(int).tolist(), "fish": _table(wy(results[u][3])),
                        "birds": _birds(wy(results[u][4])), "gum": _table(wy(results[u][5]))} for u in us},
        }
    if demo:
        fine, _ = _terrain(regions, dem, GRID_STEP)  # on the same origin as the demo terrain, every second node shared
        system_of = [SDL_UNITS[u]["system"] for u in regions["sdl_unit"]]
        for s in units:
            keep = [i for i, o in enumerate(fine["unit"]) if o >= 0 and system_of[o] == s]
            rest = [r for r in reaches if r["unit"] not in shown and SDL_UNITS[r["unit"].split("-R")[0]]["system"] == s]
            files[f"detail_{s}.json"] = {
                "terrain": {k: [fine[k][i] for i in keep] for k in ("col", "row", "elev", "unit")},
                "reaches": rest,
                "riverFlow": {r["unit"]: base64.b64encode(np.clip(river_flow[r["unit"]].iloc[window].round(0).to_numpy(), 0, 65535).astype("<u2").tobytes()).decode()
                              for r in rest},
            }
    return files


def _run_files(run, methods, units, geo, regions, rivers, dem, fringe, prefix=""):
    """Write one climate run's data files under DATA_DIR / prefix and return (their paths under DATA_DIR, the page
    metadata pointing at them), or None if a unit has no stored results for the run. With a prefix (another climate
    case), the run shares the default run's geometry files instead of writing its own."""
    climate = {u: load_climate(u, run) for u in geo}
    results = {u: load_results(u, run, methods) for u in geo}
    if any(climate[u] is None or results[u] is None for u in geo):
        return None
    river_flow = pd.concat([results[u][2] for u in geo], axis=1)
    all_days = climate[next(iter(geo))][1].index
    shown = np.flatnonzero((all_days.year >= DEMO_YEARS[0]) & (all_days.year <= DEMO_YEARS[1]))
    demo = slice(max(0, shown[0] - LEAD_DAYS), shown[-1] + 1)  # a lead-in so the rolling windows are full on the first shown day
    files = {f"{prefix}demo/{k}": v for k, v in _payloads(units, geo, climate, results, regions, rivers, river_flow, dem, DEMO_GRID_STEP, demo, True, fringe).items()}
    files.update({f"{prefix}full/{k}": v for k, v in _payloads(units, geo, climate, results, regions, rivers, river_flow, dem, GRID_STEP, slice(None), False, fringe).items()})
    engines, areas = {}, {}
    for s, us in units.items():
        basins = pd.concat([geo[u]["basins"] for u in us], ignore_index=True)
        engines[s] = f"engine_{s}_{'_'.join(run)}.json"
        nodes = connected(build_nodes(basins, s), basins)
        if not prefix:  # the node areas do not depend on the climate run
            areas[s] = f"areas_{s}.json"
            files[areas[s]] = _areas(nodes, basins)
        files[engines[s]] = _engine(s, basins, pd.concat([climate[u][2] for u in us], axis=1), regions[regions["sdl_unit"].isin(us)],
                                    rivers[rivers["sdl_unit"].isin(us)], nodes)
    if prefix:
        for k in ("demo", "full"):
            del files[f"{prefix}{k}/geometry.json"]
    for name, payload in files.items():  # written as they are made, so only one run's payloads are held at a time
        (DATA_DIR / name).parent.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / name).write_text(compact_floats(json.dumps(payload, separators=(",", ":"), allow_nan=False)))
    shared = lambda k: [f"data/{k}/geometry.json"] if prefix else []
    meta = {
        "climate": {"globalModel": run[0], "scenario": run[1], "regionalConfig": run[2],
                    "period": f"{all_days[0].year}–{all_days[-1].year}", "source": "NARCliM2.0", "resolution": "4 km", "frequency": "Daily"},
        "run": "_".join(run),
        "years": [int(all_days[0].year), int(all_days[-1].year)],
        # full-run peak flow, so the demo bundle colours its rivers on the same scale as the full series
        "maxQ": round(float(max(max(results[u][0].max(), results[u][1].max().max()) for u in geo))),
        "engines": {s: f"data/{f}" for s, f in engines.items()},  # fetched only when a non-default method is chosen
        **({"areas": {s: f"data/{f}" for s, f in areas.items()}} if areas else {}),  # the runoff editor's node areas, fetched when it opens
        "engineHash": hashlib.sha1(b"".join((DATA_DIR / f).read_bytes() for f in engines.values())).hexdigest()[:10],  # saved results are keyed by it
        "demoFiles": shared("demo") + [f"data/{n}" for n in files if n.startswith(f"{prefix}demo/") and not n.startswith(f"{prefix}demo/detail_")],
        "details": {s: f"data/{prefix}demo/detail_{s}.json" for s in units},  # fetched when the demo page zooms in on a system
        "files": shared("full") + [f"data/{n}" for n in files if n.startswith(f"{prefix}full/")],
    }
    return list(files), meta


def run_display(run=DEFAULT_RUN, methods=(RAINFALL_RUNOFF_MODEL, ROUTING_MODEL)):
    """Write the interactive 'river pulse' page for every SDL unit of DISPLAY_SYSTEMS, from their stored geometry,
    climate and results for one run and method pair.

    The page opens on a small demo bundle (docs/data/demo/): DEMO_YEARS only, 2 km terrain and full-run evaporation
    normals. Choosing other years or methods reloads it on the full series (docs/data/full/, 1 km terrain), and the
    browser engine's forcing (docs/data/engine_*.json) is fetched only to recalculate other methods. Every other climate
    case (CLIMATE_CASES) stored for all units gets its own files in docs/data/<case id>/, and the page's Climate model
    panel reloads on them (?case=<id>); cases not stored are listed as not built.
    """
    units = {s: SYSTEMS[s]["units"] for s in DISPLAY_SYSTEMS}
    geo = {u: {n: load_geometry(u, n) for n in ("outline", "subcatchments", "basins", "rivers")} for us in units.values() for u in us}
    missing = [u for u in geo if geo[u]["subcatchments"] is None]
    if missing:
        raise RuntimeError(f"no stored geometry for {', '.join(missing)}: run python main.py first")

    regions = pd.concat([geo[u]["subcatchments"] for u in geo], ignore_index=True)
    regions = gpd.GeoDataFrame(regions, crs=geo[next(iter(geo))]["subcatchments"].crs)
    regions["geometry"] = regions.geometry.make_valid()  # the stored GeoJSON can carry tiny self-touches that break the union
    rivers = gpd.GeoDataFrame(pd.concat([geo[u]["rivers"] for u in geo], ignore_index=True), crs=regions.crs)
    rivers = _drop_duplicate_borders(rivers)
    fringe = buffer_outline(shapely.union_all([geo[u]["outline"].geometry.union_all() for u in geo]))  # SDL outlines + OUTLINE_BUFFER_KM
    bx = np.array(fringe.bounds).reshape(2, 2)
    dem = Dem(np.concatenate([np.minimum(regions.total_bounds[:2], bx[0]), np.maximum(regions.total_bounds[2:], bx[1])]))
    built = _run_files(run, methods, units, geo, regions, rivers, dem, fringe)
    if built is None:
        raise RuntimeError(f"no stored {'/'.join(run)} results for every unit: run python main.py first")
    files, run_meta = built
    cases = {}
    for c in CLIMATE_CASES:
        if tuple(c["run"]) == tuple(run):
            continue
        other = _run_files(tuple(c["run"]), methods, units, geo, regions, rivers, dem, fringe, prefix=f"{c['id']}/")
        if other is None:
            print(f"6_display: {c['label']} ({'/'.join(c['run'])}) is not stored for every unit, listed as not built")
            continue
        files += other[0]
        cases[c["id"]] = other[1]
    gauges, gauge_flows = {}, {}  # per built case, and the observed flow: the EWR tool's results at the gauges on the modelled rivers (5_outputs/gauge_ewr.py export)
    for c in [*CLIMATE_CASES, {"id": "observed", "run": ()}]:
        source = HERE.parent / "data" / "gauge_ewr" / f"{c['id']}.json"
        if (tuple(c["run"]) == tuple(run) or c["id"] in cases or c["id"] == "observed") and source.exists():
            (DATA_DIR / f"gauges_{c['id']}.json").write_text(source.read_text())
            files.append(f"gauges_{c['id']}.json")
            gauges[c["id"]] = f"data/gauges_{c['id']}.json"
            (DATA_DIR / f"gauges_flow_{c['id']}.json").write_text((HERE.parent / "data" / "gauge_ewr" / f"{c['id']}_flow.json").read_text())
            files.append(f"gauges_flow_{c['id']}.json")
            gauge_flows[c["id"]] = f"data/gauges_flow_{c['id']}.json"
    # "Your data": the page runs py_ewr on an uploaded file (Pyodide), exporting with the same code as above, so it needs that code and where the EWR gauges are
    ewr_gauges = pd.read_csv(HERE.parent / "data" / "input" / "routing" / "ewr_gauges.csv", dtype={"gauge": str}).set_index("gauge")
    (DATA_DIR / "ewr_gauges.json").write_text(json.dumps({g: {"name": r["name"], "lon": round(r["lon"], 4), "lat": round(r["lat"], 4)} for g, r in ewr_gauges.iterrows()}, separators=(",", ":")))
    files.append("ewr_gauges.json")
    (HERE.parent / "docs" / "ewr").mkdir(exist_ok=True)
    for name in ("ewr_export.py", "flow_regime_mappings.py"):
        (HERE.parent / "docs" / "ewr" / name).write_text((HERE.parent / "5_outputs" / name).read_text())
    roads = json.loads((HERE / "roads.json").read_text())  # fetched only when the Roads switch is turned on
    (DATA_DIR / "roads.json").write_text(compact_floats(json.dumps(roads, separators=(",", ":"), allow_nan=False)))
    files.append("roads.json")
    for old in DATA_DIR.rglob("*.json"):  # keep only the build's own files; unchanged content is rewritten byte-for-byte
        if old.relative_to(DATA_DIR).as_posix() not in files:
            old.unlink()
    for d in sorted((d for d in DATA_DIR.rglob("*") if d.is_dir()), reverse=True):  # deepest first
        if not any(d.iterdir()):
            d.rmdir()
    names = [SDL_UNITS[u]["name"] for u in geo]
    title = ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]
    meta = {
        "title": title,
        "focus": next(iter(geo)),  # the unit whose outlet flow and ecology the page shows first
        **run_meta,
        "cases": [{"id": c["id"], "label": c["label"], "globalModel": c["run"][0], "scenario": c["run"][1], "regionalConfig": c["run"][2],
                   "run": "_".join(c["run"]), "built": tuple(c["run"]) == tuple(run) or c["id"] in cases} for c in CLIMATE_CASES],
        "defaultCase": next((c["id"] for c in CLIMATE_CASES if tuple(c["run"]) == tuple(run)), None),
        "gauges": gauges,  # fetched when the Gauges switch is turned on or the car drives
        "gaugeFlows": gauge_flows,  # each case's daily flow at the gauges, fetched for the panel's flow charts
        "caseData": cases,  # per built case other than the default: its own run metadata, swapped in by ?case=<id>
        "runoff": {"selected": methods[0], "specs": runoff_specs()},
        "routing": {"selected": methods[1], "specs": routing_specs()},
        "demoYears": list(DEMO_YEARS),
        "detailStep": GRID_STEP,
    }
    DISPLAY_FILE.parent.mkdir(parents=True, exist_ok=True)
    html = TEMPLATE.read_text().replace("__TITLE__", title).replace("__META__", json.dumps(meta, separators=(",", ":"))).replace("__STORAGES__", (HERE / "storages.json").read_text())
    DISPLAY_FILE.write_text(html.replace("../../6_display/car/", "car/"))
    publish_assets()
    size = lambda prefix: sum((DATA_DIR / n).stat().st_size for n in files if n.startswith(prefix)) / 1e6
    extra = "".join(f", {c} case {size(c + '/'):.1f} MB" for c in cases)
    print(f"Wrote river pulse page ({DISPLAY_FILE.stat().st_size / 1e6:.2f} MB) for {title}: demo data {size('demo/'):.1f} MB, "
          f"full data {size('full/'):.1f} MB{extra}, engines {size('engine_'):.1f} MB, roads {size('roads'):.1f} MB: {DISPLAY_FILE}")


if __name__ == "__main__":
    run_display()
