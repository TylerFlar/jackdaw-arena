# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=11"]
# ///
"""Copy the sprites and the font the site draws with out of a Balatro install, into web/.art/v1/.

    uv run infra/scripts/extract_art.py ".../steamapps/common/Balatro/Balatro.exe"
    uv run infra/scripts/extract_art.py path/to/an/extracted/game    # a folder holding resources/

Balatro's art is LocalThunk's and never goes in this repository: web/.art is ignored by git, and
the site's build doesn't include it. `pnpm dev` serves it from there; upload_art.py publishes it
to the site's bucket. Without it, the site draws plain cards. Where each sprite sits in its atlas
comes from jackdaw's data, through /api/catalog.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
VERSION = 1  # the folder under art/: bump it when the files change, since they're cached forever

# name: (the game's 2x texture, cell width, cell height). Cells are twice the game's 1x units.
ATLASES = {
    "cards": ("8BitDeck.png", 142, 190),
    "centers": ("Enhancers.png", 142, 190),  # backs, enhancements, seals, the debuff cross
    "jokers": ("Jokers.png", 142, 190),
    "tarots": ("Tarots.png", 142, 190),  # tarots, planets and spectrals
    "vouchers": ("Vouchers.png", 142, 190),
    "boosters": ("boosters.png", 142, 190),
    "stickers": ("stickers.png", 142, 190),
    "tags": ("tags.png", 68, 68),
    "stakes": ("chips.png", 58, 58),
    "blinds": ("BlindChips.png", 68, 68),  # an animation strip per blind: only its first frame
}
FONT = "m6x11plus.ttf"
CREDIT = "Balatro art © LocalThunk. m6x11 font by Daniel Linssen."


class Game:
    """The game's files, from the executable (a zip archive) or an extracted folder."""

    def __init__(self, source: Path) -> None:
        self.zip = zipfile.ZipFile(source) if source.is_file() else None
        self.dir = None if self.zip else source
        if self.dir is not None and not (self.dir / "resources").is_dir():
            raise SystemExit(f"{source} has no resources/ folder")

    def read(self, name: str) -> bytes:
        if self.zip is not None:
            return self.zip.read(name)
        assert self.dir is not None
        return (self.dir / name).read_bytes()

    def version(self) -> str | None:
        try:
            return self.read("version.jkr").decode().splitlines()[1].strip()
        except (KeyError, FileNotFoundError, IndexError):
            return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source", type=Path, help="Balatro.exe, or a folder with the game's files")
    parser.add_argument("--out", type=Path, default=ROOT / "web" / ".art" / f"v{VERSION}")
    args = parser.parse_args()
    if not args.source.exists():
        raise SystemExit(f"{args.source} doesn't exist")
    game = Game(args.source)
    args.out.mkdir(parents=True, exist_ok=True)

    atlases = {}
    for name, (texture, w, h) in ATLASES.items():
        image = Image.open(io.BytesIO(game.read(f"resources/textures/2x/{texture}")))
        if image.width % w or image.height % h:
            raise SystemExit(f"{texture} is {image.size}, not a grid of {w}x{h} cells")
        if name == "blinds":
            image = image.crop((0, 0, w, image.height))
        image.save(args.out / f"{name}.png", optimize=True)
        atlases[name] = {"file": f"{name}.png", "cell": [w, h], "size": list(image.size)}
    (args.out / FONT).write_bytes(game.read(f"resources/fonts/{FONT}"))

    manifest = {
        "version": VERSION, "game": game.version(), "atlases": atlases, "font": FONT,
        "credit": CREDIT,
    }  # fmt: skip
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    total = sum(p.stat().st_size for p in args.out.iterdir())
    print(f"wrote {len(atlases)} atlases and {FONT} to {args.out} ({total // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
