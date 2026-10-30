import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ScopeStackTests(unittest.TestCase):
    def test_socal_subregion_stacks_use_distinct_valid_names(self):
        """The map's suggested scopes meet MeshCore's published naming rules."""
        manifest = json.loads((ROOT / 'data/socal-draft/manifest.json').read_text())
        codes = set()
        for entry in manifest['subregions']:
            with self.subTest(region=entry['id']):
                code = entry['proposed_code']
                self.assertNotIn(code, codes)
                codes.add(code)
                feature = json.loads((ROOT / 'public/regions' / entry['file']).read_text())['features'][0]
                chain = feature['properties']['region_chain'].split()
                self.assertEqual(chain, ['west', 'california', 'socal', code])
                self.assertEqual(len(chain), len(set(chain)))
                for name in chain:
                    self.assertRegex(name, r'^[a-z0-9-]+$')
                    self.assertLessEqual(len(name.encode('utf-8')), 29)


if __name__ == '__main__':
    unittest.main()
