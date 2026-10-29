#!/usr/bin/env python3
"""Check the local region boundaries after editing them (requires Shapely 2)."""
import argparse
import json
from pathlib import Path

try:
    from shapely.geometry import shape
    from shapely.ops import unary_union
    from shapely.validation import explain_validity
except ImportError as exc:
    raise SystemExit('Install Shapely in a development environment to check region topology.') from exc


ROOT = Path(__file__).resolve().parents[1] / 'public' / 'regions'
TOLERANCE = 1e-8  # square degrees, for floating-point noise at shared edges


def check(directory):
    manifest = json.loads((directory / 'index.json').read_text())
    entries = manifest['regions']
    names = [entry['id'] for entry in entries]
    if len(names) != len(set(names)):
        raise ValueError('Region identifiers must be unique across the manifest.')
    geometries = {}
    for entry in entries:
        name = entry['file']
        if Path(name).name != name:
            raise ValueError(f'Invalid local region file: {name}')
        data = json.loads((directory / name).read_text())
        if data.get('type') != 'FeatureCollection' or not data.get('features'):
            raise ValueError(f'{name} must contain a nonempty FeatureCollection.')
        features = []
        for feature in data['features']:
            geometry = shape(feature['geometry'])
            if geometry.geom_type not in ('Polygon', 'MultiPolygon') or geometry.is_empty or not geometry.is_valid:
                raise ValueError(f'{name} has invalid geometry: {explain_validity(geometry)}')
            features.append(geometry)
        geometries[entry['id']] = unary_union(features)

    def group(kind):
        return [(entry['id'], geometries[entry['id']]) for entry in entries if entry.get('overlay_group') == kind]

    def partition(items, parent, label):
        if not items:
            raise ValueError(f'{label} has no regions.')
        for index, (name, geometry) in enumerate(items):
            for other, neighbor in items[index + 1:]:
                if geometry.intersection(neighbor).area > TOLERANCE:
                    raise ValueError(f'{label} regions overlap: {name} and {other}.')
        union = unary_union([geometry for _, geometry in items])
        if parent.difference(union).area > TOLERANCE:
            raise ValueError(f'{label} has a gap in its parent boundary.')
        if union.difference(parent).area > TOLERANCE:
            raise ValueError(f'{label} extends outside its parent boundary.')

    regions, subregions = group('region'), group('subregion')
    partition(regions, geometries['california'], 'California')
    partition(subregions, geometries['socal'], 'SoCal')
    print(f'Valid: {len(regions)} California regions and {len(subregions)} SoCal subregions cover their parents without overlaps.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--regions-dir', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        check(args.regions_dir)
    except (KeyError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == '__main__':
    main()
