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
SOURCE = "U.S. Census Bureau 2024 cartographic boundary files"
SETTINGS_SOURCE = "meshcore-settings California region tree"
DRAFT_DIR = ROOT / "data" / "socal-draft"

LEVEL_TYPES = {
    "region": "Region",
    "area": "Area",
    "local area": "Local Area",
}

# meshcore-settings leaves some counties only on local areas or nested outlines
# that would otherwise overlap a sibling. These extras are map-only.
OUTLINE_EXTRAS = {
    "cvsouth": ["Kern"],
}

OUTLINE_REMOVALS = {
    "goldcountry": ["Sierra"],
}

ID_OVERRIDES = {
    "oc": "orange",
    "orangecounty": "orange",
}

# Counties that a top-level region should own even when another region's
# outline or nested tree would claim them. These extras win first.
TOP_LEVEL_EXTRAS = {
    "sacramentofoothills": ["Butte", "Sierra", "Nevada"],
}


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
            ROOT.parent / "meshcore-settings" / "data" / "regions.json",
            ROOT / "data" / "regions.json",
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
    return list(place["outline"])


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


def california_record(state: gpd.GeoDataFrame, tree: dict) -> gpd.GeoDataFrame:
    region = dissolve(state[["geometry"]])
    region["id"] = "california"
    region["name"] = "California"
    region["short_name"] = "CALIFORNIA"
    region["kind"] = "state_region"
    region["region_type"] = "State Region"
    region["boundary_basis"] = "Existing political boundary represented by a U.S. Census state boundary"
    region["notes"] = "Statewide umbrella for the meshcore-settings California tree."
    root = [item["code"] for item in tree.get("root") or [] if item.get("code")]
    region["region_chain"] = " ".join(root) if root else "california"
    region["counties"] = ""
    region["draft"] = False
    region["source"] = SOURCE
    region["coordinator"] = ""
    return region


def index_entry(place: dict, *, visible: bool, optional: bool = False, legend: bool = True) -> dict:
    status = "official_local" if place["id"] != "california" else "political_boundaries"
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
    for place in places:
        names = counties_for(place, top_level_counties)
        if names:
            polygon_places.append((place, names))
    generated_entries = [{"id": "california", "file": "california.geojson"}] + [
        {"id": place["id"], "file": f"{place['id']}.geojson"} for place, _ in polygon_places
    ]
    validated_draft = None if args.no_socal_draft else load_socal_draft(generated_entries)
    if validated_draft is not None:
        validate_socal_compatibility(validated_draft[0], places, top_level_counties)
    counties = gpd.read_file(COUNTY_INPUT).to_crs(4326)
    state = gpd.read_file(STATE_INPUT).to_crs(4326)

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

    california = california_record(state, tree)
    write_geojson(california, OUT / "california.geojson")
    index["regions"].append(
        index_entry(
            {
                "id": "california",
                "name": "California",
                "short_name": "CALIFORNIA",
                "kind": "state_region",
                "region_type": "State Region",
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
        index["regions"].append(
            index_entry(
                {
                    **place,
                    "region_type": region_type_for(place["kind"]),
                },
                visible=is_top_level,
                legend=is_top_level,
            )
        )

    if not args.no_socal_draft:
        apply_socal_draft(index, OUT, validated_draft=validated_draft)
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
