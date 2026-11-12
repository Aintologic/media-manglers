"""The FFmpeg Media Manglers bundles: its complete Corresponding Source, and a mirror of the file it came from
(installer plan, Stage 5). Built on the operator's PC from the pin list; never published from here.

    python ffmpeg_source_bundle.py build --out DIR --ci-cache ZIP [--pins JSON]
    python ffmpeg_source_bundle.py mirror --out DIR --from ZIP [--lock JSON]

``build`` gathers, into ``DIR\\source``:

- ``ffmpeg\\``         FFmpeg itself at the pinned commit (a git archive of that exact tree);
- ``ffmpeg-builds\\``  the FFmpeg-Builds scripts at the release's own commit: the scripts that controlled
                      compilation, its patches and the toolchain recipe;
- ``dependencies\\``   every dependency stage's source exactly as the build fetched it, from the build's own CI
                      download cache (the archive GitHub kept for that run, checked against its published digest);
- ``extra\\``          what the build fetched outside that cache (FreeType's dlg, rav1e's Rust crates);
- ``toolchain\\``      the sources of the toolchain parts linked into the binaries (GCC's runtime libraries,
                      mingw-w64, the crosstool-NG patches, the Rust standard library);
- ``README-SOURCE.txt``, ``MANIFEST.json`` (every file, where it came from, its revision, SHA-256 and licence) and
  ``SHA256SUMS.txt``.

The folder is then packed into ZIP parts of at most 1.9 GB each (a release asset may not exceed 2 GB), with their
own ``SHA256SUMS.txt``. A git source is fetched by its commit and checked by git itself; a file pinned by a checksum
is checked against it; anything else records its SHA-256 in the manifest. Downloads go through the app's one shared
downloader's connection, so Windows checks every certificate.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tomllib
from typing import Any
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from media_manglers.core import downloads  # noqa: E402

PINS = Path(__file__).with_name("ffmpeg-source-pins.json")
LOCK = Path(__file__).with_name("components.lock.json")
PART_LIMIT = 1_900_000_000
CRATES = "https://static.crates.io/crates/{name}/{name}-{version}.crate"


def _hash(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fetch(url: str, target: Path, *, sha256: str = "", sha512: str = "") -> Path:
    """``url`` to ``target`` through a ``.partial`` file, checked against whichever checksum is pinned."""

    if sha256:
        return downloads.download_file(url, target, sha256, replace=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + downloads.PARTIAL_SUFFIX)
    with downloads.open_url(url) as response, open(partial, "wb") as handle:
        shutil.copyfileobj(response, handle, 4 * 1024 * 1024)
    if sha512 and _hash(partial, "sha512") != sha512.casefold():
        partial.unlink()
        raise SystemExit(f"{target.name} did not match its pinned SHA-512; nothing was kept.")
    os.replace(partial, target)
    return target


def _read_url(url: str) -> bytes:
    with downloads.open_url(url) as response:
        return response.read()


def git_archive(repo: str, commit: str, target: Path, prefix: str, work: Path) -> Path:
    """The tree of ``commit`` as a .tar.gz, fetched by its commit id: git checks every object against it."""

    clone = work / ("git-" + hashlib.sha256(f"{repo}@{commit}".encode()).hexdigest()[:12])
    if clone.exists():
        shutil.rmtree(clone)
    clone.mkdir(parents=True)

    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(clone), *args], check=True, capture_output=True, text=True).stdout

    git("init", "-q")
    git("-c", "protocol.version=2", "fetch", "-q", "--depth", "1", repo, commit)
    found = git("rev-parse", "FETCH_HEAD^{commit}").strip()
    if found != commit:
        raise SystemExit(f"{repo} gave {found}, not the pinned {commit}.")
    target.parent.mkdir(parents=True, exist_ok=True)
    git("archive", "--format=tar.gz", f"--prefix={prefix}/", "-o", str(target), "FETCH_HEAD")
    shutil.rmtree(clone, ignore_errors=True)
    return target


def _record(manifest: list[dict[str, Any]], source: Path, path: Path, **fields: Any) -> None:
    manifest.append({"file": path.relative_to(source).as_posix(), "bytes": path.stat().st_size,
                     "sha256": _hash(path), **fields})


def _stem(stage: str) -> str:
    return stage.rsplit("/", 1)[-1].removesuffix(".sh")


def _unpack_ci_cache(ci_cache: Path, pins: dict[str, Any], folder: Path, manifest: list[dict[str, Any]],
                     source: Path) -> dict[str, Any]:
    """Take each enabled stage's source archive out of the build's CI download cache (one ``cache.tar.gz``, checked
    against the digest GitHub published). The cache serves every build variant; stages this build did not use are
    left out and listed. Returns which stages came from the cache, and which were not in it."""

    pinned = pins["ci_download_cache"]
    found = _hash(ci_cache)
    if found != pinned["sha256"]:
        raise SystemExit(f"The CI download cache does not match its published digest ({found}).")
    wanted = {_stem(item["stage"]): item for item in pins["dependencies"] if item["kind"] != "meta"}
    folder.mkdir(parents=True, exist_ok=True)
    links: dict[str, str] = {}
    candidates: dict[str, list[str]] = {}
    left_out: set[str] = set()
    with zipfile.ZipFile(ci_cache) as archive, archive.open("cache.tar.gz") as raw, \
            tarfile.open(fileobj=raw, mode="r|gz") as tar:
        for member in tar:
            name = Path(member.name).name
            if member.issym() or member.islnk():
                links[name.removesuffix(".tar.xz")] = Path(member.linkname).name
                continue
            if not member.isfile():
                continue
            stem = name.split("_", 1)[0]
            if stem not in wanted:
                left_out.add(stem)
                continue
            reader = tar.extractfile(member)
            with reader, open(folder / name, "wb") as writer:
                shutil.copyfileobj(reader, writer, 4 * 1024 * 1024)
            candidates.setdefault(stem, []).append(name)
    used: dict[str, str] = {}
    for stem, names in candidates.items():
        chosen = links.get(stem) if links.get(stem) in names else (names[0] if len(names) == 1 else "")
        if not chosen:
            raise SystemExit(f"The CI cache holds several archives for {stem} and does not say which was used.")
        for name in names:
            if name != chosen:
                (folder / name).unlink()
        item = wanted[stem]
        used[stem] = chosen
        _record(manifest, source, folder / chosen, origin=f"FFmpeg-Builds CI run {pinned['run']}, artifact "
                f"{pinned['artifact']} ({pinned['name']}); upstream {item.get('repo', '')}",
                revision=item.get("commit") or item.get("revision", ""), licence=item.get("licence", ""),
                what=item["stage"])
    missing = sorted(set(wanted) - set(used))
    return {"from_cache": len(used), "missing_from_cache": missing, "left_out": sorted(left_out)}


def _rav1e_crates(item: dict[str, Any], folder: Path, manifest: list[dict[str, Any]], source: Path) -> int:
    lock_text = _read_url(item["cargo_lock"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Cargo.lock").write_bytes(lock_text)
    _record(manifest, source, folder / "Cargo.lock", origin=item["cargo_lock"], what="rav1e's crate list")
    count = 0
    for package in tomllib.loads(lock_text.decode("utf-8")).get("package", []):
        checksum = package.get("checksum")
        if not checksum or "crates.io" not in str(package.get("source", "")):
            continue
        name, version = package["name"], package["version"]
        target = folder / f"{name}-{version}.crate"
        _fetch(CRATES.format(name=name, version=version), target, sha256=checksum)
        _record(manifest, source, target, origin="crates.io", revision=version, what=f"Rust crate {name}")
        count += 1
    return count


README = """FFmpeg {describe}, win64 gpl-shared, release {release}: the complete Corresponding Source

This is the source of the FFmpeg programs and libraries that Media Manglers ships in runtime\\ffmpeg\\bin, taken
unchanged from the FFmpeg-Builds file {binary} (SHA-256 {binary_sha256}).

What is here
- ffmpeg\\           FFmpeg at commit {ffmpeg_commit} ({branch}). No patches are applied to FFmpeg itself.
- ffmpeg-builds\\    FFmpeg-Builds at commit {builds_commit}: build.sh, generate.sh, download.sh, util\\, scripts.d\\,
                    patches\\, variants\\, addins\\ and images\\ (the toolchain recipe). These are the scripts used to
                    control compilation and installation; TARGET=win64, VARIANT=gpl-shared, ADDINS=8.1.
- dependencies\\     every dependency stage's source exactly as that build fetched it, from the build's own CI
                    download cache (run {run}).
- extra\\            what the build fetched outside that cache: FreeType's dlg submodule and rav1e's Rust crates.
- toolchain\\        the parts of the toolchain linked into the binaries: GCC 16.2.0 (libgcc, libstdc++, libgomp),
                    mingw-w64, the crosstool-NG patches, and the Rust standard library of rustc 1.99.1.
- MANIFEST.json     every file: where it came from, its revision, its SHA-256 and its licence.
- SHA256SUMS.txt    the SHA-256 of every file.

To rebuild: check out ffmpeg-builds at the commit above and run its build with TARGET=win64, VARIANT=gpl-shared and
ADDINS=8.1, giving it these sources. The container images the original build used no longer exist, so fresh images
are built from the recipe in ffmpeg-builds\\images.

Licence: the build as a whole is GNU GPL version 3 or later. Each component's own licence file is inside its source.

Known problems, as found when this bundle was made:
{problems}
"""


def build_bundle(out: Path, *, ci_cache: Path | None, pins_file: Path = PINS) -> dict[str, Any]:
    """Gather the complete source into ``out\\source`` and pack it into ZIP parts in ``out\\parts``."""

    pins = json.loads(Path(pins_file).read_text(encoding="utf-8"))
    out = Path(out).resolve()
    source, work = out / "source", out / "work"
    for folder in (source, out / "parts"):
        if folder.exists():
            shutil.rmtree(folder)
    source.mkdir(parents=True)
    work.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    ffmpeg, builds = pins["ffmpeg"], pins["builds"]
    target = git_archive(ffmpeg["repo"], ffmpeg["commit"], source / "ffmpeg" / f"ffmpeg-{ffmpeg['describe']}.tar.gz",
                         f"ffmpeg-{ffmpeg['describe']}", work)
    _record(manifest, source, target, origin=ffmpeg["repo"], revision=ffmpeg["commit"], licence=ffmpeg["licence"],
            what="FFmpeg")
    target = git_archive(builds["repo"], builds["commit"], source / "ffmpeg-builds" /
                         f"FFmpeg-Builds-{builds['commit'][:12]}.tar.gz", f"FFmpeg-Builds-{builds['commit'][:12]}", work)
    _record(manifest, source, target, origin=builds["repo"], revision=builds["commit"], licence=builds["licence"],
            what="the FFmpeg-Builds scripts")
    # Only the build's own CI download cache holds every dependency stage complete: a stage's download step also
    # fetches submodules, second repositories, vendored crates and data files that a single commit does not name.
    # So the bundle is made from it or not at all, never from a partial re-fetch labelled complete.
    if ci_cache is None:
        raise SystemExit("The complete source needs the build's own CI download cache (--ci-cache); without it the "
                         "dependency stages would be incomplete. Nothing was built.")
    cache = _unpack_ci_cache(Path(ci_cache), pins, source / "dependencies", manifest, source)
    if cache["missing_from_cache"]:
        raise SystemExit("The CI download cache lacks these stages, so the source would not be complete: "
                         + ", ".join(cache["missing_from_cache"]) + ". Nothing was built.")
    fetched: list[str] = []
    crates = 0
    for item in pins["fetched_during_the_build"]:
        if "commit" in item:
            name = item["repo"].rstrip("/").split("/")[-1].removesuffix(".git")
            target = git_archive(item["repo"], item["commit"], source / "extra" / f"{name}.tar.gz", name, work)
            _record(manifest, source, target, origin=item["repo"], revision=item["commit"], licence=item["licence"],
                    what=item["what"])
        else:
            crates = _rav1e_crates(item, source / "extra" / "rav1e-crates", manifest, source)
    for item in pins["toolchain"]:
        if "commit" in item:
            name = item["repo"].rstrip("/").split("/")[-1].removesuffix(".git")
            target = git_archive(item["repo"], item["commit"], source / "toolchain" / f"{name}-{item['commit'][:12]}.tar.gz",
                                 f"{name}-{item['commit'][:12]}", work)
        else:
            sha256 = _read_url(item["sha256_url"]).decode("ascii").split()[0] if "sha256_url" in item else ""
            target = _fetch(item["url"], source / "toolchain" / item["url"].rsplit("/", 1)[-1], sha256=sha256,
                            sha512=item.get("sha512", ""))
        _record(manifest, source, target, origin=item.get("repo") or item["url"], revision=item.get("commit", ""),
                licence=item["licence"], what=item["what"])
    problems = "\n".join(f"- {line}" for line in pins["known_problems"])
    readme = README.format(describe=ffmpeg["describe"], release=pins["binary"]["release"], binary=pins["binary"]["file"],
                           binary_sha256=pins["binary"]["sha256"], ffmpeg_commit=ffmpeg["commit"],
                           branch=ffmpeg["branch"], builds_commit=builds["commit"],
                           run=pins["ci_download_cache"]["run"], problems=problems)
    (source / "README-SOURCE.txt").write_text(readme.replace("\n", "\r\n"), encoding="utf-8", newline="")
    made = {"made_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "binary": pins["binary"],
            "ffmpeg": ffmpeg, "builds": builds, "stages_from_ci_cache": cache["from_cache"],
            "stages_fetched_by_commit": fetched, "ci_cache_stages_left_out_as_unused_by_this_build": cache["left_out"],
            "files": manifest}
    (source / "MANIFEST.json").write_text(json.dumps(made, indent=2) + "\n", encoding="utf-8")
    sums = [f"{item['sha256']}  {item['file']}" for item in manifest]
    for extra in ("README-SOURCE.txt", "MANIFEST.json"):
        sums.append(f"{_hash(source / extra)}  {extra}")
    (source / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    parts = pack_parts(source, out / "parts", f"ffmpeg-{ffmpeg['describe']}-win64-gpl-shared-8.1-source")
    shutil.rmtree(work, ignore_errors=True)
    total = sum(path.stat().st_size for path in source.rglob("*") if path.is_file())
    return {"source": str(source), "files": len(manifest) + 3, "bytes": total, "crates": crates,
            "stages_from_ci_cache": cache["from_cache"], "stages_fetched_by_commit": fetched,
            "left_out": cache["left_out"],
            "parts": [{"file": part.name, "bytes": part.stat().st_size, "sha256": _hash(part)} for part in parts]}


def pack_parts(source: Path, folder: Path, stem: str) -> list[Path]:
    """Store the source folder's files in ZIP parts of at most ``PART_LIMIT`` bytes (no file is split)."""

    folder.mkdir(parents=True, exist_ok=True)
    files = sorted((path for path in source.rglob("*") if path.is_file()), key=lambda path: path.as_posix())
    groups: list[list[Path]] = [[]]
    size = 0
    for path in files:
        length = path.stat().st_size
        if groups[-1] and size + length > PART_LIMIT:
            groups.append([])
            size = 0
        groups[-1].append(path)
        size += length
    parts: list[Path] = []
    for number, group in enumerate(groups, start=1):
        part = folder / f"{stem}-part{number}-of-{len(groups)}.zip"
        with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for path in group:
                archive.write(path, f"{stem}/{path.relative_to(source).as_posix()}")
        parts.append(part)
    (folder / "SHA256SUMS.txt").write_text("".join(f"{_hash(part)}  {part.name}\n" for part in parts),
                                           encoding="utf-8")
    return parts


def mirror(out: Path, source_zip: Path, *, lock_file: Path = LOCK) -> dict[str, Any]:
    """An unchanged copy of the pinned FFmpeg file, checked against its pin, with its SHA256SUMS."""

    part = json.loads(Path(lock_file).read_text(encoding="utf-8"))["components"]["ffmpeg"]
    if _hash(Path(source_zip)) != part["sha256"]:
        raise SystemExit(f"{source_zip} is not the pinned FFmpeg file.")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / part["file"]
    shutil.copyfile(source_zip, target.with_name(target.name + ".partial"))
    if _hash(target.with_name(target.name + ".partial")) != part["sha256"]:
        raise SystemExit("The mirror copy did not match its pin.")
    os.replace(target.with_name(target.name + ".partial"), target)
    (out / "SHA256SUMS.txt").write_text(f"{part['sha256']}  {part['file']}\n", encoding="utf-8")
    return {"file": str(target), "bytes": target.stat().st_size, "sha256": part["sha256"], "url": part["url"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--out", required=True)
    build.add_argument("--ci-cache", required=True)
    build.add_argument("--pins", default=str(PINS))
    copy = commands.add_parser("mirror")
    copy.add_argument("--out", required=True)
    copy.add_argument("--from", dest="source", required=True)
    copy.add_argument("--lock", default=str(LOCK))
    args = parser.parse_args(argv)
    if args.command == "build":
        result = build_bundle(Path(args.out), ci_cache=Path(args.ci_cache) if args.ci_cache else None,
                              pins_file=Path(args.pins))
    else:
        result = mirror(Path(args.out), Path(args.source), lock_file=Path(args.lock))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
