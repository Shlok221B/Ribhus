from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_package_files_exist():
    for name in ("config.yaml", "skill.md", "README.md"):
        assert (ROOT / name).exists(), name


def test_config_name():
    raw = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    assert raw["name"] == "travel"
    assert "hotel" in raw["triggers"]
    assert "open payment" in raw["triggers"]


def test_skill_has_payment_handoff_phase():
    text = (ROOT / "skill.md").read_text(encoding="utf-8")
    assert "Phase B" in text
    assert "payment" in text.lower()
    assert "card" in text.lower() or "UPI" in text
