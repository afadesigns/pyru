"""PyRu's in-tree PEP 517 build backend.

Replaces maturin with a self-contained backend that only uses CPython's
standard library. It invokes ``cargo build --release`` to produce the native
extension (`native/Cargo.toml`, crate `_native`, cdylib), then assembles a
PEP 427 wheel or PEP 643 source distribution.

The wheel layout:

    pyru/__init__.py            (from sources)
    pyru/__main__.py
    pyru/cli.py
    pyru/_native.pyi
    pyru/py.typed
    pyru/_native.<ext>          (freshly compiled by cargo)
    pyru_scraper-<ver>.dist-info/METADATA
    pyru_scraper-<ver>.dist-info/WHEEL
    pyru_scraper-<ver>.dist-info/entry_points.txt
    pyru_scraper-<ver>.dist-info/licenses/LICENSE
    pyru_scraper-<ver>.dist-info/RECORD

Implemented hooks:

* `get_requires_for_build_wheel` / `_sdist` / `_editable` — PEP 517
* `prepare_metadata_for_build_wheel` / `_editable` — PEP 517 optional
* `build_wheel` — PEP 517 mandatory
* `build_sdist` — PEP 517 mandatory
* `build_editable` — PEP 660
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tomllib
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# ---------- Paths + config ---------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent

# Maximum Python version pyo3 0.28 exposes as an ABI3 feature. The wheel is
# forward-compatible with any CPython >= this floor; the distribution's
# `requires-python` gate (read from pyproject.toml) narrows installs further.
_ABI3_MIN_TAG = "cp313"


def _pyproject() -> dict[str, Any]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))


def _project(cfg: dict[str, Any]) -> dict[str, Any]:
    return cfg["project"]


def _dist_name(cfg: dict[str, Any]) -> str:
    return _project(cfg)["name"]


def _version(cfg: dict[str, Any]) -> str:
    return _project(cfg)["version"]


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _wheel_safe(name: str) -> str:
    return _normalize(name).replace("-", "_")


# ---------- Cargo invocation -------------------------------------------------


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _cargo_build(profile: str = "release") -> Path:
    if _which("cargo") is None:
        msg = (
            "`cargo` not found on PATH. PyRu's native extension is compiled by "
            "the Rust toolchain during wheel building — install rustup or run "
            "the build from an environment that already has cargo available."
        )
        raise RuntimeError(msg)

    manifest = ROOT / "native" / "Cargo.toml"
    env = os.environ.copy()
    # Lean on pyo3's ABI3 stable contract so we do not need a live interpreter
    # resolved beyond the one running this backend.
    env.setdefault("PYO3_USE_ABI3_FORWARD_COMPATIBILITY", "1")

    cmd = [
        "cargo",
        "build",
        "--manifest-path",
        str(manifest),
        "--features",
        "extension-module",
    ]
    if profile == "release":
        cmd.append("--release")
    subprocess.run(cmd, check=True, cwd=str(ROOT), env=env)

    target_dir = ROOT / "native" / "target" / profile
    candidates = (
        target_dir / "lib_native.so",  # Linux
        target_dir / "lib_native.dylib",  # macOS
        target_dir / "_native.dll",  # Windows
    )
    for c in candidates:
        if c.is_file():
            return c
    msg = (
        f"cargo build succeeded but no artefact matched in {target_dir}; "
        f"looked for: {', '.join(str(c.relative_to(ROOT)) for c in candidates)}"
    )
    raise FileNotFoundError(msg)


def _installed_ext_name() -> str:
    return "_native.pyd" if sys.platform == "win32" else "_native.so"


# ---------- Tag computation --------------------------------------------------


def _python_tag() -> str:
    return _ABI3_MIN_TAG


def _abi_tag() -> str:
    return "abi3"


def _platform_tag() -> str:
    raw = sysconfig.get_platform()  # e.g. "linux-x86_64"
    return re.sub(r"[^A-Za-z0-9]", "_", raw)


def _tag_triple() -> tuple[str, str, str]:
    return _python_tag(), _abi_tag(), _platform_tag()


# ---------- Metadata rendering ----------------------------------------------


def _author_email_field(project: dict[str, Any]) -> str:
    parts: list[str] = []
    for a in project.get("authors", []):
        name = a.get("name", "").strip()
        email = a.get("email", "").strip()
        if name and email:
            parts.append(f"{name} <{email}>")
        elif email:
            parts.append(email)
        elif name:
            parts.append(name)
    return ", ".join(parts)


def _metadata(cfg: dict[str, Any]) -> str:
    project = _project(cfg)
    name = project["name"]
    version = project["version"]

    lines: list[str] = [
        "Metadata-Version: 2.3",
        f"Name: {name}",
        f"Version: {version}",
    ]
    if "description" in project:
        lines.append(f"Summary: {project['description']}")
    authors = _author_email_field(project)
    if authors:
        lines.append(f"Author-email: {authors}")

    license_info = project.get("license")
    if isinstance(license_info, dict) and "file" in license_info:
        lines.append("License-File: LICENSE")
    elif isinstance(license_info, str):
        lines.append(f"License: {license_info}")

    for classifier in project.get("classifiers", []):
        lines.append(f"Classifier: {classifier}")
    for label, url in (project.get("urls") or {}).items():
        lines.append(f"Project-URL: {label}, {url}")

    requires = project.get("requires-python")
    if requires:
        lines.append(f"Requires-Python: {requires}")

    for dep in project.get("dependencies") or []:
        lines.append(f"Requires-Dist: {dep}")

    readme = project.get("readme")
    readme_path: Path | None = None
    content_type = "text/markdown"
    if isinstance(readme, str):
        readme_path = ROOT / readme
        if readme.endswith(".rst"):
            content_type = "text/x-rst"
    elif isinstance(readme, dict):
        readme_path = ROOT / readme.get("file", "README.md")
        content_type = readme.get("content-type", "text/markdown")

    description = ""
    if readme_path and readme_path.exists():
        description = readme_path.read_text("utf-8")

    lines.append(f"Description-Content-Type: {content_type}")
    return "\n".join(lines) + "\n\n" + description


def _wheel_file(tags: tuple[str, str, str]) -> str:
    py_tag, abi, plat = tags
    return (
        "Wheel-Version: 1.0\n"
        "Generator: pyru-build 1.0\n"
        "Root-Is-Purelib: false\n"
        f"Tag: {py_tag}-{abi}-{plat}\n"
    )


def _entry_points(cfg: dict[str, Any]) -> str:
    scripts = _project(cfg).get("scripts") or {}
    if not scripts:
        return ""
    body = "[console_scripts]\n"
    for cmd, target in sorted(scripts.items()):
        body += f"{cmd} = {target}\n"
    return body


# ---------- Wheel writer -----------------------------------------------------


def _digest(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def _zipinfo(arcname: str, *, mode: int = 0o644) -> ZipInfo:
    zi = ZipInfo(arcname)
    zi.compress_type = ZIP_DEFLATED
    zi.external_attr = (0o100000 | mode) << 16
    zi.date_time = (1980, 1, 1, 0, 0, 0)  # reproducible timestamps
    return zi


def _add_bytes(
    zf: ZipFile,
    records: list[tuple[str, str, int]],
    arcname: str,
    data: bytes,
    *,
    mode: int = 0o644,
) -> None:
    zf.writestr(_zipinfo(arcname, mode=mode), data)
    records.append((arcname, _digest(data), len(data)))


def _add_file(
    zf: ZipFile,
    records: list[tuple[str, str, int]],
    arcname: str,
    path: Path,
    *,
    mode: int = 0o644,
) -> None:
    _add_bytes(zf, records, arcname, path.read_bytes(), mode=mode)


def _write_record(
    zf: ZipFile,
    records: list[tuple[str, str, int]],
    dist_info: str,
) -> None:
    lines = [f"{path},{digest},{size}" for path, digest, size in records]
    lines.append(f"{dist_info}/RECORD,,")
    body = "\n".join(lines) + "\n"
    zf.writestr(_zipinfo(f"{dist_info}/RECORD"), body)


def _copy_python_package(
    zf: ZipFile,
    records: list[tuple[str, str, int]],
    pkg_dir: Path,
) -> None:
    for p in sorted(pkg_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix == ".pyc":
            continue
        if p.suffix in {".so", ".dylib", ".pyd"}:
            continue  # rebuilt freshly below
        if "__pycache__" in p.parts:
            continue
        arcname = p.relative_to(ROOT).as_posix()
        _add_file(zf, records, arcname, p)


def _emit_dist_info(
    zf: ZipFile,
    records: list[tuple[str, str, int]],
    cfg: dict[str, Any],
    tags: tuple[str, str, str],
    dist_info: str,
) -> None:
    _add_bytes(zf, records, f"{dist_info}/METADATA", _metadata(cfg).encode("utf-8"))
    _add_bytes(zf, records, f"{dist_info}/WHEEL", _wheel_file(tags).encode("utf-8"))
    entries = _entry_points(cfg)
    if entries:
        _add_bytes(zf, records, f"{dist_info}/entry_points.txt", entries.encode("utf-8"))
    license_path = ROOT / "LICENSE"
    if license_path.exists():
        _add_file(zf, records, f"{dist_info}/licenses/LICENSE", license_path)


# ---------- PEP 517 / 660 hooks ---------------------------------------------


def get_requires_for_build_wheel(config_settings: dict | None = None) -> list[str]:
    del config_settings
    return []


def get_requires_for_build_sdist(config_settings: dict | None = None) -> list[str]:
    del config_settings
    return []


def get_requires_for_build_editable(config_settings: dict | None = None) -> list[str]:
    del config_settings
    return []


def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings: dict | None = None,
) -> str:
    del config_settings
    cfg = _pyproject()
    name = _wheel_safe(_dist_name(cfg))
    version = _version(cfg)
    dist_info = f"{name}-{version}.dist-info"
    target = Path(metadata_directory) / dist_info
    target.mkdir(parents=True, exist_ok=True)
    (target / "METADATA").write_text(_metadata(cfg), encoding="utf-8")
    (target / "WHEEL").write_text(_wheel_file(_tag_triple()), encoding="utf-8")
    entries = _entry_points(cfg)
    if entries:
        (target / "entry_points.txt").write_text(entries, encoding="utf-8")
    license_path = ROOT / "LICENSE"
    if license_path.exists():
        licenses_dir = target / "licenses"
        licenses_dir.mkdir(exist_ok=True)
        shutil.copy2(license_path, licenses_dir / "LICENSE")
    return dist_info


def prepare_metadata_for_build_editable(
    metadata_directory: str,
    config_settings: dict | None = None,
) -> str:
    return prepare_metadata_for_build_wheel(metadata_directory, config_settings)


def build_wheel(
    wheel_directory: str,
    config_settings: dict | None = None,
    metadata_directory: str | None = None,
) -> str:
    del config_settings, metadata_directory
    cfg = _pyproject()
    name = _wheel_safe(_dist_name(cfg))
    version = _version(cfg)
    tags = _tag_triple()
    dist_info = f"{name}-{version}.dist-info"
    wheel_path = Path(wheel_directory) / f"{name}-{version}-{'-'.join(tags)}.whl"

    native_artefact = _cargo_build(profile="release")

    records: list[tuple[str, str, int]] = []
    with ZipFile(wheel_path, "w", ZIP_DEFLATED) as zf:
        _copy_python_package(zf, records, ROOT / "pyru")
        _add_file(zf, records, f"pyru/{_installed_ext_name()}", native_artefact, mode=0o755)
        _emit_dist_info(zf, records, cfg, tags, dist_info)
        _write_record(zf, records, dist_info)
    return wheel_path.name


def build_editable(
    wheel_directory: str,
    config_settings: dict | None = None,
    metadata_directory: str | None = None,
) -> str:
    """PEP 660 editable install.

    Build the native extension in-tree (`pyru/_native.<ext>`) and emit a tiny
    wheel that just drops a `.pth` file into site-packages, pointing `import
    pyru` at the source tree.
    """
    del config_settings, metadata_directory
    cfg = _pyproject()
    name = _wheel_safe(_dist_name(cfg))
    version = _version(cfg)
    tags = _tag_triple()
    dist_info = f"{name}-{version}.dist-info"
    wheel_path = Path(wheel_directory) / f"{name}-{version}-{'-'.join(tags)}.whl"

    native_artefact = _cargo_build(profile="release")
    in_tree = ROOT / "pyru" / _installed_ext_name()
    shutil.copy2(native_artefact, in_tree)

    pth_body = f"{ROOT}\n"

    records: list[tuple[str, str, int]] = []
    with ZipFile(wheel_path, "w", ZIP_DEFLATED) as zf:
        _add_bytes(zf, records, f"_{name}_editable.pth", pth_body.encode("utf-8"))
        _emit_dist_info(zf, records, cfg, tags, dist_info)
        _write_record(zf, records, dist_info)
    return wheel_path.name


# ---------- Source distribution ---------------------------------------------


_SDIST_INCLUDE: tuple[str, ...] = (
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "pyru",
    "native",
    "_build",
    "tests",
    "benchmarks",
)
_SDIST_EXCLUDE_SUFFIX = (".pyc", ".so", ".dylib", ".pyd", ".dll")
_SDIST_EXCLUDE_DIRS = frozenset({
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".ty_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "target",
})


def _sdist_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    parts = Path(tarinfo.name).parts
    if _SDIST_EXCLUDE_DIRS.intersection(parts):
        return None
    if tarinfo.name.endswith(_SDIST_EXCLUDE_SUFFIX):
        return None
    tarinfo.uid = tarinfo.gid = 0
    tarinfo.uname = tarinfo.gname = ""
    tarinfo.mtime = 0
    return tarinfo


def build_sdist(sdist_directory: str, config_settings: dict | None = None) -> str:
    del config_settings
    cfg = _pyproject()
    name = _normalize(_dist_name(cfg))
    version = _version(cfg)
    sdist_name = f"{name}-{version}.tar.gz"
    prefix = f"{name}-{version}"

    sdist_path = Path(sdist_directory) / sdist_name
    with tarfile.open(sdist_path, "w:gz") as tar:
        for entry in _SDIST_INCLUDE:
            source = ROOT / entry
            if not source.exists():
                continue
            tar.add(source, arcname=f"{prefix}/{entry}", filter=_sdist_filter)
    return sdist_name
