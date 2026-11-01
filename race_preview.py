"""Render an offline shark-race concept; never reads or changes bot state."""

import argparse
from pathlib import Path

from shark_race import shark_race_gif


def render_preview(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = [
        ("AANYA", 232, "Spoken"),
        ("JULIA YE", 61, "Frozen"),
        ("OLIVER CHEN", 43, "Spoken"),
        ("SHRESHTH SETH", 32, "Scheduled"),
        ("EVA OLTEANU", 24, "Spoken"),
        ("ETHAN", 15, "Scheduled"),
        ("KRISHIV", 12, "Frozen"),
        ("JERRY SONG", 9, "Spoken"),
        ("AARON WANG", 7, "Scheduled"),
        ("MATHEW ZHOU", 4, "Spoken"),
        ("YIHE CHEN", 2, "Scheduled"),
    ]
    frames = shark_race_gif(rows)
    frames[0].save(output / "shark-race.png")
    frames[0].save(output / "shark-race.gif", save_all=True, append_images=frames[1:],
                   duration=200, loop=0, optimize=True)
    page = """<!doctype html>
<html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Squolingo - Shark race preview</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#080e17;color:#e3f7ff;
font:16px/1.5 system-ui,sans-serif;min-height:100vh;display:grid;place-items:center;padding:28px}
main{width:min(100%,1100px)}header{display:flex;gap:20px;align-items:center;justify-content:space-between}
h1{font-size:24px;margin:0}p{color:#93afc0}small{color:#72dbc8;font-size:11px;letter-spacing:2px}
.card{background:#11202e;border:1px solid #283e50;border-radius:16px;padding:20px;
box-shadow:0 24px 80px #0007}img{display:block;width:100%;
border:1px solid #274558;border-radius:4px}.controls{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}
button{border:1px solid #385269;border-radius:7px;padding:10px 18px;background:#1f3548;
color:#c6deed;font:600 14px system-ui}button:first-child{background:#1c5957;border-color:#3b8e83}
.note{font-size:13px;margin-bottom:0}a{color:#80d8ef}
@media(prefers-reduced-motion:reduce){.animated{display:none}.still{display:block!important}}
</style>
<main><header><h1>Squolingo</h1><small>OFFLINE CONCEPT</small></header>
<div class="card">
<img class="animated" src="shark-race.gif" alt="Pixel-art sharks race toward a shared 300-streak finish line.">
<img class="still" style="display:none" src="shark-race.png" alt="Static version of the shark race.">
<div class="controls"><button disabled>Spoke</button><button disabled>Freeze</button>
<button disabled>My schedule</button><button disabled>My week</button></div>
<p class="note">Illustrative totals and statuses for 11 debaters.
Not live Discord data. Preview buttons are inactive.</p>
</div>
<p class="note">
<a href="shark-race.gif">Open GIF</a> / <a href="shark-race.png">Still image</a></p>
</main></html>
"""
    (output / "index.html").write_text(page, encoding="utf-8")
    return output / "index.html"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Local preview output directory")
    args = parser.parse_args()
    print(render_preview(args.output).resolve())
