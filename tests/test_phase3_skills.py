from __future__ import annotations

from pathlib import Path

import pytest

from ribhus.skills.installer import create_skill, install_skill, remove_skill
from ribhus.skills.loader import load_skill
from ribhus.skills.registry import SkillRegistry


def test_load_bundled_company_research():
    bundled = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "ribhus"
        / "skills"
        / "bundled"
        / "company-research"
    )
    skill = load_skill(bundled)
    assert skill.name == "company-research"
    assert skill.matches("Research this Indian company: Zoho")
    assert "Company brief" in skill.instructions or "Snapshot" in skill.instructions


def test_skill_registry_match_and_addon(tmp_path: Path):
    create_skill("demo-skill", workspace=tmp_path, description="Demo")
    # Strengthen triggers for match test
    cfg = tmp_path / "skills" / "demo-skill" / "config.yaml"
    cfg.write_text(
        "name: demo-skill\nversion: 0.1.0\ndescription: Demo\n"
        "triggers:\n  - demo workflow\nlanguages:\n  - en\n",
        encoding="utf-8",
    )
    registry = SkillRegistry.load_default(tmp_path)
    assert "demo-skill" in registry.names()
    matched = registry.match("Please run the demo workflow now")
    assert len(matched) == 1
    addon = registry.prompt_addon("Please run the demo workflow now")
    assert "Active skills" in addon
    assert "demo-skill" in addon


def test_install_and_remove(tmp_path: Path):
    create_skill("pack", workspace=tmp_path, description="Pack")
    skill = install_skill("pack", workspace=tmp_path)
    assert skill.name == "pack"
    installed = tmp_path / ".ribhus" / "skills" / "pack"
    assert installed.exists()
    remove_skill("pack", workspace=tmp_path)
    assert not installed.exists()


def test_create_skill_refuses_duplicate(tmp_path: Path):
    create_skill("once", workspace=tmp_path)
    with pytest.raises(FileExistsError):
        create_skill("once", workspace=tmp_path)


def test_create_skill_writes_package_files(tmp_path: Path):
    path = create_skill("full-pack", workspace=tmp_path)
    assert (path / "README.md").exists()
    assert (path / "tools.py").exists()
    assert (path / "tests" / "test_skill.py").exists()


def test_company_research_triggers():
    bundled = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "ribhus"
        / "skills"
        / "bundled"
        / "company-research"
    )
    skill = load_skill(bundled)
    assert skill.matches("company brief for Paytm")
    assert skill.matches("MCA details for Infosys")
    assert not skill.matches("what is the weather in Goa")
