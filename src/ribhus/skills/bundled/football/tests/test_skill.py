from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_package_files_exist():
    for name in ("config.yaml", "skill.md", "README.md"):
        assert (ROOT / name).exists(), name


def test_config_name():
    raw = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    assert raw["name"] == "football"
    assert "football" in raw["triggers"]
    assert "isl" in raw["triggers"]
