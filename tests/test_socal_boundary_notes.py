import json
from pathlib import Path
import unittest

from shapely.geometry import Point, shape
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[1]
REGIONS = ROOT / "public/regions"


def geometry(name):
    data = json.loads((REGIONS / f"{name}.geojson").read_text())
    return unary_union([shape(feature["geometry"]) for feature in data["features"]])


class NorthernBoundaryNoteTests(unittest.TestCase):
    def test_central_coast_and_santa_maria_stay_on_the_intended_sides(self):
        socal = geometry("socal")
        coast = geometry("centralcoast")
        santa_maria = geometry("draft-santamaria")
        for name, coordinates in (
            ("San Luis Obispo", (-120.6596, 35.2828)),
            ("Pismo Beach", (-120.6413, 35.1428)),
            ("Arroyo Grande", (-120.5907, 35.1186)),
            ("Oceano", (-120.6154, 35.0989)),
        ):
            with self.subTest(place=name):
                point = Point(*coordinates)
                self.assertTrue(coast.covers(point))
                self.assertFalse(socal.covers(point))
        for name, coordinates in (
            ("Santa Maria", (-120.4357, 34.9530)),
            ("Guadalupe", (-120.5718, 34.9716)),
            ("Nipomo", (-120.4763, 35.0428)),
        ):
            with self.subTest(place=name):
                point = Point(*coordinates)
                self.assertTrue(socal.covers(point))
                self.assertTrue(santa_maria.covers(point))
                self.assertFalse(coast.covers(point))

        index = json.loads((REGIONS / "index.json").read_text())["regions"]
        entry = next(item for item in index if item["id"] == "santamaria")
        self.assertEqual(entry["proposed_code"], "socal-smv")
        self.assertFalse(any(item["id"] == "slocoast" for item in index))

    def test_notes_trace_the_shared_proposal_boundary(self):
        notes = json.loads((REGIONS / "socal-boundary-notes.geojson").read_text())["features"]
        lines = {feature["properties"]["id"]: shape(feature["geometry"]) for feature in notes}
        neighbors = {name: geometry(name) for name in ("centralcoast", "centralvalley", "sierranevada")}
        self.assertEqual(set(lines), set(neighbors))
        self.assertEqual(len(notes), 3)

        socal_boundary = geometry("socal").boundary
        for name, line in lines.items():
            with self.subTest(neighbor=name):
                self.assertEqual(line.geom_type, "LineString")
                self.assertTrue(line.is_valid)
                self.assertLess(line.difference(socal_boundary.buffer(1e-8)).length, 1e-7)
                # Small intervening contact fragments are grouped with the long
                # Central Valley segment so each explanation has one continuous line.
                shared = line.intersection(neighbors[name].boundary.buffer(1e-8)).length
                self.assertGreater(shared / line.length, 0.98)

        all_notes = unary_union(list(lines.values()))
        shared_border = unary_union([socal_boundary.intersection(neighbor.boundary) for neighbor in neighbors.values()])
        self.assertLess(shared_border.difference(all_notes.buffer(1e-8)).length, 1e-7)
        self.assertLess(all_notes.difference(shared_border.buffer(1e-8)).length, 1e-7)


if __name__ == "__main__":
    unittest.main()
