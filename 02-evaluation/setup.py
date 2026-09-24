"""Compatibility shim for environments with setuptools too old for PEP 621."""

from pathlib import Path

from setuptools import find_packages, setup


setup(
    name="poi-evaluator",
    version="0.1.0",
    description="Deterministic SQLite pipeline for evaluating POI datasets",
    long_description=Path("README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    python_requires=">=3.9",
    package_dir={"": "src"},
    packages=find_packages("src"),
    package_data={"poi_evaluator": ["py.typed"]},
    data_files=[("share/poi-evaluator/schema", ["schema/001_initial.sql"])],
    entry_points={"console_scripts": ["poi-evaluator=poi_evaluator.cli:main"]},
)
