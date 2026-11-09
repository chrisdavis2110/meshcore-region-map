import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'public' / 'regions' / 'original-regions.json'


class OriginalSnapshotTests(unittest.TestCase):
    def test_original_snapshot_matches_its_upstream_revision(self):
        saved = json.loads(SNAPSHOT.read_text())
        revision = saved['source_revision']

        def at_revision(path):
            return json.loads(subprocess.check_output(['git', 'show', f'{revision}:{path}'], cwd=ROOT, stderr=subprocess.DEVNULL))

        try:
            index = at_revision('public/regions/index.json')
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.skipTest('The original upstream revision is not present in this checkout')
        self.assertEqual([item['entry'] for item in saved['regions']], index['regions'])
        current = {entry['id']: entry for entry in json.loads((ROOT / 'public/regions/index.json').read_text())['regions']}
        for item in saved['regions']:
            with self.subTest(region=item['entry']['id']):
                path = 'public/regions/' + item['entry']['file']
                data = item.get('data')
                if data is None:
                    data = json.loads((ROOT / 'public/regions' / current[item['entry']['id']]['file']).read_text())
                self.assertEqual(data, at_revision(path))

    def test_socal_original_and_proposal_are_distinct(self):
        saved = json.loads(SNAPSHOT.read_text())
        original = next(item['data'] for item in saved['regions'] if item['entry']['id'] == 'socal')
        proposal = json.loads((ROOT / 'public' / 'regions' / 'socal.geojson').read_text())
        self.assertNotEqual(original['features'][0]['geometry'], proposal['features'][0]['geometry'])

    def test_original_socal_includes_eastern_kern_ridgeline(self):
        """Original keeps the Tehachapi/El Paso redraw (Ridgecrest / CA-14 / Frazier)."""
        from shapely.geometry import Point, shape

        saved = json.loads(SNAPSHOT.read_text())
        socal = shape(next(item['data'] for item in saved['regions'] if item['entry']['id'] == 'socal')['features'][0]['geometry'])
        for name, point in {
            'Ridgecrest': Point(-117.67, 35.62),
            'Inyokern': Point(-117.812, 35.647),
            'Edwards': Point(-117.88, 34.91),
            'Frazier Mountain Park Road': Point(-118.912, 34.825),
        }.items():
            with self.subTest(place=name):
                self.assertTrue(socal.contains(point), f'{name} should be inside Original SoCal')


if __name__ == '__main__':
    unittest.main()
