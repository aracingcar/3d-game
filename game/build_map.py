"""Build the 3D map's data in docs/game/data/ for the region drawn on the map (the SDL units of DISPLAY_SYSTEMS).

    python game/build_map.py

Writes:
    heights.bin   int16 little-endian elevation (m), GRID_W x rows, row 0 north, lon/lat evenly spaced (equirectangular)
    texture.jpg   ground colour (land cover tint from elevation, slope and dryness, rivers, region outline), same extent
    meta.json     extent, grid size and labels (towns, storages, rivers)

Inputs: AWS Terrarium tiles (cached in data/input/dem, see 6_display/terrain.py), the MDBA SDL unit outlines and the OSM
waterways (downloads/download_sdl_units.py, downloads/download_osm_waterways.py).
"""
import importlib.util
import json
import math
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "game" / "data"
sys.path.insert(0, str(ROOT / "6_display"))
from terrain import Dem, hillshade  # noqa: E402

GRID_W = 1024  # elevation columns (~0.9 km cells over the region)
TEX_W = 4096  # texture columns (~220 m pixels); 4096 is the safe WebGL texture limit
MARGIN_DEG = 0.3  # terrain shown around the region for context
SEA_FLOOR_M = -60  # sea bathymetry is clamped to this, just below the water plane

# Rivers drawn wider and labelled on the map.
MAJOR_RIVERS = ("Murray River", "Murrumbidgee River", "Lachlan River", "Darling River", "Goulburn River", "Loddon River",
                "Wimmera River", "Broken River", "Ovens River", "Kiewa River", "Campaspe River", "Avoca River",
                "Edward River", "Wakool River", "Tumut River", "Mitta Mitta River", "Anabranch of the Darling River")

TOWNS = {
    "Canberra": (149.13, -35.28), "Wagga Wagga": (147.37, -35.12), "Albury": (146.92, -36.08),
    "Wodonga": (146.89, -36.12), "Griffith": (146.04, -34.29), "Leeton": (146.40, -34.55), "Hay": (144.85, -34.51),
    "Balranald": (143.56, -34.64), "Mildura": (142.16, -34.19), "Wentworth": (141.91, -34.11),
    "Broken Hill": (141.47, -31.95), "Menindee": (142.42, -32.39), "Swan Hill": (143.55, -35.34),
    "Echuca": (144.75, -36.13), "Shepparton": (145.40, -36.38), "Bendigo": (144.28, -36.76),
    "Horsham": (142.20, -36.71), "Wangaratta": (146.31, -36.36), "Benalla": (145.98, -36.55),
    "Deniliquin": (144.96, -35.53), "Forbes": (148.01, -33.38), "Cowra": (148.69, -33.83), "Parkes": (148.18, -33.14),
    "Orange": (149.10, -33.28), "Hillston": (145.53, -33.48), "Condobolin": (147.15, -33.09), "Cooma": (149.13, -36.24),
    "Tumut": (148.22, -35.30), "Gundagai": (148.10, -35.07), "Narrandera": (146.55, -34.75), "Kerang": (143.92, -35.73),
    "Seymour": (145.14, -37.03), "Bright": (146.96, -36.73), "Corowa": (146.39, -35.99), "Ivanhoe": (144.30, -32.90),
}
PEAKS = {"Mt Kosciuszko": (148.263, -36.456), "Mt Bogong": (147.305, -36.736), "Mt Buller": (146.437, -37.146),
         "Grampians": (142.48, -37.15)}


def load_config():
    spec = importlib.util.spec_from_file_location("config", ROOT / "1_masking" / "config.py")
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    return config


def region_outline(config):
    """Union of the SDL units of the displayed systems, in lon/lat."""
    units = [u for s in config.DISPLAY_SYSTEMS for u in config.SYSTEMS[s]["units"]]
    sdl = gpd.read_file(config.SDL_FILE).to_crs("EPSG:4326")
    sdl = sdl[sdl["SWSDLID"].isin(units)]
    missing = set(units) - set(sdl["SWSDLID"])
    if missing:
        raise ValueError(f"SDL units missing from {config.SDL_FILE}: {sorted(missing)}")
    return unary_union(sdl.geometry.buffer(0)), units


def polygons(geom):
    return list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]


def land_colour(elev, slope_deg, lon, rng):
    """Ground colour (0-255 RGB) from elevation, slope and a west-to-east dryness gradient: red-brown mallee and
    saltbush plains in the west, straw-coloured cropping and grazing country in the middle, eucalypt forest on the
    ranges and grey alpine ground on the high country. A visual approximation, not a land cover map."""
    wet = np.clip((lon - 142.0) / 6.0, 0, 1) * 0.65 + np.clip((elev - 150) / 700, 0, 1) * 0.35
    patch = gaussian_filter(rng.standard_normal(elev.shape), 6)
    patch = patch / (np.abs(patch).max() + 1e-9)
    wet = np.clip(wet + 0.12 * patch, 0, 1)[..., None]
    arid = np.array([186, 140, 96])
    pasture = np.array([176, 166, 112])
    green = np.array([128, 140, 84])
    forest = np.array([66, 88, 52])
    alpine = np.array([142, 146, 128])
    base = np.where(wet < 0.5, arid + (pasture - arid) * (wet / 0.5), pasture + (green - pasture) * ((wet - 0.5) / 0.5))
    treed = (np.clip((slope_deg - 2.0) / 6.0, 0, 1) * np.clip((elev - 250) / 350, 0, 1))[..., None]
    base = base + (forest - base) * treed
    high = np.clip((elev - 1500) / 400, 0, 1)[..., None]
    base = base + (alpine - base) * high
    return base


def main():
    config = load_config()
    region, units = region_outline(config)
    minx, miny, maxx, maxy = region.bounds
    west, south, east, north = minx - MARGIN_DEG, miny - MARGIN_DEG, maxx + MARGIN_DEG, maxy + MARGIN_DEG
    lat_c = (north + south) / 2
    width_km = (east - west) * 111.32 * math.cos(math.radians(lat_c))
    height_km = (north - south) * 110.57
    grid_h = round(GRID_W * height_km / width_km)
    tex_h = round(TEX_W * height_km / width_km)
    print(f"region {units}: {west:.2f}..{east:.2f} E, {south:.2f}..{north:.2f} S, {width_km:.0f} x {height_km:.0f} km")

    dem = Dem((west, south, east, north))

    def sample(cols, rows):
        lon = np.linspace(west, east, cols)
        lat = np.linspace(north, south, rows)
        lon2, lat2 = np.meshgrid(lon, lat)
        return lon2, dem.at(lon2, lat2)

    _, z = sample(GRID_W, grid_h)
    if not np.isfinite(z).all():
        raise ValueError("non-finite elevation in the DEM mosaic")
    z = np.maximum(z, SEA_FLOOR_M)  # the south-east corner reaches the Tasman Sea; the viewer draws a water plane at 0 m
    OUT.mkdir(parents=True, exist_ok=True)
    np.clip(np.round(z), -32768, 32767).astype("<i2").tofile(OUT / "heights.bin")

    lon_t, zt = sample(TEX_W, tex_h)
    step = (east - west) / (TEX_W - 1)
    dx = step * 111320 * math.cos(math.radians(lat_c))
    gy, gx = np.gradient(zt, step * 110574, dx)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    shade = hillshade(zt, step, lat_c)
    rgb = land_colour(zt, slope, lon_t, np.random.default_rng(7))
    rgb *= (0.78 + 0.4 * shade)[..., None]  # fine relief below the mesh resolution; the 3D lighting does the rest
    rgb[zt <= 0] = (52, 84, 110)  # sea (Port Phillip edge, if in view)

    def px(coords):
        return [((x - west) / (east - west) * (TEX_W - 1), (north - y) / (north - south) * (tex_h - 1)) for x, y in coords]

    # Outside the region: faded and greyed so the playable area stands out.
    mask = Image.new("L", (TEX_W, tex_h), 0)
    draw = ImageDraw.Draw(mask)
    for poly in polygons(region.simplify(0.002)):
        draw.polygon(px(poly.exterior.coords), fill=255)
        for hole in poly.interiors:
            draw.polygon(px(hole.coords), fill=0)
    inside = (np.asarray(mask) > 0)[..., None]
    grey = rgb.mean(axis=2, keepdims=True)
    rgb = np.where(inside, rgb, (rgb * 0.45 + grey * 0.55) * 0.72)

    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(img)
    rivers = {}
    for path in sorted((ROOT / "data" / "input" / "routing").glob("osm_*_waterways.geojson")):
        ways = gpd.read_file(path)
        ways = ways[ways["waterway"] == "river"]
        for name, geom in zip(ways["name"], ways.geometry):
            lines = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
            major = name in MAJOR_RIVERS
            for line in lines:
                draw.line(px(line.coords), fill=(58, 104, 128) if major else (78, 116, 128), width=4 if major else 2)
                if major:
                    rivers.setdefault(name, []).append(line)
    for poly in polygons(region.simplify(0.002)):
        draw.line(px(poly.exterior.coords), fill=(236, 226, 196), width=3)
    img.save(OUT / "texture.jpg", quality=88)

    def within(lon, lat):
        return west <= lon <= east and south <= lat <= north

    labels = [{"kind": "town", "name": n, "lon": x, "lat": y} for n, (x, y) in TOWNS.items() if within(x, y)]
    labels += [{"kind": "peak", "name": n, "lon": x, "lat": y} for n, (x, y) in PEAKS.items() if within(x, y)]
    for s in config.DISPLAY_SYSTEMS:
        for name, st in config.SYSTEMS[s].get("storages", {}).items():
            labels.append({"kind": "storage", "name": name, "lon": st["lon"], "lat": st["lat"]})
    for name, lines in rivers.items():
        longest = max(lines, key=lambda l: l.length)
        p = longest.interpolate(0.5, normalized=True)
        labels.append({"kind": "river", "name": name, "lon": round(p.x, 4), "lat": round(p.y, 4)})

    meta = {
        "west": west, "east": east, "south": south, "north": north,
        "width_km": width_km, "height_km": height_km, "grid_w": GRID_W, "grid_h": grid_h,
        "elev_min": int(z.min()), "elev_max": int(z.max()), "units": units,
        "outline": [[[round(x, 3), round(y, 3)] for x, y in poly.exterior.coords] for poly in polygons(region.simplify(0.01))],
        "labels": labels,
    }
    (OUT / "meta.json").write_text(json.dumps(meta))
    print(f"wrote {OUT}: grid {GRID_W}x{grid_h}, texture {TEX_W}x{tex_h}, elevation {meta['elev_min']}..{meta['elev_max']} m")


if __name__ == "__main__":
    main()
