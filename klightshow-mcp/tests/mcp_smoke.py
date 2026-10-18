"""Smoke test over real MCP stdio: list tools, generate a 4x8 lot show, edit a clip, export, validate."""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SONG = sys.argv[1]
SRC = os.path.join(os.path.dirname(__file__), "..", "src")


def text(res):
    return "\n".join(getattr(c, "text", "") for c in res.content)


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "klightshow_mcp"],
                                   env={**os.environ, "PYTHONPATH": os.path.abspath(SRC)})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("tools:", [t.name for t in tools.tools])
            res = await s.call_tool("generate_show_from_music", {"audio_path": SONG, "name": "smoke", "rows": 4, "cols": 8,
                                                                 "missing_seats": ["D08"], "title_text": "HI"})
            out = json.loads(text(res))
            print("generate:", out["export"]["cars"], "cars, ok =", out["export"]["validation"]["ok"], out["export"].get("zip"))
            res = await s.call_tool("add_clip", {"project": "smoke", "start": "bar:9", "end": "bar:11", "effect": "strobe",
                                                 "target": "turn_signals", "pattern": {"type": "snake", "span": 1.0}})
            print("add_clip:", text(res)[:200])
            res = await s.call_tool("preview_car", {"project": "smoke", "seat": "B03", "start": "bar:9", "end": "bar:10",
                                                    "channels": [0, 12, 25]})
            print(text(res))
            res = await s.call_tool("export_show", {"project": "smoke", "zip": False})
            exp = json.loads(text(res))
            print("export ok:", exp["validation"]["ok"], exp["validation"]["warnings"])
            f = os.path.join(exp["out_dir"], "cars", "A01", "LightShow", "smoke.fseq")
            res = await s.call_tool("validate_fseq", {"fseq_path": f, "audio_path": exp["audio"]})
            print("validate:", text(res)[:400])

asyncio.run(main())
