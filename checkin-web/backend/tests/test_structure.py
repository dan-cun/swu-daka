from pathlib import Path


def test_runtime_data_is_outside_source_tree_contract() -> None:
    project_root = Path(__file__).resolve().parents[2]
    assert (project_root / "data").exists()
    assert (project_root / ".env.example").exists()

