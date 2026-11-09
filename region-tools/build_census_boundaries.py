#!/usr/bin/env python3
"""Download Census cartographic state and county boundaries used by the map."""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import requests

YEAR = 2024
RESOLUTION = "5m"
WEST_OUTLINE_RESOLUTION = "20m"
OUT = Path(__file__).resolve().parent
STATE_URL = f"https://www2.census.gov/geo/tiger/GENZ{YEAR}/shp/cb_{YEAR}_us_state_{RESOLUTION}.zip"
WEST_STATE_URL = (
    f"https://www2.census.gov/geo/tiger/GENZ{YEAR}/shp/cb_{YEAR}_us_state_{WEST_OUTLINE_RESOLUTION}.zip"
)
COUNTY_URL = f"https://www2.census.gov/geo/tiger/GENZ{YEAR}/shp/cb_{YEAR}_us_county_{RESOLUTION}.zip"
CALIFORNIA_FIPS = "06"
# Continental states west of the Rocky Mountains (Pacific + Intermountain).
WESTERN_STATE_CODES = ("WA", "OR", "CA", "NV", "AZ", "ID", "UT")


def download_and_extract(url: str, destination: Path) -> Path:
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        zf.extractall(destination)
    return next(destination.glob("*.shp"))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        source_root = Path(tmp)
        state_dir = source_root / "state_source"
        west_dir = source_root / "west_state_source"
        county_dir = source_root / "county_source"
        state_dir.mkdir()
        west_dir.mkdir()
        county_dir.mkdir()

        states = gpd.read_file(download_and_extract(STATE_URL, state_dir)).to_crs(4326)
        west_source = gpd.read_file(download_and_extract(WEST_STATE_URL, west_dir)).to_crs(4326)
        counties = gpd.read_file(download_and_extract(COUNTY_URL, county_dir)).to_crs(4326)

        state_cols = [c for c in ["STATEFP", "STUSPS", "NAME", "GEOID", "geometry"] if c in states.columns]
        county_cols = [
            c for c in ["STATEFP", "COUNTYFP", "NAME", "NAMELSAD", "GEOID", "geometry"] if c in counties.columns
        ]

        california = states[states["STATEFP"] == CALIFORNIA_FIPS][state_cols]
        california_counties = counties[counties["STATEFP"] == CALIFORNIA_FIPS][county_cols]
        western = west_source[west_source["STUSPS"].isin(WESTERN_STATE_CODES)][state_cols]
        if california.empty or california_counties.empty:
            raise RuntimeError("Census download did not include California")
        missing_west = sorted(set(WESTERN_STATE_CODES) - set(western["STUSPS"]))
        if missing_west:
            raise RuntimeError(f"Census download missed western states: {missing_west}")

        california.to_file(OUT / "census_california_state.geojson", driver="GeoJSON")
        california_counties.to_file(OUT / "census_california_counties.geojson", driver="GeoJSON")
        western.to_file(OUT / "census_western_states.geojson", driver="GeoJSON")

    print(f"Wrote Census GeoJSON to {OUT.resolve()}")


if __name__ == "__main__":
    main()
