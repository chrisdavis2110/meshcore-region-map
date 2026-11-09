#!/usr/bin/env python3
"""
Build Leaflet-ready MeshCore region GeoJSON from meshcore-settings places.

Top-level places become the default map layers. Nested places that claim county
outlines are also generated, but hidden by default.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
TOOLS = Path(__file__).resolve().parent
OUT = ROOT / "public" / "regions"
COUNTY_INPUT = TOOLS / "census_california_counties.geojson"
STATE_INPUT = TOOLS / "census_california_state.geojson"
WESTERN_STATES_INPUT = TOOLS / "census_western_states.geojson"
SOURCE = "U.S. Census Bureau 2024 cartographic boundary files"
SETTINGS_SOURCE = "meshcore-settings California region tree"
DRAFT_DIR = ROOT / "data" / "socal-draft"
# Continental states west of the Rocky Mountains (Pacific + Intermountain).
WESTERN_STATE_CODES = ("WA", "OR", "CA", "NV", "AZ", "ID", "UT")
# Root tokens emitted as map layers. `us` stays a chain prefix only.
MAP_ROOT_CODES = frozenset({"west", "california"})

LEVEL_TYPES = {
    "region": "Region",
    "area": "Area",
    "local area": "Local Area",
}

# meshcore-settings leaves some counties only on local areas or nested outlines
# that would otherwise overlap a sibling. These extras are map-only.
OUTLINE_EXTRAS = {}

OUTLINE_REMOVALS = {}

# Keep map ids identical to settings codes so the homepage tree and map match.
ID_OVERRIDES = {}

# Counties that a top-level region should own even when another region's
# outline or nested tree would claim them. These extras win first.
TOP_LEVEL_EXTRAS = {}


def adjusted_outline(code: str, names: list[str]) -> list[str]:
    outline = list(dict.fromkeys(names + OUTLINE_EXTRAS.get(code, [])))
    skip = set(OUTLINE_REMOVALS.get(code, []))
    return [name for name in outline if name not in skip]


def as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def regions_json_path(explicit: Path | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(explicit)
    candidates.extend(
        [
            ROOT / "data" / "regions.json",
            ROOT.parent / "meshcore-settings" / "data" / "regions.json",
        ]
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "Could not find regions.json. Pass --regions or keep a copy in data/regions.json."
    )


def load_tree(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("places"), list):
        raise ValueError(f"{path} must contain a places array")
    return data


def level_name(tree: dict, depth: int, place: dict) -> str:
    if place.get("kind"):
        return str(place["kind"])
    levels = tree.get("levels") or []
    if depth < len(levels) and isinstance(levels[depth], dict):
        return str(levels[depth].get("name") or "place")
    return "place"


def region_type_for(kind: str) -> str:
    return LEVEL_TYPES.get(kind, kind.replace("_", " ").title() or "Place")


def flatten_places(tree: dict) -> list[dict]:
    places = []

    def walk(place: dict, ancestors: list[dict], depth: int) -> None:
        children = place.get("children") or []
        source_code = place["code"]
        code = ID_OVERRIDES.get(source_code, source_code)
        node = {
            "id": code,
            "name": place["name"],
            "short_name": place.get("short") or str(code).upper(),
            "blurb": place.get("blurb") or "",
            "outline": adjusted_outline(source_code, as_list(place.get("outline"))),
            "county": as_list(place.get("county")),
            "lat": place.get("lat"),
            "lon": place.get("lon"),
            "kind": level_name(tree, depth, place),
            "depth": depth,
            "ancestors": ancestors,
            "children": children,
        }
        places.append(node)
        parent = {
            "id": node["id"],
            "name": node["name"],
            "short_name": node["short_name"],
        }
        for child in children:
            walk(child, ancestors + [parent], depth + 1)

    for place in tree["places"]:
        walk(place, [], 0)
    return places


def counties_for(place: dict, top_level_counties: dict[str, list[str]] | None = None) -> list[str]:
    if place["depth"] == 0 and top_level_counties is not None:
        return list(top_level_counties.get(place["id"], []))
    if place["outline"]:
        return list(place["outline"])
    # Areas/counties may name counties without an outline (Lake Tahoe).
    # Local areas with lat/lon stay points instead of filling the parent county.
    if place["county"] and place["kind"] != "local area":
        return list(place["county"])
    return []


def top_level_id(place: dict) -> str | None:
    if place["depth"] == 0:
        return place["id"]
    if place["ancestors"]:
        return place["ancestors"][0]["id"]
    return None


def assign_top_level_counties(places: list[dict]) -> dict[str, list[str]]:
    """Give each county to exactly one top-level region.

    Explicit parent outlines win, so nested places like Grass Valley (Nevada
    County) and Gold Country (Sierra County) cannot pull those counties out of
    North California. Unclaimed descendant outlines then fill regions with no
    parent outline, such as Bay Area, Central Valley, and SoCal.
    """
    top = [place for place in places if place["depth"] == 0]
    descendants = [place for place in places if place["depth"] > 0]
    claimed: dict[str, str] = {}
    assigned: dict[str, list[str]] = {place["id"]: [] for place in top}

    def claim(region_id: str, names: list[str]) -> None:
        for name in names:
            if name in claimed:
                continue
            claimed[name] = region_id
            assigned[region_id].append(name)

    for place in top:
        claim(place["id"], TOP_LEVEL_EXTRAS.get(place["id"], []))
    for place in top:
        claim(place["id"], place["outline"])
    for place in top:
        claim(
            place["id"],
            [
                name
                for child in descendants
                if top_level_id(child) == place["id"]
                for name in child["outline"]
            ],
        )
    for place in top:
        claim(
            place["id"],
            [
                name
                for child in descendants
                if top_level_id(child) == place["id"]
                for name in child["county"]
            ],
        )
    return assigned


def chain_for(place: dict, tree: dict) -> str:
    root = [item["code"] for item in tree.get("root") or []]
    ancestors = [item["id"] for item in place["ancestors"]]
    return " ".join(root + ancestors + [place["id"]])


def select_counties(counties: gpd.GeoDataFrame, names: list[str], region_id: str) -> gpd.GeoDataFrame:
    selected = counties[counties["NAME"].isin(names)][["geometry"]].copy()
    missing = set(names) - set(counties["NAME"])
    if missing:
        raise ValueError(f"{region_id} references missing California counties: {sorted(missing)}")
    if selected.empty:
        raise ValueError(f"{region_id} selected no county geometry")
    return selected


def dissolve(rows: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    geometry = rows.geometry.union_all()
    dissolved = gpd.GeoDataFrame(geometry=[geometry], crs=4326)
    dissolved["geometry"] = dissolved.geometry.make_valid()
    return dissolved


def write_geojson(gdf: gpd.GeoDataFrame, path: Path) -> None:
    gdf.to_file(path, driver="GeoJSON")


def polygon_record(place: dict, tree: dict, geometry: gpd.GeoDataFrame, county_names: list[str]) -> gpd.GeoDataFrame:
    region = geometry.copy()
    region["id"] = place["id"]
    region["name"] = place["name"]
    region["short_name"] = place["short_name"]
    region["kind"] = place["kind"]
    region["depth"] = place["depth"]
    region["region_type"] = region_type_for(place["kind"])
    region["boundary_basis"] = (
        "Non-overlapping California counties from meshcore-settings outlines"
        if place["depth"] == 0
        else "Counties named by meshcore-settings outline"
    )
    region["notes"] = place["blurb"]
    region["region_chain"] = chain_for(place, tree)
    region["counties"] = ", ".join(county_names)
    region["draft"] = False
    region["source"] = f"{SOURCE}; {SETTINGS_SOURCE}"
    region["coordinator"] = ""
    return region[
        [
            "id",
            "name",
            "short_name",
            "kind",
            "depth",
            "region_type",
            "boundary_basis",
            "notes",
            "region_chain",
            "counties",
            "draft",
            "source",
            "coordinator",
            "geometry",
        ]
    ]


def point_feature_collection(place: dict, tree: dict) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "id": place["id"],
                    "name": place["name"],
                    "short_name": place["short_name"],
                    "kind": place["kind"],
                    "depth": place["depth"],
                    "region_type": region_type_for(place["kind"]),
                    "boundary_basis": "Representative point from meshcore-settings",
                    "notes": place["blurb"],
                    "region_chain": chain_for(place, tree),
                    "counties": ", ".join(place["county"]),
                    "draft": False,
                    "source": SETTINGS_SOURCE,
                    "coordinator": "",
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(place["lon"]), float(place["lat"])],
                },
            }
        ],
    }


def root_scope_record(
    geometry: gpd.GeoDataFrame, item: dict, chain: list[str]
) -> gpd.GeoDataFrame:
    code = item["code"]
    name = item.get("name") or code
    region = dissolve(geometry[["geometry"]])
    region["id"] = code
    region["name"] = name
    region["short_name"] = code.upper().replace("-", "")
    if code == "california":
        region["kind"] = "state_region"
        region["region_type"] = "State Region"
        region["notes"] = "Statewide umbrella for the meshcore-settings California tree."
        region["boundary_basis"] = (
            "Existing political boundary represented by a U.S. Census state boundary"
        )
    else:
        region["kind"] = "root"
        region["region_type"] = "Root Scope"
        region["notes"] = (
            "Root scope from meshcore-settings. Outline of Washington, Oregon, "
            "California, Nevada, Arizona, Idaho, and Utah — states west of the "
            "Rocky Mountains."
        )
        region["boundary_basis"] = (
            "U.S. Census state boundaries for states west of the Rocky Mountains"
        )
    region["region_chain"] = " ".join(chain) if chain else code
    region["counties"] = ""
    region["draft"] = False
    region["source"] = SOURCE
    region["coordinator"] = ""
    return region


def index_entry(place: dict, *, visible: bool, optional: bool = False, legend: bool = True) -> dict:
    status = (
        "political_boundaries"
        if place.get("kind") in {"state_region", "root"} or place["id"] == "california"
        else "official_local"
    )
    entry = {
        "id": place["id"],
        "name": place["name"],
        "short_name": place["short_name"],
        "region_type": place.get("region_type") or region_type_for(place["kind"]),
        "coordination_status": status,
        "coordination_label": (
            "Political Boundaries" if status == "political_boundaries" else "Official Local Region"
        ),
        "file": f"{place['id']}.geojson",
    }
    if optional:
        entry["optional"] = True
    if not visible:
        entry["visible"] = False
    if not legend:
        entry["legend"] = False
    return entry


def load_socal_draft(entries: list[dict]) -> tuple[dict, dict, dict] | None:
    """Validate curated data before any generated outputs are replaced."""
    by_id = {entry["id"]: entry for entry in entries}
    region_ids = set(by_id)
    if "socal" not in region_ids:
        return None  # A custom, unrelated region tree must remain unchanged.
    if len(by_id) != len(entries):
        duplicates = sorted({entry["id"] for entry in entries if sum(e["id"] == entry["id"] for e in entries) > 1})
        raise ValueError(f"Duplicate generated region ids: {duplicates}; use --no-socal-draft")
    draft = json.loads((DRAFT_DIR / "manifest.json").read_text(encoding="utf-8"))
    draft["subregions"] = [{**draft.get("subregion_defaults", {}), **entry} for entry in draft["subregions"]]
    collection = json.loads((DRAFT_DIR / "geometries.geojson").read_text(encoding="utf-8"))
    required = {"socal", "centralcoast", "centralvalley", "sierranevada"}
    missing = required - region_ids
    if missing:
        raise ValueError(f"SoCal draft requires {sorted(missing)}; use --no-socal-draft for a different tree")

    # Validate the full set before touching either the index or generated files.
    # Legacy areas are required only when the source tree contains them.
    feature_ids = [feature["properties"]["id"] for feature in collection["features"]]
    seen = set()
    for region_id in feature_ids:
        if region_id in seen:
            raise ValueError(f"Duplicate SoCal draft geometry: {region_id}")
        seen.add(region_id)
    adjusted_legacy = {"slo", "cvsouth", "eastsierra"} & region_ids
    required_geometries = required | adjusted_legacy | {entry["id"] for entry in draft["subregions"]}
    missing = required_geometries - seen
    if missing:
        raise ValueError(f"Missing SoCal draft geometries: {sorted(missing)}")

    # Check collisions and all final targets before the builder deletes old files.
    for update in draft["updates"]:
        previous = by_id.get(update["id"])
        if previous:
            if (update["id"] not in seen and "file" in update
                    and update["file"] != previous.get("file")):
                raise ValueError(f"SoCal draft cannot change filename for non-curated region: {update['id']}")
            by_id[update["id"]] = {**previous, **update}
    proposed_ids = set()
    for proposal in draft["subregions"]:
        if proposal["id"] in proposed_ids:
            raise ValueError(f"Duplicate SoCal draft id: {proposal['id']}")
        proposed_ids.add(proposal["id"])
        previous = by_id.get(proposal["id"])
        if previous and previous.get("overlay_group") != "subregion":
            raise ValueError(f"SoCal draft id conflicts with an existing region: {proposal['id']}; use --no-socal-draft")
        by_id[proposal["id"]] = proposal
    # Reserve every generated filename, including those a draft update changes.
    # A curated feature may overwrite its own generated file, never another's.
    targets = {entry.get("file"): entry["id"] for entry in entries if entry.get("file")}
    for region_id in feature_ids:
        entry = by_id.get(region_id)
        if not entry:  # The source tree may not contain every legacy area.
            continue
        filename = entry["file"]
        if (not isinstance(filename, str) or not filename
                or Path(filename).name != filename or Path(filename).suffix.lower() != ".geojson"):
            raise ValueError(f"Invalid draft GeoJSON filename: {filename}")
        if filename in targets and targets[filename] != region_id:
            raise ValueError(f"Duplicate draft GeoJSON filename: {filename} ({targets[filename]}, {region_id})")
        targets[filename] = region_id
    if "socal-boundary-notes.geojson" in targets:
        raise ValueError("Duplicate draft GeoJSON filename: socal-boundary-notes.geojson")
    try:
        boundary_notes = json.loads((DRAFT_DIR / "boundary-notes.geojson").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("SoCal boundary notes are missing or invalid") from error
    if (not isinstance(boundary_notes, dict) or boundary_notes.get("type") != "FeatureCollection"
            or not isinstance(boundary_notes.get("features"), list)):
        raise ValueError("SoCal boundary notes are missing or invalid")
    features = boundary_notes["features"]
    def valid_boundary_note(feature: object) -> bool:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            return False
        properties, geometry = feature.get("properties"), feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict) or geometry.get("type") != "LineString":
            return False
        if any(not isinstance(properties.get(key), str) or not properties[key].strip() for key in ("id", "title", "description")):
            return False
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            return False
        for point in coordinates:
            if (not isinstance(point, list) or len(point) != 2
                    or any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
                           for value in point)
                    or not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90)):
                return False
        return len({tuple(point) for point in coordinates}) >= 2

    if (len(features) != 3 or not all(valid_boundary_note(feature) for feature in features)
            or {feature["properties"].get("id") for feature in features} != {"centralcoast", "centralvalley", "sierranevada"}):
        raise ValueError("SoCal boundary notes are missing or invalid")
    return draft, collection, boundary_notes


def validate_socal_compatibility(draft: dict, places: list[dict], assignments: dict[str, list[str]]) -> None:
    """Reject trees whose county outlines do not match the curated geometry's source."""
    baseline = draft["county_baseline"]
    current = {place["id"]: sorted(assignments[place["id"]]) for place in places if place["depth"] == 0}
    expected = {key: sorted(value) for key, value in baseline["top_level"].items()}
    mismatched = sorted(key for key in current.keys() | expected.keys() if current.get(key) != expected.get(key))
    if mismatched:
        raise ValueError(f"SoCal draft is incompatible with county assignments for {mismatched}; use --no-socal-draft")

    expected_legacy = baseline["adjusted_legacy"]
    changed_legacy = sorted(place["id"] for place in places
        if place["id"] in expected_legacy and sorted(place["outline"]) != sorted(expected_legacy[place["id"]]))
    if changed_legacy:
        raise ValueError(f"SoCal draft is incompatible with nested outlines for {changed_legacy}; use --no-socal-draft")


def apply_eastern_kern_ridgeline(output: Path) -> None:
    """Move eastern Kern (Ridgecrest / Edwards / Mojave) from Central Valley onto SoCal.

    County lines put all of Kern in Central Valley. The curated SoCal draft
    follows the Tehachapi / El Paso ridgeline instead; reuse that cut so the
    desert side of the ridge maps with SoCal.
    """
    from shapely.geometry import Polygon, box, mapping, shape
    from shapely.ops import unary_union

    draft_path = DRAFT_DIR / "geometries.geojson"
    if not draft_path.is_file():
        return
    needed = ("socal", "centralvalley", "kern")
    paths = {region_id: output / f"{region_id}.geojson" for region_id in needed}
    if not all(path.is_file() for path in paths.values()):
        return

    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    socal_draft = next(
        (shape(feature["geometry"]) for feature in draft["features"] if feature["properties"]["id"] == "socal"),
        None,
    )
    if socal_draft is None:
        return

    def load(region_id: str):
        path = paths[region_id]
        data = json.loads(path.read_text(encoding="utf-8"))
        return path, data, shape(data["features"][0]["geometry"])

    socal_path, socal_data, socal = load("socal")
    cv_path, cv_data, cv = load("centralvalley")
    kern_path, kern_data, kern = load("kern")

    pocket = kern.intersection(socal_draft).buffer(0)
    # Pull west through Red Rock Canyon / Inyokern so CA-14 stays inside SoCal
    # up to the East Sierra / Kern corner. Keep a straight western edge so the
    # map boundary does not zig-zag where the corridor meets the ridgeline cut.
    ca14_corridor = Polygon(
        [
            (-118.055, 35.28),
            (-117.85, 35.28),
            (-117.63, 35.62),
            (-117.63, 35.81),
            (-118.055, 35.81),
            (-118.055, 35.28),
        ]
    )
    ca14_pocket = kern.intersection(ca14_corridor).buffer(0)
    # Leftover Kern stub over China Lake NWC, south of East Sierra.
    china_lake = kern.intersection(box(-117.85, 35.60, -117.55, 35.81)).buffer(0)
    pocket = unary_union([g for g in (pocket, ca14_pocket, china_lake) if not g.is_empty]).buffer(0)

    socal = unary_union([socal, pocket]).buffer(0) if not pocket.is_empty else socal
    cv = cv.difference(pocket).buffer(0) if not pocket.is_empty else cv
    kern = kern.difference(pocket).buffer(0) if not pocket.is_empty else kern

    # Flatten only the Grapevine V (I-5) to a straight cut just above Frazier
    # Mountain Park Road. Keep the window between the V's natural cut-latitude
    # crossings — a wider box leaves vertical stubs on the clip edges.
    cut = 34.838
    west, east = -118.931, -118.831
    north_of_cut = box(west, cut, east, 35.05)
    south_of_cut = box(west, 34.70, east, cut)
    add = unary_union([cv, kern]).intersection(south_of_cut).difference(socal).buffer(0)
    remove = socal.intersection(north_of_cut).buffer(0)
    socal = unary_union([socal, add]).difference(remove).buffer(0)
    # Drop any interior rings left by the V/cut (they render as tiny yellow islands).
    if socal.geom_type == "Polygon":
        socal = Polygon(socal.exterior).buffer(0)
    elif socal.geom_type == "MultiPolygon":
        socal = unary_union([Polygon(part.exterior) for part in socal.geoms]).buffer(0)
    cv = cv.difference(socal).buffer(0)
    kern = kern.difference(socal).buffer(0)

    note = (
        "Map boundary follows the Tehachapi/El Paso ridgeline: eastern Kern "
        "(Ridgecrest, Edwards, Mojave, Inyokern / CA-14, China Lake NWC) is drawn with SoCal. "
        "Straight cut just above Frazier Mountain Park Road at the Grapevine."
    )

    def save(path: Path, data: dict, geometry) -> None:
        feature = data["features"][0]
        feature["geometry"] = mapping(geometry)
        props = feature["properties"]
        existing = props.get("notes") or ""
        if note not in existing:
            props["notes"] = f"{existing} {note}".strip()
        path.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")

    save(socal_path, socal_data, socal)
    save(cv_path, cv_data, cv)
    save(kern_path, kern_data, kern)


def apply_socal_draft(index: dict, output: Path, *, validated_draft: tuple[dict, dict, dict] | None = None) -> None:
    """Restore the curated draft after the county-based outputs are rebuilt."""
    entries = index["regions"]
    by_id = {entry["id"]: entry for entry in entries}
    data = validated_draft if validated_draft is not None else load_socal_draft(entries)
    if data is None:
        return
    draft, collection, boundary_notes = data

    index.update(draft.get("metadata", {}))
    for update in draft["updates"]:
        if update["id"] in by_id:
            by_id[update["id"]].update(update)
    for proposal in draft["subregions"]:
        previous = by_id.get(proposal["id"])
        if previous:
            previous.update(proposal)
        else:
            entries.append(proposal.copy())
            by_id[proposal["id"]] = entries[-1]
    for feature in collection["features"]:
        region_id = feature["properties"]["id"]
        entry = by_id.get(region_id)
        if not entry:  # The source tree may not contain every legacy area.
            continue
        filename = entry["file"]
        (output / filename).write_text(
            json.dumps({"type": "FeatureCollection", "features": [feature]}, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    (output / "socal-boundary-notes.geojson").write_text(
        json.dumps(boundary_notes, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regions", type=Path, help="Path to meshcore-settings regions.json")
    parser.add_argument("--no-socal-draft", action="store_true", help="Generate the original county-based boundaries without the SoCal draft")
    args = parser.parse_args()

    if not COUNTY_INPUT.exists() or not STATE_INPUT.exists():
        raise FileNotFoundError("Run build_census_boundaries.py first")

    regions_path = regions_json_path(args.regions)
    tree = load_tree(regions_path)
    places = flatten_places(tree)
    top_level_counties = assign_top_level_counties(places)
    polygon_places = []
    point_places = []
    for place in places:
        names = counties_for(place, top_level_counties)
        if names:
            polygon_places.append((place, names))
        elif place.get("lat") is not None and place.get("lon") is not None:
            point_places.append(place)
    root_items = [item for item in tree.get("root") or [] if item.get("code")]
    if not any(item["code"] == "california" for item in root_items):
        root_items = root_items + [{"code": "california", "name": "California"}]
    map_root_items = [item for item in root_items if item["code"] in MAP_ROOT_CODES]
    if not any(item["code"] == "west" for item in map_root_items):
        map_root_items = [{"code": "west", "name": "Western US"}, *map_root_items]
    if not any(item["code"] == "california" for item in map_root_items):
        map_root_items = [*map_root_items, {"code": "california", "name": "California"}]
    generated_entries = [
        {"id": item["code"], "file": f"{item['code']}.geojson"} for item in map_root_items
    ] + [
        {"id": place["id"], "file": f"{place['id']}.geojson"} for place, _ in polygon_places
    ] + [
        {"id": place["id"], "file": f"{place['id']}.geojson"} for place in point_places
    ]
    validated_draft = None if args.no_socal_draft else load_socal_draft(generated_entries)
    if validated_draft is not None:
        validate_socal_compatibility(validated_draft[0], places, top_level_counties)
    if not WESTERN_STATES_INPUT.exists():
        raise FileNotFoundError(
            f"Missing {WESTERN_STATES_INPUT.name}; run build_census_boundaries.py first"
        )
    counties = gpd.read_file(COUNTY_INPUT).to_crs(4326)
    state = gpd.read_file(STATE_INPUT).to_crs(4326)
    western_states = gpd.read_file(WESTERN_STATES_INPUT).to_crs(4326)
    if "STUSPS" in western_states.columns:
        western_states = western_states[western_states["STUSPS"].isin(WESTERN_STATE_CODES)]
        missing_west = sorted(set(WESTERN_STATE_CODES) - set(western_states["STUSPS"]))
        if missing_west:
            raise ValueError(f"Western states input is missing: {missing_west}")
    elif len(western_states) == 0:
        raise ValueError("Western states input is empty")

    census_county_names = set(counties["NAME"])
    assigned_names = [name for names in top_level_counties.values() for name in names]
    duplicates = sorted({name for name in assigned_names if assigned_names.count(name) > 1})
    if duplicates:
        raise ValueError(f"Top-level regions overlap: {duplicates}")
    missing = sorted(census_county_names - set(assigned_names))
    extra = sorted(set(assigned_names) - census_county_names)
    if missing or extra:
        raise ValueError(
            "Top-level county assignment does not match California: "
            + ", ".join(
                part
                for part in (
                    f"unassigned: {missing}" if missing else "",
                    f"unknown: {extra}" if extra else "",
                )
                if part
            )
        )

    OUT.mkdir(parents=True, exist_ok=True)
    for old_output in OUT.glob("*.geojson"):
        old_output.unlink()

    index = {
        "title": "California MeshCore Region Map",
        "source": tree.get("source") or "meshcore-settings",
        "updated": tree.get("updated"),
        "regions": [],
    }

    for item in map_root_items:
        # Keep full settings root prefixes in the chain even when `us` has no layer.
        chain_codes = [entry["code"] for entry in root_items]
        if item["code"] in chain_codes:
            chain = chain_codes[: chain_codes.index(item["code"]) + 1]
        else:
            chain = [item["code"]]
        geometry = western_states if item["code"] == "west" else state
        record = root_scope_record(geometry, item, chain)
        write_geojson(record, OUT / f"{item['code']}.geojson")
        kind = "state_region" if item["code"] == "california" else "root"
        region_type = "State Region" if item["code"] == "california" else "Root Scope"
        index["regions"].append(
            index_entry(
                {
                    "id": item["code"],
                    "name": item.get("name") or item["code"],
                    "short_name": item["code"].upper().replace("-", ""),
                    "kind": kind,
                    "region_type": region_type,
                },
                visible=False,
                optional=True,
                legend=False,
            )
        )

    for place, names in polygon_places:
        geometry = dissolve(select_counties(counties, names, place["id"]))
        region = polygon_record(place, tree, geometry, names)
        write_geojson(region, OUT / f"{place['id']}.geojson")
        is_top_level = place["depth"] == 0
        entry = index_entry(
            {
                **place,
                "region_type": region_type_for(place["kind"]),
            },
            visible=is_top_level,
            legend=is_top_level,
        )
        if is_top_level:
            entry["overlay_group"] = "region"
        index["regions"].append(entry)

    for place in point_places:
        (OUT / f"{place['id']}.geojson").write_text(
            json.dumps(point_feature_collection(place, tree), separators=(",", ":"), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        index["regions"].append(
            index_entry(
                {
                    **place,
                    "region_type": region_type_for(place["kind"]),
                },
                visible=False,
                legend=False,
            )
        )

    if not args.no_socal_draft:
        apply_socal_draft(index, OUT, validated_draft=validated_draft)
    # Always apply: CA-14 / Inyokern, China Lake, and the Frazier cut. Draft
    # geometries should already include this redraw; re-running keeps --no-socal-draft
    # and any stale draft copy aligned.
    apply_eastern_kern_ridgeline(OUT)
    (OUT / "index.json").write_text(json.dumps(index, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")

    report = [
        "# California MeshCore region build",
        "",
        f"- Source: `{regions_path}`",
        f"- Places in tree: {len(places)}",
        f"- Polygon layers: {len(index['regions'])}",
        "",
        "County assignments before applying the SoCal draft:",
    ]
    for place in places:
        if place["depth"] == 0:
            names = top_level_counties.get(place["id"], [])
            report.append(f"- `{place['id']}` {place['name']} ({len(names)}): {', '.join(names)}")
    (TOOLS / "validation_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Wrote region GeoJSON to {OUT}")
    print(f"Read places from {regions_path}")


if __name__ == "__main__":
    main()
