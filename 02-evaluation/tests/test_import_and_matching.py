import json
import tempfile
import unittest
from pathlib import Path

from poi_evaluator.db import connect, initialize
from poi_evaluator.importer import import_dataset
from poi_evaluator.matching import match_candidates, resolve_match
from poi_evaluator.reports import build_agent_report, build_report, export_review_queue


class ImportAndMatchingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.connection = connect(self.root / "test.sqlite")
        initialize(self.connection)

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def _write(self, name, payload):
        path = self.root / name
        text = json.dumps(payload, ensure_ascii=False, indent=1)
        path.write_text(text, encoding="utf-8")
        return path, text

    def _run_id(self):
        cursor = self.connection.execute(
            "INSERT INTO evaluation_runs(run_type, status) VALUES ('matching', 'running')"
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def test_import_preserves_document_and_expands_children(self):
        path, original = self._write(
            "agent.json",
            {
                "metadata": {
                    "schemaVersion": "1",
                    "datasetVersion": "demo-1",
                    "language": "en",
                    "destinationId": "example-city"
                },
                "pois": [
                    {
                        "id": "poi-1",
                        "name": "Mestská veža",
                        "lat": 48.1,
                        "lon": 17.1,
                        "tags": ["Historic Site"],
                        "externalIds": {"wikidata": "Q1"},
                        "links": [{"type": "official", "url": "https://example.com"}],
                        "media": {
                            "primaryImage": {
                                "url": "https://example.com/image.jpg",
                                "sourcePageUrl": "https://example.com/image-page",
                                "license": "CC0"
                            }
                        },
                        "ratings": {"google": {"value": 4.5, "reviewCount": 10}},
                        "evidence": [{"type": "identity", "url": "https://example.com/source"}],
                    }
                ],
            },
        )
        summary = import_dataset(self.connection, path, "agent-a")
        self.assertEqual(summary["poi_count"], 1)
        stored = self.connection.execute("SELECT raw_document_json FROM submissions").fetchone()[0]
        self.assertEqual(stored, original)
        submission = self.connection.execute(
            "SELECT schema_version, dataset_version, language, region_name FROM submissions"
        ).fetchone()
        self.assertEqual(tuple(submission), ("1", "demo-1", "en", "example-city"))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM poi_records").fetchone()[0], 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM tags").fetchone()[0], 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM external_identifiers").fetchone()[0], 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM links").fetchone()[0], 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM images").fetchone()[0], 1)
        image = self.connection.execute("SELECT image_url, page_url FROM images").fetchone()
        self.assertEqual(tuple(image), ("https://example.com/image.jpg", "https://example.com/image-page"))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM ratings").fetchone()[0], 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0], 1)

    def test_external_id_creates_same_place_and_canonical_poi(self):
        first, _ = self._write(
            "a.json",
            {"pois": [{"id": "a", "name": "Colosseum", "category": "monument", "lat": 41.8902, "lon": 12.4922, "externalIds": {"wikidata": "Q10285"}}]},
        )
        second, _ = self._write(
            "b.json",
            {"pois": [{"id": "b", "name": "Colosseo", "category": "archaeological_site", "lat": 41.89021, "lon": 12.49221, "externalIds": {"wikidata": "Q10285"}}]},
        )
        import_dataset(self.connection, first, "agent-a")
        import_dataset(self.connection, second, "agent-b")
        summary = match_candidates(self.connection, self._run_id())
        self.assertEqual(summary["auto_accepted"], 1)
        match = self.connection.execute("SELECT relation, status FROM matches").fetchone()
        self.assertEqual(tuple(match), ("same_place", "auto_accepted"))
        canonical_ids = self.connection.execute("SELECT DISTINCT canonical_poi_id FROM poi_records").fetchall()
        self.assertEqual(len(canonical_ids), 1)
        self.assertIsNotNone(canonical_ids[0][0])
        self.assertEqual(summary["conflicts_created"], 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM conflicts").fetchone()[0], 1)

    def test_fuzzy_candidate_enters_review_and_can_be_resolved(self):
        first, _ = self._write(
            "a.json",
            {"pois": [{"id": "a", "name": "National History Museum", "lat": 48.1000, "lon": 17.1000}]},
        )
        second, _ = self._write(
            "b.json",
            {"pois": [{"id": "b", "name": "National Historical Museum", "lat": 48.1001, "lon": 17.1001}]},
        )
        import_dataset(self.connection, first, "agent-a")
        import_dataset(self.connection, second, "agent-b")
        match_candidates(self.connection, self._run_id(), fuzzy_threshold=0.75)
        match = self.connection.execute("SELECT id, relation FROM matches").fetchone()
        self.assertEqual(match["relation"], "uncertain")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0], 1)
        resolve_match(self.connection, match["id"], "related", "tester")
        status = self.connection.execute("SELECT status FROM review_queue").fetchone()[0]
        self.assertEqual(status, "resolved")

    def test_report_and_review_export(self):
        path, _ = self._write("a.json", {"pois": [{"id": "a", "name": "Only Place"}]})
        import_dataset(self.connection, path, "agent-a")
        report = build_report(self.connection)
        self.assertEqual(report["totals"]["poi_records"], 1)
        output = self.root / "review.jsonl"
        self.assertEqual(export_review_queue(self.connection, output), 0)
        self.assertEqual(output.read_text(encoding="utf-8"), "")

    def test_agent_report_marks_unchecked_urls_inconclusive(self):
        path, _ = self._write(
            "a.json",
            {"pois": [{"id": "a", "name": "Only Place", "description": "A useful description.",
                       "lat": 48.1, "lon": 17.1,
                       "links": [{"type": "official", "url": "https://example.com"}]}]},
        )
        import_dataset(self.connection, path, "agent-a")
        report = build_agent_report(self.connection)
        agent = report["agents"][0]
        self.assertEqual(agent["record_counts"]["poi"], 1)
        self.assertEqual(agent["url_validation"]["total"], 0)
        self.assertEqual(agent["url_validation"]["inconclusive"], 0)
        self.assertEqual(agent["provisional_rank"], 1)


if __name__ == "__main__":
    unittest.main()
