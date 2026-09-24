import unittest

from poi_evaluator.normalize import normalize_name, normalize_poi


class NormalizeTests(unittest.TestCase):
    def test_name_is_case_and_diacritic_insensitive(self):
        self.assertEqual(normalize_name("  Námestie SNP & Café  "), "namestie snp and cafe")

    def test_name_keeps_non_latin_scripts(self):
        self.assertEqual(normalize_name("Национальный музей"), "национальный музей")

    def test_nested_coordinates_and_basic_fields(self):
        result = normalize_poi(
            {
                "poiId": "x-1",
                "displayName": "Clock Tower",
                "location": {"lat": "48.1", "lng": "17.1", "city": "Demo"},
                "isHiddenGem": "yes",
            },
            0,
        )
        self.assertEqual(result["original_poi_id"], "x-1")
        self.assertEqual(result["latitude"], 48.1)
        self.assertEqual(result["locality"], "Demo")
        self.assertTrue(result["is_hidden_gem"])


if __name__ == "__main__":
    unittest.main()
