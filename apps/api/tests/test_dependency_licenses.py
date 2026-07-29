import importlib.util
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

from packaging.requirements import Requirement

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "dependency_licenses.py"
SPEC = importlib.util.spec_from_file_location("dependency_licenses", SCRIPT)
assert SPEC and SPEC.loader
dependency_licenses = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dependency_licenses)


def metadata(name: str, license_value: str, *requirements: str) -> Message:
    value = Message()
    value["Name"] = name
    value["License"] = license_value
    for requirement in requirements:
        value["Requires-Dist"] = requirement
    return value


def distribution(
    name: str, license_value: str = "MIT", *requirements: str
) -> SimpleNamespace:
    return SimpleNamespace(
        metadata=metadata(name, license_value, *requirements), version="1.0"
    )


def test_python_license_normalizes_known_values_and_uses_classifier_for_text() -> None:
    assert dependency_licenses.python_license(metadata("a", "Apache 2.0")) == (
        "Apache-2.0"
    )
    assert dependency_licenses.python_license(metadata("a", "The MIT License (MIT)")) == (
        "MIT"
    )
    long_license = metadata("a", "license paragraph\n" * 20)
    long_license["Classifier"] = "License :: OSI Approved :: BSD License"
    assert dependency_licenses.python_license(long_license) == "BSD-3-Clause"


def test_python_dependency_closure_excludes_unrelated_installed_packages() -> None:
    available = {
        "root": distribution(
            "root",
            "MIT",
            "child>=1",
            'optional-child>=1; extra == "standard"',
        ),
        "child": distribution("child"),
        "optional-child": distribution("optional-child"),
        "unrelated": distribution("unrelated", "Dual License"),
    }
    selected = dependency_licenses.python_dependency_names(
        [Requirement("root[standard]==1")], available
    )
    assert selected == {"root", "child", "optional-child"}


def test_requirement_roots_follows_nested_files(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("fastapi==1\n", encoding="utf-8")
    dev = tmp_path / "requirements-dev.txt"
    dev.write_text("-r requirements.txt\npytest==1\n", encoding="utf-8")
    assert [item.name for item in dependency_licenses.requirement_roots(dev)] == [
        "fastapi",
        "pytest",
    ]
