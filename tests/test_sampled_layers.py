import gzip
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REGIONS = ROOT / 'public' / 'regions'


class SampledLayerTests(unittest.TestCase):
    def read_layer(self, name):
        with gzip.open(REGIONS / name, 'rt', encoding='utf-8') as source:
            data = json.load(source)
        self.assertEqual(data['type'], 'FeatureCollection')
        return data['features']

    def test_coverage_contains_only_display_shapes_and_bands(self):
        features = self.read_layer('sampled-coverage.geojson.gz')
        self.assertEqual({feature['properties']['band'] for feature in features}, {1, 2, 3, 4, 5})
        for feature in features:
            self.assertEqual(set(feature['properties']), {'band'})
            self.assertEqual(feature['geometry']['type'], 'MultiPolygon')
            self.assertTrue(feature['geometry']['coordinates'])

    def test_topology_contains_only_the_reported_path_geometry(self):
        features = self.read_layer('sampled-topology.geojson.gz')
        self.assertEqual(len(features), 1)
        self.assertEqual(features[0]['properties'], {})
        self.assertEqual(features[0]['geometry']['type'], 'MultiLineString')
        paths = features[0]['geometry']['coordinates']
        self.assertEqual(len(paths), 1727)
        self.assertTrue(all(len(path) >= 2 for path in paths))
        self.assertTrue(all(-180 <= lon <= 180 and -90 <= lat <= 90
                            for path in paths for lon, lat in path))


if __name__ == '__main__':
    unittest.main()
