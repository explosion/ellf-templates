"""Run Neo4j inside the service pod.

Recipe images only bring Python packages, and Neo4j is a Java server, so the service
downloads a Java runtime and Neo4j Community the first time it starts. The downloads are
kept on the cluster's shared storage and checked against pinned checksums, so later
starts skip the download.

The database itself lives on the pod's own disk, because Neo4j doesn't support network
file systems for its data. It's rebuilt from the input assets on every start, which takes
seconds for a graph this size and keeps the assets the only copy of the data.

Neo4j only listens on 127.0.0.1, so nothing outside the pod can reach it. The service's
own web app is the only way in.
"""

import hashlib
import os
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

NEO4J_VERSION = "5.26.32"
NEO4J_URL = f"https://dist.neo4j.org/neo4j-community-{NEO4J_VERSION}-unix.tar.gz"
NEO4J_SHA256 = "d279ae6a9b38034280681a558b0cd222dce89f87cc3d9867f1f7bd28ef5ebc30"
JAVA_URL = (
    "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13%2B9/"
    "OpenJDK21U-jre_x64_linux_hotspot_21.0.13_9.tar.gz"
)
JAVA_SHA256 = "a535a1df9c6284d9618872984e026ae0352d1f7e9e0605425c0e6114f47351dd"

#: The environment variable the broker sets on every recipe pod for the shared volume.
NFS_ENV_VAR = "ELLF_BUILTIN_PATH_NFS"
HTTP_PORT = 7474
BOLT_PORT = 7687

Report = Callable[[str], None]


@dataclass
class Running:
    url: str
    user: str
    password: str
    process: subprocess.Popen


def cache_dir() -> Path:
    nfs = os.environ.get(NFS_ENV_VAR)
    root = Path(nfs) / "kg_recipes" / "downloads" if nfs else Path.home() / ".cache" / "kg_recipes"
    root.mkdir(parents=True, exist_ok=True)
    return root


def fetch(url: str, sha256: str, target: Path, report: Report) -> Path:
    """Download ``url`` to ``target`` unless a file with the right checksum is already there."""
    if target.exists() and _sha256(target) == sha256:
        return target
    report(f"Downloading {target.name}")
    # Another service may be downloading the same file, so each writes its own part file
    # and the finished file is moved into place in one step.
    part = target.with_name(f"{target.name}.{secrets.token_hex(4)}.part")
    try:
        with urllib.request.urlopen(url, timeout=120) as resp, part.open("wb") as f:
            shutil.copyfileobj(resp, f, length=1 << 20)
        actual = _sha256(part)
        if actual != sha256:
            raise RuntimeError(f"Checksum mismatch for {url}: expected {sha256}, got {actual}")
        part.replace(target)
    finally:
        part.unlink(missing_ok=True)
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def extract(archive: Path, dest: Path) -> Path:
    """Unpack ``archive`` into ``dest`` and return the single top-level folder it contains."""
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        # The "data" filter refuses absolute paths and links that point outside dest. It
        # keeps the owner's executable bits, which Java and Neo4j need.
        tar.extractall(dest, filter="data")
    (top,) = [p for p in dest.iterdir() if p.is_dir()]
    return top


def write_config(conf_dir: Path, run_dir: Path) -> None:
    """Write a neo4j.conf for a small, local-only, single-database server."""
    conf_dir.mkdir(parents=True, exist_ok=True)
    settings = {
        "server.default_listen_address": "127.0.0.1",
        "server.http.listen_address": f"127.0.0.1:{HTTP_PORT}",
        "server.bolt.listen_address": f"127.0.0.1:{BOLT_PORT}",
        "server.https.enabled": "false",
        "server.directories.data": str(run_dir / "data"),
        "server.directories.logs": str(run_dir / "logs"),
        "server.directories.run": str(run_dir / "run"),
        "server.directories.import": str(run_dir / "import"),
        "server.directories.plugins": str(run_dir / "plugins"),
        # 1,500 passages and a few thousand links fit in far less than this.
        "server.memory.heap.initial_size": "512m",
        "server.memory.heap.max_size": "512m",
        "server.memory.pagecache.size": "128m",
        "db.transaction.timeout": "30s",
        "dbms.usage_report.enabled": "false",
        # Queries typed into the page may use LOAD CSV, which can read files and URLs.
        # Block local files and every private network, so it can't read the pod or
        # reach other services on the cluster.
        "dbms.security.allow_csv_import_from_file_urls": "false",
        "internal.dbms.cypher_ip_blocklist": ",".join([
            "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
            "172.16.0.0/12", "192.168.0.0/16", "::1/128", "::ffff:0:0/96", "fc00::/7", "fe80::/10",
        ]),
    }
    text = "".join(f"{k}={v}\n" for k, v in settings.items())
    (conf_dir / "neo4j.conf").write_text(text, encoding="utf-8")


def start(report: Report, workdir: Optional[Path] = None) -> Running:
    """Download what's missing, start Neo4j and wait until it answers."""
    cache = cache_dir()
    java_archive = fetch(JAVA_URL, JAVA_SHA256, cache / f"jre-{JAVA_SHA256[:12]}.tar.gz", report)
    neo4j_archive = fetch(NEO4J_URL, NEO4J_SHA256, cache / f"neo4j-community-{NEO4J_VERSION}.tar.gz", report)

    root = workdir or Path(tempfile.mkdtemp(prefix="kg-graph-"))
    report("Unpacking Java and Neo4j")
    java_home = extract(java_archive, root / "java")
    neo4j_home = extract(neo4j_archive, root / "neo4j")
    run_dir = root / "db"
    conf_dir = root / "conf"
    write_config(conf_dir, run_dir)

    env = dict(os.environ, JAVA_HOME=str(java_home), NEO4J_HOME=str(neo4j_home), NEO4J_CONF=str(conf_dir))
    env["PATH"] = f"{java_home / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    password = secrets.token_urlsafe(24)
    report("Setting up the database")
    setup = subprocess.run(
        [str(neo4j_home / "bin" / "neo4j-admin"), "dbms", "set-initial-password", password],
        env=env, capture_output=True, text=True,
    )
    if setup.returncode != 0:
        # The command line holds the password, so the error only carries Neo4j's output.
        raise RuntimeError(f"Couldn't set up the database:\n{(setup.stdout + setup.stderr)[-2000:]}")
    report("Starting Neo4j")
    log = (root / "neo4j-console.log").open("ab")
    process = subprocess.Popen(
        [str(neo4j_home / "bin" / "neo4j"), "console"], env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{HTTP_PORT}"
    wait_until_up(url, process, root / "neo4j-console.log")
    return Running(url=url, user="neo4j", password=password, process=process)


def wait_until_up(url: str, process: subprocess.Popen, log_path: Path, timeout: float = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            raise RuntimeError(f"Neo4j stopped with exit code {process.returncode}:\n{tail}")
        try:
            with urllib.request.urlopen(url, timeout=5):
                return
        except OSError:
            time.sleep(1)
    raise RuntimeError(f"Neo4j didn't answer on {url} within {timeout:.0f} seconds")
