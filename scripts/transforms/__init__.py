"""Per-family transform modules.

The pipeline orchestrator is ``postprocess.py``. The transform functions
themselves live in themed submodules of this package. ``postprocess.py``
re-exports every public symbol so the test surface and external import
path (``import postprocess; postprocess.convert_X(...)``) remain stable.

See QUALITY-REVIEW.md §P3a for the module split rationale.
"""
