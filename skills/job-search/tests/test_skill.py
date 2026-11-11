from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_package_files_exist():
    for name in ("config.yaml", "skill.md", "README.md"):
        assert (ROOT / name).exists(), name


def test_config_name_and_triggers():
    raw = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    assert raw["name"] == "job-search"
    triggers = [t.lower() for t in raw["triggers"]]
    assert any("job" in t for t in triggers)
    assert "web" in raw["permissions"]
    assert "browser" in raw["permissions"]


def test_skill_requires_deep_pass():
    text = (ROOT / "skill.md").read_text(encoding="utf-8").lower()
    assert "web_search" in text
    assert "browser" in text
    assert "do **not** stop after a single" in text or "do not stop after a single" in text
