import copy
import importlib.util
import pathlib
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('poi_validate',ROOT/'tools'/'validate.py')
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class ValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema=mod.load(ROOT/'poi.schema.json')
        cls.taxonomy=mod.load(ROOT/'taxonomy.json')
        cls.profile=mod.load(ROOT/'destination.json')
        cls.config=mod.load(ROOT/'benchmark.config.json')
        cls.empty=mod.load(ROOT/'examples/empty-dataset.example.json')

    def test_schema_is_valid(self):
        from jsonschema import Draft202012Validator
        Draft202012Validator.check_schema(self.schema)

    def test_empty_dataset_is_schema_valid_but_fails_benchmark(self):
        from jsonschema import Draft202012Validator,FormatChecker
        self.assertFalse(list(Draft202012Validator(self.schema,format_checker=FormatChecker()).iter_errors(self.empty)))
        result=mod.validate(self.empty,self.schema,self.taxonomy,self.profile,self.config)
        self.assertFalse(result['passed'])
        self.assertTrue(any('POI count' in e for e in result['errors']))

    def test_adaptive_does_not_guess_inputs(self):
        cfg=copy.deepcopy(self.config)
        cfg['target']['mode']='adaptive'
        with self.assertRaises(ValueError):mod.compute_target(self.profile,cfg)

    def test_target_fixed(self):
        self.assertEqual(mod.compute_target(self.profile,self.config),500)

if __name__=='__main__':unittest.main()

