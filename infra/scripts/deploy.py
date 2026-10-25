# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3>=1.40"]
# ///
"""Release a commit of Jackdaw Arena: the API image to both Lambda functions, the web build to
S3. Terraform isn't involved; it only creates what this updates.

    uv run infra/scripts/deploy.py              # release HEAD (the worktree must be clean)
    uv run infra/scripts/deploy.py --rollback   # point the API back at the previous version

Every step is safe to rerun, and nothing visitors see changes until step 5:
  1. image  build api/ for linux/amd64, tagged with the commit, and push it (skipped when ECR
            already has that tag)
  2. web    pnpm build
  3. tasks  point arena-tasks at the image and run the migrations (expand/contract: the live
            version keeps working with the new schema). When the jackdaw release changes,
            replay the season's ended episodes with it (the audit): if any ends differently,
            arena-tasks goes back to its previous image and the release stops
  4. api    point arena-api at the image, publish a version, health-check that version against
            the database
  5. live   move the "live" alias (behind the Function URL) to the new version
  6. site   upload web/dist: hashed assets first (immutable), then index.html (no-cache), and
            invalidate the unhashed files
  7. smoke  check the site serves the new build through CloudFront; if not, move "live" back

Configuration: the environment, with the names of Terraform's github_variables output (that's
how GitHub Actions passes them), falling back to `terraform output` for any that are unset:
  AWS_REGION ECR_REPOSITORY API_FUNCTION TASKS_FUNCTION WEB_BUCKET DISTRIBUTION_ID SITE_URL
AWS credentials come from the usual chain: AWS_PROFILE (SSO) locally, OIDC in Actions.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[2]
KEYS = (
    "AWS_REGION", "ECR_REPOSITORY", "API_FUNCTION", "TASKS_FUNCTION", "WEB_BUCKET",
    "DISTRIBUTION_ID", "SITE_URL",
)  # fmt: skip
ALIAS = "live"
IMMUTABLE = "public, max-age=31536000, immutable"
# Explicit, because Windows' registry can map .js to text/plain, and browsers refuse to run a
# module script served as that.
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".webmanifest": "application/manifest+json",
}


class DeployError(Exception):
    pass


def log(message: str) -> None:
    print(f"[deploy] {message}", flush=True)


def tool(name: str) -> str:
    path = shutil.which(name)  # honors PATHEXT, so pnpm.cmd is found on Windows
    if path is None:
        raise DeployError(f"{name} isn't on PATH")
    return path


def run(*cmd: str, stdin: str | None = None, cwd: Path = ROOT) -> None:
    log("$ " + " ".join(cmd))
    subprocess.run([tool(cmd[0]), *cmd[1:]], input=stdin, text=True, cwd=cwd, check=True)


def output(*cmd: str, cwd: Path = ROOT) -> str:
    return subprocess.run(
        [tool(cmd[0]), *cmd[1:]], cwd=cwd, check=True, text=True, capture_output=True
    ).stdout


def config() -> dict[str, str]:
    cfg = {k: os.environ.get(k, "") for k in KEYS}
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        try:
            tf = json.loads(output("terraform", "-chdir=infra/terraform", "output", "-json",
                                   "github_variables"))  # fmt: skip
        except (DeployError, subprocess.CalledProcessError) as exc:
            raise DeployError(f"set {', '.join(missing)} (terraform output failed: {exc})") from exc
        cfg.update({k: tf[k] for k in missing})
    cfg["SITE_URL"] = cfg["SITE_URL"].rstrip("/")
    return cfg


class Aws:
    def __init__(self, region: str) -> None:
        # Long reads: a migration on a fresh cluster waits for its index builds.
        slow = Config(read_timeout=900, retries={"max_attempts": 3, "mode": "standard"})
        self.ecr = boto3.client("ecr", region_name=region)
        self.lam = boto3.client("lambda", region_name=region, config=slow)
        self.s3 = boto3.client("s3", region_name=region)
        self.cf = boto3.client("cloudfront")

    def invoke(self, function: str, payload: dict[str, Any], qualifier: str | None = None) -> dict:
        extra = {"Qualifier": qualifier} if qualifier else {}
        r = self.lam.invoke(FunctionName=function, Payload=json.dumps(payload).encode(), **extra)
        body = r["Payload"].read().decode()
        try:
            data = json.loads(body)
        except ValueError:
            data = None
        if r.get("FunctionError") or not isinstance(data, dict) or data.get("ok") is not True:
            raise DeployError(f"{function} {payload['task']} failed: {body[:2000]}")
        return data

    def update_code(self, function: str, image_uri: str) -> None:
        log(f"{function} <- {image_uri}")
        self.lam.update_function_code(FunctionName=function, ImageUri=image_uri)
        self.lam.get_waiter("function_updated_v2").wait(FunctionName=function)


# --- steps ---------------------------------------------------------------------------------


def commit(allow_dirty: bool) -> str:
    sha = output("git", "rev-parse", "HEAD").strip()
    if not allow_dirty and output("git", "status", "--porcelain").strip():
        raise DeployError("the worktree has uncommitted changes; a release is named by its commit")
    return sha


def image(aws: Aws, repository: str, sha: str) -> str:
    """Build and push the image for ``sha`` unless ECR has it; return its URI by digest."""
    registry, name = repository.split("/", 1)

    def digest() -> str | None:
        try:
            found = aws.ecr.describe_images(repositoryName=name, imageIds=[{"imageTag": sha}])
        except aws.ecr.exceptions.ImageNotFoundException:
            return None
        return found["imageDetails"][0]["imageDigest"]

    if (d := digest()) is not None:
        log(f"image {sha[:12]} is already in ECR")
    else:
        auth = aws.ecr.get_authorization_token()["authorizationData"][0]
        user, password = base64.b64decode(auth["authorizationToken"]).decode().split(":", 1)
        run("docker", "login", "--username", user, "--password-stdin", registry, stdin=password)
        # One plain manifest (no attestations): what Lambda accepts.
        run("docker", "buildx", "build", "--platform", "linux/amd64", "--provenance=false",
            "--sbom=false", "--build-arg", f"BUILD={sha}", "--tag", f"{repository}:{sha}",
            "--push", "api")  # fmt: skip
        d = digest()
        if d is None:
            raise DeployError("the pushed image isn't in ECR")
    return f"{repository}@{d}"


def build_web() -> Path:
    run("pnpm", "install", "--frozen-lockfile", cwd=ROOT / "web")
    run("pnpm", "build", cwd=ROOT / "web")
    dist = ROOT / "web" / "dist"
    if not (dist / "index.html").is_file():
        raise DeployError("web/dist/index.html is missing after the build")
    return dist


def release_api(aws: Aws, cfg: dict[str, str], image_uri: str, sha: str) -> tuple[str, str]:
    """Migrate, audit, publish and health-check; return (new version, previous live version)."""
    api, tasks = cfg["API_FUNCTION"], cfg["TASKS_FUNCTION"]
    try:
        live_engine = aws.invoke(api, {"task": "health"}, qualifier=ALIAS).get("engine")
    except DeployError:
        live_engine = None  # an unhealthy live version: audit, and still allow the fix out
    previous_image = aws.lam.get_function(FunctionName=tasks)["Code"]["ImageUri"]
    aws.update_code(tasks, image_uri)
    migrated = aws.invoke(tasks, {"task": "migrate"})
    log(f"migrations applied: {migrated['applied'] or 'none pending'}")
    if migrated.get("engine") != live_engine:
        log(f"jackdaw {live_engine or '(unknown)'} -> {migrated.get('engine')}: auditing")
        try:
            result = aws.invoke(tasks, {"task": "audit"})
        except DeployError:
            log("audit failed: putting the tasks function back on its previous image")
            aws.update_code(tasks, previous_image)
            raise
        log(f"audit passed: all {result['checked']} ended episodes of season "
            f"{result['season']} replay to their recorded final state")  # fmt: skip

    aws.update_code(api, image_uri)
    version = aws.lam.publish_version(FunctionName=api, Description=sha)["Version"]
    aws.lam.get_waiter("published_version_active").wait(FunctionName=api, Qualifier=version)
    health = aws.invoke(api, {"task": "health"}, qualifier=version)
    if health.get("build") != sha:
        raise DeployError(f"version {version} reports build {health.get('build')!r}, not {sha}")
    log(f"{api}:{version} is healthy")
    previous = aws.lam.get_alias(FunctionName=api, Name=ALIAS)["FunctionVersion"]
    return version, previous


def move_alias(aws: Aws, function: str, version: str) -> None:
    aws.lam.update_alias(FunctionName=function, Name=ALIAS, FunctionVersion=version)
    log(f"{function}:{ALIAS} -> version {version}")


def upload_site(aws: Aws, cfg: dict[str, str], dist: Path, sha: str) -> None:
    bucket = cfg["WEB_BUCKET"]
    files = sorted(p for p in dist.rglob("*") if p.is_file())
    key = {p: p.relative_to(dist).as_posix() for p in files}
    assets = [p for p in files if key[p].startswith("assets/")]
    rest = [p for p in files if p not in assets]
    have: set[str] = set()
    for page in aws.s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="assets/"):
        have.update(o["Key"] for o in page.get("Contents", []))

    def put(p: Path, cache: str) -> None:
        kind = TYPES.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0]
        aws.s3.put_object(Bucket=bucket, Key=key[p], Body=p.read_bytes(), CacheControl=cache,
                          ContentType=kind or "application/octet-stream")  # fmt: skip

    # Hashed assets first, so the new index.html never points at a file that isn't there yet.
    # Old ones stay: a browser still holding the previous index.html can load its assets.
    new = [p for p in assets if key[p] not in have]
    for p in new:
        put(p, IMMUTABLE)
    for p in rest:
        put(p, "no-cache" if p.name == "index.html" else "public, max-age=300")
    log(f"uploaded {len(new)} new assets and {len(rest)} other files")
    # The catalog is cached at the edge for a day, and can change with the release.
    paths = ["/" + key[p] for p in rest] + ["/api/catalog"]
    aws.cf.create_invalidation(
        DistributionId=cfg["DISTRIBUTION_ID"],
        InvalidationBatch={
            "Paths": {"Quantity": len(paths), "Items": paths},
            "CallerReference": f"{sha}-{time.time_ns()}",
        },
    )


def fetch(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "jackdaw-arena-deploy"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def smoke(site: str, sha: str) -> None:
    deadline = time.monotonic() + 120
    problem = ""
    while time.monotonic() < deadline:
        problem = ""
        status, body = fetch(f"{site}/api/version")
        build = json.loads(body).get("build") if status == 200 else None
        if build != sha:
            problem = f"/api/version: {status} build={build}"
        elif (s := fetch(f"{site}/healthz/deep")[0]) != 200:
            problem = f"/healthz/deep: {s}"
        else:
            status, body = fetch(f"{site}/agents/house-smart")  # a client-side route
            if status != 200 or b'<div id="root">' not in body:
                problem = f"the SPA shell: {status}"
        if not problem:
            log(f"smoke test passed: {site} serves {sha[:12]}")
            return
        time.sleep(5)
    raise DeployError(f"smoke test failed: {problem}")


def rollback(aws: Aws, cfg: dict[str, str], version: str | None) -> None:
    api = cfg["API_FUNCTION"]
    current = aws.lam.get_alias(FunctionName=api, Name=ALIAS)["FunctionVersion"]
    if version is None:
        pages = aws.lam.get_paginator("list_versions_by_function").paginate(FunctionName=api)
        published = [v["Version"] for page in pages for v in page["Versions"]]
        older = [int(v) for v in published if v != "$LATEST" and int(v) < int(current)]
        if not older:
            raise DeployError(f"no version before {current}")
        version = str(max(older))
    move_alias(aws, api, version)
    log("the web build isn't rolled back: redeploy the older commit for that")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--rollback", nargs="?", const="", metavar="VERSION",
        help="move the API's live alias back (default: the version before the live one)",
    )  # fmt: skip
    parser.add_argument(
        "--allow-dirty", action="store_true",
        help="release HEAD despite uncommitted changes (they aren't included)",
    )  # fmt: skip
    args = parser.parse_args()
    try:
        cfg = config()
        aws = Aws(cfg["AWS_REGION"])
        if args.rollback is not None:
            rollback(aws, cfg, args.rollback or None)
            return 0
        sha = commit(args.allow_dirty)
        log(f"releasing {sha}")
        image_uri = image(aws, cfg["ECR_REPOSITORY"], sha)
        dist = build_web()
        version, previous = release_api(aws, cfg, image_uri, sha)
        move_alias(aws, cfg["API_FUNCTION"], version)
        aws.invoke(cfg["API_FUNCTION"], {"task": "warm"}, qualifier=ALIAS)
        upload_site(aws, cfg, dist, sha)
        try:
            smoke(cfg["SITE_URL"], sha)
        except DeployError:
            if previous != version:
                log(f"moving {ALIAS} back to version {previous}")
                move_alias(aws, cfg["API_FUNCTION"], previous)
            raise
    except (DeployError, subprocess.CalledProcessError) as exc:
        log(f"FAILED: {exc}")
        return 1
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
