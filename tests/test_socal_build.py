import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_regions', ROOT / 'region-tools' / 'build_regions.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class DraftBuildTests(unittest.TestCase):
    def assert_build_rejected_before_writes(self, tree, draft_dir, expected_error):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree_path, census_input, output = root / 'regions.json', root / 'census.geojson', root / 'output'
            tree_path.write_text(json.dumps(tree))
            census_input.touch()
            output.mkdir()
            sentinel = output / 'socal.geojson'
            sentinel.write_text('existing map data')
            index = output / 'index.json'
            index.write_text('existing manifest')
            with patch.object(builder, 'DRAFT_DIR', draft_dir), \
                 patch.object(builder, 'COUNTY_INPUT', census_input), \
                 patch.object(builder, 'STATE_INPUT', census_input), \
                 patch.object(builder, 'OUT', output), \
                 patch('sys.argv', ['build_regions.py', '--regions', str(tree_path)]), \
                 patch.object(builder.gpd, 'read_file', side_effect=AssertionError('preflight must happen first')):
                with self.assertRaisesRegex(ValueError, expected_error):
                    builder.main()
            self.assertEqual(sentinel.read_text(), 'existing map data')
            self.assertEqual(index.read_text(), 'existing manifest')
            self.assertEqual(set(output.iterdir()), {sentinel, index})

    def test_curated_draft_is_reapplied_to_generated_data(self):
        baseline = json.loads((ROOT / 'public' / 'regions' / 'index.json').read_text())
        baseline['title'] = 'California MeshCore Region Map'
        baseline.pop('notes', None)
        baseline['regions'] = [entry for entry in baseline['regions'] if entry.get('overlay_group') != 'subregion']
        untouched = next(entry for entry in baseline['regions'] if entry['id'] == 'bayarea').copy()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            builder.apply_socal_draft(baseline, output)
            self.assertEqual(baseline['title'], 'California MeshCore Region Map · SoCal draft')
            self.assertIn('draft for planning', baseline['notes'])
            drafts = [entry for entry in baseline['regions'] if entry.get('overlay_group') == 'subregion']
            self.assertEqual(len(drafts), 17)
            self.assertEqual(len({e['id'] for e in baseline['regions']}), len(baseline['regions']))
            self.assertEqual(next(e for e in drafts if e['id'] == 'sfvalley')['proposed_code'], 'socal-sfv')
            self.assertEqual(next(e for e in drafts if e['id'] == 'sfvalley')['area_code_hints'], ['818', '747'])
            self.assertEqual(next(e for e in baseline['regions'] if e['id'] == 'socal')['coordination_status'], 'proposed')
            self.assertEqual(next(e for e in baseline['regions'] if e['id'] == 'bayarea'), untouched)
            for entry in drafts:
                feature = json.loads((output / entry['file']).read_text())['features'][0]
                self.assertEqual(feature['properties']['id'], entry['id'])
                self.assertEqual(feature['properties']['proposed_code'], entry['proposed_code'])
            self.assertEqual(json.loads((output / 'socal.geojson').read_text())['features'][0]['properties']['draft'], True)
            for filename in ('socal.geojson', 'centralcoast.geojson', 'slo.geojson', 'draft-santamaria.geojson'):
                self.assertEqual(json.loads((output / filename).read_text()),
                                 json.loads((ROOT / 'public' / 'regions' / filename).read_text()))
            self.assertEqual(json.loads((output / 'socal-boundary-notes.geojson').read_text()),
                             json.loads((builder.DRAFT_DIR / 'boundary-notes.geojson').read_text()))
            builder.apply_socal_draft(baseline, output)
            self.assertEqual(len([e for e in baseline['regions'] if e.get('overlay_group') == 'subregion']), 17)

    def test_unrelated_tree_is_not_modified(self):
        index = {'regions': [{'id': 'other', 'name': 'Other', 'file': 'other.geojson'}]}
        with tempfile.TemporaryDirectory() as directory:
            builder.apply_socal_draft(index, Path(directory))
            self.assertEqual(index, {'regions': [{'id': 'other', 'name': 'Other', 'file': 'other.geojson'}]})
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_missing_curated_geometries_fail_before_any_output(self):
        manifest = (builder.DRAFT_DIR / 'manifest.json').read_text()
        geometry = json.loads((builder.DRAFT_DIR / 'geometries.geojson').read_text())
        baseline = json.loads((ROOT / 'public' / 'regions' / 'index.json').read_text())
        for missing_id in ('socal', 'centralcoast', 'centralvalley', 'sierranevada',
                           'slo', 'cvsouth', 'eastsierra', 'sfvalley'):
            with self.subTest(missing_id=missing_id), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, output = root / 'source', root / 'output'
                source.mkdir()
                output.mkdir()
                (source / 'manifest.json').write_text(manifest)
                incomplete = {**geometry, 'features': [feature for feature in geometry['features']
                    if feature['properties']['id'] != missing_id]}
                (source / 'geometries.geojson').write_text(json.dumps(incomplete))
                index = json.loads(json.dumps(baseline))
                with patch.object(builder, 'DRAFT_DIR', source):
                    with self.assertRaisesRegex(ValueError, f'Missing SoCal draft geometries:.*{missing_id}'):
                        builder.apply_socal_draft(index, output)
                self.assertEqual(list(output.iterdir()), [])
                self.assertEqual(index, baseline)

    def test_missing_geometry_preflight_preserves_existing_build(self):
        tree = json.loads((ROOT / 'data' / 'regions.json').read_text())
        geometry = json.loads((builder.DRAFT_DIR / 'geometries.geojson').read_text())
        geometry['features'] = [f for f in geometry['features'] if f['properties']['id'] != 'socal']
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / 'manifest.json').write_text((builder.DRAFT_DIR / 'manifest.json').read_text())
            (source / 'geometries.geojson').write_text(json.dumps(geometry))
            self.assert_build_rejected_before_writes(tree, source, 'Missing SoCal draft geometries:.*socal')

    def test_missing_or_invalid_boundary_notes_preserve_existing_build(self):
        tree = json.loads((ROOT / 'data' / 'regions.json').read_text())
        notes = json.loads((builder.DRAFT_DIR / 'boundary-notes.geojson').read_text())
        invalid_cases = [None, '[]', '{"type":"FeatureCollection","features":[]}']
        for coordinates in (None, [], [[0, 0]], [[0, 0], [0, 0]], [[181, 35], [0, 0]], [[float('nan'), 35], [0, 0]]):
            invalid_note = json.loads(json.dumps(notes))
            invalid_note['features'][0]['geometry']['coordinates'] = coordinates
            invalid_cases.append(json.dumps(invalid_note))
        missing_title = json.loads(json.dumps(notes))
        missing_title['features'][0]['properties']['title'] = ''
        invalid_cases.append(json.dumps(missing_title))
        for invalid in invalid_cases:
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                source = Path(directory)
                for name in ('manifest.json', 'geometries.geojson'):
                    (source / name).write_text((builder.DRAFT_DIR / name).read_text())
                if invalid is not None:
                    (source / 'boundary-notes.geojson').write_text(invalid)
                self.assert_build_rejected_before_writes(tree, source, 'SoCal boundary notes are missing or invalid')

    def test_incompatible_custom_assignments_preserve_existing_build(self):
        original = json.loads((ROOT / 'data' / 'regions.json').read_text())
        for change in ('top_level', 'adjusted_legacy'):
            with self.subTest(change=change):
                tree = json.loads(json.dumps(original))
                if change == 'top_level':
                    bayarea = next(place for place in tree['places'] if place['code'] == 'bayarea')
                    bayarea['outline'] = ['Ventura']
                else:
                    sierra = next(place for place in tree['places'] if place['code'] == 'sierranevada')
                    east = next(place for place in sierra['children'] if place['code'] == 'eastsierra')
                    east['outline'].append('Mariposa')
                self.assert_build_rejected_before_writes(tree, builder.DRAFT_DIR, 'SoCal draft.*--no-socal-draft')

    def test_conflicting_id_preserves_existing_build(self):
        for conflicting_id in ('sfvalley', 'california'):
            with self.subTest(conflicting_id=conflicting_id):
                tree = json.loads((ROOT / 'data' / 'regions.json').read_text())
                socal = next(place for place in tree['places'] if place['code'] == 'socal')
                socal['children'].append({'code': conflicting_id, 'name': 'Conflicting area', 'outline': ['Los Angeles']})
                error = 'SoCal draft id conflicts.*sfvalley' if conflicting_id == 'sfvalley' else 'Duplicate generated region ids:.*california'
                self.assert_build_rejected_before_writes(tree, builder.DRAFT_DIR, error)

    def test_invalid_target_filename_preserves_existing_build(self):
        tree = json.loads((ROOT / 'data' / 'regions.json').read_text())
        for change in ('proposal_path', 'update_path', 'duplicate_target', 'state_target', 'previous_target', 'boundary_notes_target',
                       'non_curated_path', 'non_curated_filename'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                draft = json.loads((builder.DRAFT_DIR / 'manifest.json').read_text())
                if change == 'update_path':
                    next(entry for entry in draft['updates'] if entry['id'] == 'socal')['file'] = '../escape.geojson'
                elif change in ('non_curated_path', 'non_curated_filename'):
                    entry = next(entry for entry in draft['updates'] if entry['id'] == 'bayarea')
                    entry['file'] = '../escape.geojson' if change == 'non_curated_path' else 'other.geojson'
                else:
                    entry = next(entry for entry in draft['subregions'] if entry['id'] == 'sfvalley')
                    entry['file'] = {'proposal_path': '../escape.geojson',
                                     'duplicate_target': 'bayarea.geojson',
                                     'state_target': 'california.geojson',
                                     'previous_target': 'socal.geojson',
                                     'boundary_notes_target': 'socal-boundary-notes.geojson'}[change]
                    if change == 'previous_target':
                        next(e for e in draft['updates'] if e['id'] == 'socal')['file'] = 'new-socal.geojson'
                source = Path(directory)
                (source / 'manifest.json').write_text(json.dumps(draft))
                (source / 'geometries.geojson').write_text((builder.DRAFT_DIR / 'geometries.geojson').read_text())
                if change in ('non_curated_path', 'non_curated_filename'):
                    error = 'SoCal draft cannot change filename for non-curated region: bayarea'
                elif change in ('proposal_path', 'update_path'):
                    error = 'Invalid draft GeoJSON filename'
                else:
                    error = 'Duplicate draft GeoJSON filename'
                self.assert_build_rejected_before_writes(tree, source, error)


if __name__ == '__main__':
    unittest.main()
