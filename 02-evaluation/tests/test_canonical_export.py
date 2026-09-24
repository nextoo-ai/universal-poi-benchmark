import json
import tempfile
import unittest
from pathlib import Path

from poi_evaluator.canonical_export import build_canonical_datasets, write_canonical_exports
from poi_evaluator.db import connect, initialize
from poi_evaluator.importer import import_dataset
from poi_evaluator.matching import match_candidates


class CanonicalExportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.connection = connect(self.root / "test.sqlite")
        initialize(self.connection)

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def _import(self, filename, agent, poi):
        path = self.root / filename
        path.write_text(json.dumps({"pois": [poi]}), encoding="utf-8")
        import_dataset(self.connection, path, agent)

    def _run_id(self):
        cursor = self.connection.execute(
            "INSERT INTO evaluation_runs(run_type, status) VALUES ('matching', 'running')"
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def test_export_merges_records_and_filters_safe_profile(self):
        licensed_image = {
            "url": "https://example.com/licensed.jpg",
            "sourcePageUrl": "https://example.com/photo",
            "license": "CC BY 4.0",
            "licenseUrl": "https://creativecommons.org/licenses/by/4.0/",
            "creator": "Photographer",
        }
        self._import(
            "a.json",
            "agent-a",
            {
                "id": "a",
                "name": "Colosseum",
                "category": "monument",
                "description": "A long and useful description of the amphitheatre.",
                "lat": 41.8902,
                "lon": 12.4922,
                "externalIds": {"wikidata": "Q10285"},
                "tags": ["history"],
                "media": {"primaryImage": licensed_image},
                "ratings": {
                    "google": {
                        "score": 4.7,
                        "reviewCount": 100,
                        "verifiedAt": "2026-01-01",
                        "sourceUrl": "https://example.com/rating",
                    }
                },
            },
        )
        self._import(
            "b.json",
            "agent-b",
            {
                "id": "b",
                "name": "Colosseo",
                "category": "monument",
                "lat": 41.8903,
                "lon": 12.4923,
                "externalIds": {"wikidata": "Q10285"},
                "images": [{"url": "https://example.com/unknown.jpg", "license": "unknown"}],
            },
        )
        match_candidates(self.connection, self._run_id())
        rating_id = self.connection.execute("SELECT id FROM ratings").fetchone()[0]
        self.connection.execute(
            """
            INSERT INTO url_checks(target_type, target_id, url, validator_version, status)
            VALUES ('rating', ?, 'https://example.com/rating', 'test', 'reachable')
            """,
            (rating_id,),
        )
        self.connection.commit()

        safe, detailed, audit = build_canonical_datasets(self.connection, "test-v1")
        self.assertEqual(audit["counts"]["exportedEntities"], 1)
        self.assertEqual(detailed["pois"][0]["id"], "wikidata:Q10285")
        self.assertEqual(len(detailed["pois"][0]["provenance"]["sourceRecords"]), 2)
        self.assertEqual(len(detailed["pois"][0]["media"]), 2)
        self.assertEqual(len(safe["pois"][0]["media"]), 1)
        self.assertEqual(safe["pois"][0]["media"][0]["rightsStatus"], "verified-permissive")
        self.assertEqual(safe["pois"][0]["ratings"][0]["scale"], {"min": 0.0, "max": 5.0})
        self.assertEqual(safe["pois"][0]["ratings"][0]["verificationStatus"], "verified-source")

        paths = [self.root / name for name in ("safe.json", "detailed.json", "audit.json")]
        counts = write_canonical_exports(self.connection, *paths, dataset_version="test-v1")
        self.assertEqual(counts["exportedEntities"], 1)
        self.assertTrue(all(path.exists() for path in paths))

    def test_open_uncertain_pair_is_excluded(self):
        self._import(
            "a.json",
            "agent-a",
            {"id": "a", "name": "National History Museum", "category": "museum", "lat": 48.1, "lon": 17.1},
        )
        self._import(
            "b.json",
            "agent-b",
            {"id": "b", "name": "National Historical Museum", "category": "museum", "lat": 48.1001, "lon": 17.1001},
        )
        match_candidates(self.connection, self._run_id(), fuzzy_threshold=0.75)
        safe, detailed, audit = build_canonical_datasets(self.connection)
        self.assertEqual(safe["pois"], [])
        self.assertEqual(detailed["pois"], [])
        self.assertEqual(audit["counts"]["excludedAmbiguousEntities"], 2)


if __name__ == "__main__":
    unittest.main()
