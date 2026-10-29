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


if __name__ == '__main__':
    unittest.main()
