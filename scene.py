#!/usr/bin/env python3
"""Procedural ASCII night scene: stars, moon, layered mountains, lake reflection.

usage: python3 scene.py [seed] [width] [height]
"""
import math
import random
import sys

seed = int(sys.argv[1]) if len(sys.argv) > 1 else random.randrange(10_000)
W = int(sys.argv[2]) if len(sys.argv) > 2 else 78
H = int(sys.argv[3]) if len(sys.argv) > 3 else 28
rng = random.Random(seed)

grid = [[" "] * W for _ in range(H)]
horizon = int(H * 0.68)  # where land meets the lake

# --- stars -------------------------------------------------------------
for _ in range(W * horizon // 18):
    x, y = rng.randrange(W), rng.randrange(horizon - 4)
    grid[y][x] = rng.choice(".....''*+")

# --- moon --------------------------------------------------------------
mx, my, r = rng.randrange(8, W - 8), rng.randrange(2, horizon // 3), 3
for y in range(H):
    for x in range(W):
        d = math.hypot((x - mx) / 2.0, y - my)  # /2: terminal cells are tall
        if d < r:
            grid[y][x] = "@" if d < r - 1.2 else "O"

# --- mountains (back to front, each layer darker + lower) --------------
def ridge(base, amp, rough):
    """1D midpoint-ish noise: sum of a few random sine waves."""
    waves = [(rng.uniform(0.02, 0.2) * rough, rng.uniform(0, 6.28), rng.uniform(0.4, 1))
             for _ in range(4)]
    return [base - amp * sum(a * math.sin(f * x + p) for f, p, a in waves) / 2.5
            for x in range(W)]

layers = [  # (baseline row, amplitude, roughness, fill char, peak char)
    (horizon - 6, 6, 1.0, ":", "^"),
    (horizon - 3, 4, 1.6, "%", "/"),
    (horizon - 1, 2, 2.5, "#", "#"),
]
for base, amp, rough, fill, peak in layers:
    tops = ridge(base, amp, rough)
    for x, top in enumerate(tops):
        t = max(0, int(top))
        for y in range(t, horizon):
            grid[y][x] = fill
        if 0 <= t < horizon:
            left = tops[x - 1] if x else top
            grid[t][x] = "/" if left > top + 0.3 else "\\" if left < top - 0.3 else peak

# --- lake: mirrored, rippled reflection --------------------------------
ripple = {":": "-", "%": "~", "#": "=", "@": "o", "O": "o", "*": ".", "+": ".", "/": "\\", "\\": "/", "^": "v"}
for y in range(horizon, H):
    src = horizon - (y - horizon) - 1
    for x in range(W):
        sx = min(W - 1, max(0, x + rng.choice((-1, 0, 0, 1))))
        c = grid[src][sx] if src >= 0 else " "
        if c == " " and rng.random() < 0.04:
            c = "~"
        grid[y][x] = ripple.get(c, c) if rng.random() > 0.15 else " "

print("\n".join("".join(row) for row in grid))
print(f"seed {seed}".rjust(W))
