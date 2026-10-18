"""Command line: python -m klightshow_mcp.cli song.mp3 --rows 16 --cols 63"""

import argparse
import json

from .server import generate_show_from_music


def main():
    ap = argparse.ArgumentParser(description="Generate a Tesla light show from a music file")
    ap.add_argument("audio")
    ap.add_argument("--name")
    ap.add_argument("--rows", type=int, default=1)
    ap.add_argument("--cols", type=int, default=1)
    ap.add_argument("--missing", nargs="*", default=None, help="empty seats, e.g. A01 P63")
    ap.add_argument("--style", default="balanced", choices=["balanced", "energetic", "elegant"])
    ap.add_argument("--closures", default="safe", choices=["none", "safe", "full"])
    ap.add_argument("--title")
    ap.add_argument("--channels", type=int, default=48, choices=[48, 200])
    ap.add_argument("--mp3", action="store_true", help="write mp3 instead of wav")
    ap.add_argument("--layout", default="usb", choices=["usb", "automator"],
                    help="automator = source folder for K-LightShow USB Automator")
    a = ap.parse_args()
    res = generate_show_from_music(a.audio, a.name, a.rows, a.cols, a.missing, a.style, a.closures, a.title,
                                   a.channels, "mp3" if a.mp3 else "wav", layout=a.layout)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
