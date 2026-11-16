"""The image scan may ignore a finding only with a written reason, and the list must not grow silently."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TEXT = (ROOT / ".grype.yaml").read_text(encoding="utf-8")


def test_the_only_ignored_finding_is_the_python_one_with_no_published_fix_image():
    ignored = yaml.safe_load(TEXT)["ignore"]
    assert [i["vulnerability"] for i in ignored] == ["CVE-2026-119170"]
    assert ignored[0]["package"] == {"name": "python", "type": "binary"}          # narrow: this one package, not the CVE everywhere


def test_the_exception_says_why_and_when_to_remove_it():
    assert "python:3.14.11-slim" in TEXT and "REMOVE this entry" in TEXT and "project owner" in TEXT


def test_the_image_upgrades_its_os_packages_so_fixable_findings_are_cleared_not_ignored():
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "apt-get update && apt-get upgrade -y" in docker and "rm -rf /var/lib/apt/lists/*" in docker
