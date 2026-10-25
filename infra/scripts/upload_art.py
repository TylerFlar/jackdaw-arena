# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3>=1.40"]
# ///
"""Publish the game art in web/.art/ (from extract_art.py) to the site's bucket, under art/.

    uv run infra/scripts/upload_art.py

The files are cached as immutable, so different files go in a new folder (art/v2/, with
extract_art.py's VERSION). Releases never delete from the bucket: the art stays across them.
Configuration and credentials are deploy.py's.
"""

from __future__ import annotations

import sys

from deploy import IMMUTABLE, ROOT, TYPES, Aws, DeployError, config, log

ART = ROOT / "web" / ".art"


def main() -> int:
    files = sorted(p for p in ART.rglob("*") if p.is_file())
    # The manifest last: the site uses the art once the manifest is there.
    files.sort(key=lambda p: p.name == "manifest.json")
    if not files or files[-1].name != "manifest.json":
        log(f"no art in {ART}: run infra/scripts/extract_art.py first")
        return 1
    try:
        cfg = config()
        aws = Aws(cfg["AWS_REGION"])
        for p in files:
            key = "art/" + p.relative_to(ART).as_posix()
            kind = TYPES[p.suffix.lower()]
            aws.s3.put_object(Bucket=cfg["WEB_BUCKET"], Key=key, Body=p.read_bytes(),
                              CacheControl=IMMUTABLE, ContentType=kind)  # fmt: skip
            log(f"s3://{cfg['WEB_BUCKET']}/{key}")
    except DeployError as exc:
        log(f"FAILED: {exc}")
        return 1
    log(f"uploaded {len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
