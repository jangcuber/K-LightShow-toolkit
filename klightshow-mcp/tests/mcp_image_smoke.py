"""MCP stdio test for images: place_image (dry run + real), preview_frames, export still valid.
usage: mcp_image_smoke.py <project> <image1> <image2> <out_dir>"""
import asyncio
import base64
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT, IMG1, IMG2, OUT = sys.argv[1:5]
SRC = os.path.join(os.path.dirname(__file__), "..", "src")


def unpack(res, name):
    info = None
    for c in res.content:
        if getattr(c, "type", "") == "image":
            path = os.path.join(OUT, name)
            open(path, "wb").write(base64.b64decode(c.data))
            print("  picture ->", path, getattr(c, "mime_type", None) or getattr(c, "mimeType", None))
        elif getattr(c, "text", None):
            info = c.text
    if getattr(res, "is_error", None) or getattr(res, "isError", None):
        print("  ERROR", info)
    return info


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "klightshow_mcp"],
                                   env={**os.environ, "PYTHONPATH": os.path.abspath(SRC)})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print("dry run heart at bar 21:")
            print(" ", unpack(await s.call_tool("place_image", {"project": PROJECT, "image_path": IMG1, "start": "bar:21",
                                                                 "dry_run": True}), "heart_dry.png")[:160])
            print("heart pulsing on beats, bars 21-23:")
            unpack(await s.call_tool("place_image", {"project": PROJECT, "image_path": IMG1, "start": "bar:21", "end": "bar:23",
                                                       "pulse": "beats"}), "heart.png")
            print("star scrolling left, bars 33-35:")
            unpack(await s.call_tool("place_image", {"project": PROJECT, "image_path": IMG2, "start": "bar:33", "end": "bar:35",
                                                       "scroll": "left"}), "star.png")
            print("preview_frames:")
            print(" ", unpack(await s.call_tool("preview_frames", {"project": PROJECT,
                                                                    "times": ["bar:21", "bar:21.125", "bar:21.25", "bar:34"]}),
                              "frames.png"))
            res = json.loads(unpack(await s.call_tool("export_show", {"project": PROJECT, "zip": False}), "x"))
            print("export ok:", res["validation"]["ok"], res["cars"], "cars,", res["seconds"], "s")

asyncio.run(main())
