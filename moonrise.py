# Moonrise in ASCII
# by Clayton Aylor, 2026
#
#   pip install numpy pygame-ce
#   python moonrise.py [seed]
#
# A night scene drawn only in letters. A big orange moon climbs out from behind three ranges of
# mountains, cooling to white as it rises. Its light catches the slopes that face it, drowns the
# stars near it and lays a path of glints across the lake, where everything above is mirrored in
# rippling letters. Now and then a shooting star crosses the sky, and the water.
#
# Space pause · R restart · N new landscape · S screenshot · Esc quit

import sys
import time
from pathlib import Path

import numpy as np
import pygame

TITLE = "Moonrise in ASCII"
AUTHOR = "Clayton Aylor"
HERE = Path(__file__).parent
TAU = 2 * np.pi

# timing (s)
FPS = 30
LOOP = 32.0                                     # one run, then it starts over
T_RISE = (0.4, 8.0)                             # the moon climbs from behind the hills to its place

# the grid of letters
CW, CH, FONT_PX = 9, 14, 15                     # cell size and font size (px)
COLS, ROWS = 132, 62                            # 1188 x 868 px
HORIZON = 0.64                                  # the lake starts on this share of the rows
MONO = "menlo,consolas,dejavusansmono,couriernew,monospace"

# the moon
MOON_R = 5.2                                    # radius, in rows
MOON_TOP = 0.17                                 # where it ends up (share of the rows)
MOON = np.array([1.0, 0.95, 0.82])              # high and white
MOON_LOW = np.array([1.0, 0.56, 0.28])          # rising, orange
CRATER = np.array([0.70, 0.66, 0.58])
WHITE = np.array([1.0, 0.98, 0.95])

# the mountains, far -> near: colour, ridge line (share of the rows), height (rows), roughness
LAYERS = [
    (np.array([0.46, 0.50, 0.86]), 0.52, 20.0, 1.1),
    (np.array([0.34, 0.34, 0.70]), 0.58, 12.0, 1.8),
    (np.array([0.24, 0.22, 0.50]), 0.635, 5.0, 3.0),
]
WATER = np.array([0.62, 0.74, 1.0])             # reflections are tinted and dimmed by this
RIPPLE = np.array([0.12, 0.17, 0.38])           # the plain water texture

# the sky
N_STARS = 300
STAR_COOL, STAR_WARM = np.array([0.70, 0.80, 1.0]), np.array([1.0, 0.84, 0.62])
FLARES = 3                                      # how many of the brightest stars throw a cross at once
SHOOT_GAP = (3.0, 6.5)                          # seconds between shooting stars
TRAIL_FADE = 0.62                               # what is left of a moving letter's light each frame

# glow: (spread in cells, strength), a tight one and a wide one
GLOW = ((0.8, 1.3), (3.2, 1.1))

# HUD colours
DIM, ACCENT, SIGN = (118, 112, 140), (150, 170, 255), (178, 176, 200)

# letters, from little ink to a lot
G = lambda ch: ord(ch) - 32                     # character -> glyph index (printable ASCII only)
RAMP = lambda s: np.array([G(c) for c in s])
MOON_RAMP = RAMP("-:;i+=ltvcxzjfnuoeasd0QO8B$%&#@")
ROCK_RAMP = RAMP("`.,:;'!i+=vxz*%#&8$@")
STROKES = RAMP("-/|\\")

# what a letter becomes when it is mirrored in the water
MIRROR = np.arange(95)
for a, b in ("/\\", "\\/", "^v", "_-", "*+", "'.", "`."):
    MIRROR[G(a)] = G(b)


def ease(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def stroke_for(dx, dy):
    # the stroke that best follows a direction on screen (y up): - / | \ in 45 degree sectors
    ang = np.degrees(np.arctan2(dy, dx)) % 180
    return STROKES[np.asarray((ang + 22.5) // 45).astype(int) % 4]


def ramp_pick(ramp, level, jitter):
    # a letter for a brightness 0..1, nudged up or down a step per cell so flat areas get texture
    i = np.round(np.clip(level, 0, 1) * (len(ramp) - 1)) + jitter
    return ramp[np.clip(i, 0, len(ramp) - 1).astype(int)]


def ridge(rng, n, rough):
    # a mountain profile 0..1: octaves of smoothly interpolated random heights, folded for peaks
    x, out, amp, freq = np.arange(n), np.zeros(n), 1.0, rough / 38
    for _ in range(5):
        pts = rng.uniform(-1, 1, int(n * freq) + 3)
        xs = x * freq
        i = xs.astype(int)
        f = ease(xs - i)
        out += amp * (pts[i] * (1 - f) + pts[i + 1] * f)
        amp, freq = amp * 0.5, freq * 2.1
    v = np.clip(out / 1.6, -1, 1)
    return 0.65 * (1 - np.abs(v)) ** 1.8 + 0.35 * (v + 1) / 2


def blur_cells(a, sx, sy):
    # separable gaussian over a (rows, cols, 3) image, sx / sy in cells
    for axis, s in ((1, sx), (0, sy)):
        r = max(1, int(3 * s))
        k = np.exp(-0.5 * (np.arange(-r, r + 1) / s) ** 2)
        k /= k.sum()
        pad = [(0, 0)] * a.ndim
        pad[axis] = (r, r)
        p = np.pad(a, pad)
        n = a.shape[axis]
        if axis == 0:
            a = sum(w * p[i:i + n] for i, w in enumerate(k))
        else:
            a = sum(w * p[:, i:i + n] for i, w in enumerate(k))
    return a


class Frame:
    # one frame of letters: glyph, colour, and whether it is moving (moving letters leave trails)
    def __init__(self, rows, cols):
        self.char = np.zeros((rows, cols), np.intp)
        self.col = np.zeros((rows, cols, 3), np.float32)
        self.move = np.zeros((rows, cols), bool)

    def cover(self, mask, char, col, move=False):
        # lay full-size char / colour arrays over the frame wherever mask is set
        self.char[mask] = char[mask]
        self.col[mask] = col[mask]
        self.move[mask] = move

    def dots(self, r, c, char, col, move=False, brighter_only=False):
        # set single cells (scalars or arrays), skipping anything off the grid
        r = np.atleast_1d(np.asarray(r)).astype(int)
        c = np.atleast_1d(np.asarray(c)).astype(int)
        char = np.broadcast_to(np.asarray(char), r.shape)
        col = np.broadcast_to(np.asarray(col, np.float32), r.shape + (3,))
        rows, cols = self.char.shape
        keep = np.flatnonzero((r >= 0) & (r < rows) & (c >= 0) & (c < cols))
        if brighter_only:
            keep = keep[col[keep].max(-1) > self.col[r[keep], c[keep]].max(-1)]
        rr, cc = r[keep], c[keep]
        self.char[rr, cc], self.col[rr, cc], self.move[rr, cc] = char[keep], col[keep], move


class Afterglow:
    # trails, kept per cell: a moving letter's light lingers and fades where nothing new is drawn
    def __init__(self, rows, cols):
        self.char = np.zeros((rows, cols), np.intp)
        self.col = np.zeros((rows, cols, 3), np.float32)

    def clear(self):
        self.col[:] = 0

    def apply(self, f):
        self.col *= TRAIL_FADE
        m = f.move & (f.char > 0)
        self.char[m] = f.char[m]
        self.col[m] = np.maximum(self.col[m], f.col[m])
        show = (f.char == 0) & (self.col.max(-1) > 0.03)
        f.char[show], f.col[show] = self.char[show], self.col[show]


class Canvas:
    # letters -> pixels: each glyph's coverage mask times its cell's colour, plus a soft glow
    def __init__(self, cols, rows, cw, ch, font_px):
        self.cols, self.rows, self.cw, self.ch = cols, rows, cw, ch
        self.size = (cols * cw, rows * ch)
        font = pygame.font.SysFont(MONO, font_px, bold=True)
        self.masks = np.zeros((95, ch, cw), np.float32)
        for i in range(95):
            img = pygame.surfarray.array_red(font.render(chr(32 + i), True, (255, 255, 255), (0, 0, 0))).T
            h, w = img.shape                                            # centre the glyph in its cell, cropping
            oy, ox = (h - ch) // 2, (w - cw) // 2
            src = img[max(oy, 0):max(oy, 0) + ch, max(ox, 0):max(ox, 0) + cw]
            dy, dx = max(-oy, 0), max(-ox, 0)
            self.masks[i, dy:dy + src.shape[0], dx:dx + src.shape[1]] = src / 255.0
        self.ink = self.masks.mean((1, 2))                              # how much of its cell each glyph covers
        self.surface = pygame.Surface(self.size)
        self.glow_cells = pygame.Surface((cols, rows))

    def render(self, char, col):
        rows, cols, ch, cw = self.rows, self.cols, self.ch, self.cw
        col = np.clip(col, 0, 1.25).astype(np.float32)
        px = self.masks[char][..., None] * col[:, :, None, None, :]     # rows, cols, ch, cw, rgb
        img = px.transpose(0, 2, 1, 3, 4).reshape(rows * ch, cols * cw, 3) * 255

        # the glow: each cell's light spread over its neighbours, then stretched smoothly over the pixels
        light = col * self.ink[char][..., None]
        glow = sum(k * blur_cells(light, s, s * cw / ch) for s, k in GLOW)
        pygame.surfarray.blit_array(self.glow_cells, np.clip(glow * 255, 0, 255).astype(np.uint8).transpose(1, 0, 2))
        big = pygame.transform.smoothscale(self.glow_cells, self.size)
        img += pygame.surfarray.array3d(big).transpose(1, 0, 2)

        pygame.surfarray.blit_array(self.surface, np.clip(img, 0, 255).astype(np.uint8).transpose(1, 0, 2))
        return self.surface


class Moonrise:
    def __init__(self, seed=None, cols=COLS, rows=ROWS):
        pygame.font.init()
        self.cols, self.rows = cols, rows
        self.h0 = round(rows * HORIZON)
        self.gr, self.gc = np.mgrid[0:rows, 0:cols]
        self.canvas = Canvas(cols, rows, CW, CH, FONT_PX)
        self.trails = Afterglow(rows, cols)
        self.hud_font = pygame.font.SysFont(MONO, 15)
        self.last_t = None
        self.build(seed)

    # one landscape, made once per seed

    def build(self, seed=None):
        self.seed = int(np.random.default_rng().integers(1 << 30)) if seed is None else seed
        rng = np.random.default_rng(self.seed)
        rows, cols, h0, gr = self.rows, self.cols, self.h0, self.gr
        self.hash = rng.integers(0, 9973, (rows, cols))                # each cell's own number
        self.rand = rng.random((rows, cols))                           # each cell's own dice
        self.jitter = rng.integers(-1, 2, (rows, cols))                # each cell's letter nudge
        self.trails.clear()

        # the moon: where it rises, and its craters (centre u, v, size, depth) on the disk
        self.moon_x = rng.uniform(0.28, 0.72) * cols
        n = 7
        self.craters = np.stack([rng.uniform(-0.6, 0.6, n), rng.uniform(-0.6, 0.6, n),
                                 rng.uniform(0.10, 0.28, n), rng.uniform(0.10, 0.22, n)], 1)

        # the mountains: per range, which cells are rock, which are its edge, which stroke, how deep
        self.layers = []
        for colour, base, height, rough in LAYERS:
            top = np.clip(base * rows - height * ridge(rng, cols, rough), 3, None)
            filled = (gr + 0.5 >= top[None, :]) & (gr < h0)
            open_ = np.pad(~filled, 1, constant_values=True)
            edge = filled & (open_[:-2, 1:-1] | open_[1:-1, :-2] | open_[1:-1, 2:])
            dt = np.gradient(top)                                       # rows per column: > 0 falls away to the right
            stroke = np.broadcast_to(stroke_for(np.full(cols, float(CW)), -dt * CH), (rows, cols))
            peak = (top < np.roll(top, 1) - 0.3) & (top < np.roll(top, -1) - 0.3)
            stroke = np.where(peak[None, :] & (np.abs(gr + 0.5 - top) < 1), G("^"), stroke)
            self.layers.append(dict(colour=colour, top=top, filled=filled, edge=edge, stroke=stroke,
                                    dt=dt, depth=gr + 0.5 - top[None, :]))

        # stars: where, how bright at rest, how they shimmer, and when (if ever) they sparkle
        self.stars = dict(x=rng.random(N_STARS) * cols, y=rng.random(N_STARS) * (h0 - 2),
                          rest=0.10 + 0.28 * rng.random(N_STARS) ** 2,
                          rate=rng.uniform(0.6, 2.2, N_STARS), phase=rng.uniform(0, TAU, N_STARS),
                          spark=np.where(rng.random(N_STARS) < 0.4, 1.1, 0.0),
                          spark_rate=rng.uniform(0.12, 0.40, N_STARS), spark_phase=rng.uniform(0, TAU, N_STARS),
                          warmth=rng.random(N_STARS))

        # shooting stars for one run: start time, start x / y, direction, speed (cells/s), duration
        self.meteors, at = [], rng.uniform(*SHOOT_GAP)
        while at < LOOP - 1:
            side = 1 if rng.random() < 0.5 else -1
            a = rng.uniform(0.25, 0.65)                                 # radians below level
            self.meteors.append((at, rng.uniform(0.1, 0.9) * cols, rng.uniform(0.03, 0.30) * rows,
                                 side * np.cos(a), np.sin(a), rng.uniform(55, 90), rng.uniform(0.5, 0.9)))
            at += rng.uniform(*SHOOT_GAP)

    # where things are at time t

    def moon_at(self, t):
        u = ease((t - T_RISE[0]) / (T_RISE[1] - T_RISE[0]))
        u = 1 - (1 - u) ** 1.6                                          # quick off the hills, slowing as it climbs
        start = self.h0 + MOON_R + 1
        my = start + (MOON_TOP * self.rows - start) * u
        mx = self.moon_x + 5 * u
        # how much of the disk has cleared the ridge in front of it: 0 hidden, 1 fully up and climbing
        ridge_top = min(L["top"][int(np.clip(mx, 0, self.cols - 1))] for L in self.layers)
        rise = float(ease((ridge_top - (my - MOON_R)) / (2 * MOON_R + 6)))
        tone = MOON_LOW + (MOON - MOON_LOW) * ease((rise - 0.3) / 0.6)  # orange until it is well up
        return mx, my, rise, tone

    def moon_coords(self, mx, my):
        # every cell's position on the moon's disk, in moon radii, measured in pixels so it is round
        rad = MOON_R * CH
        u = (self.gc + 0.5 - mx) * CW / rad
        v = (self.gr + 0.5 - my) * CH / rad
        return u, v, np.hypot(u, v)

    # drawing, back to front

    def draw_stars(self, f, t, d, rise):
        s = self.stars
        x = (s["x"] + 0.03 * t) % self.cols
        r, c = s["y"].astype(int), x.astype(int)
        b = s["rest"] * (0.7 + 0.3 * np.sin(s["rate"] * t + s["phase"]))
        b = b + s["spark"] * np.clip(np.sin(s["spark_rate"] * t + s["spark_phase"]), 0, 1) ** 60
        b *= 1 - 0.85 * rise * np.exp(-(d[r, c] / 3.2) ** 2)           # drowned by the moon
        w = s["warmth"][:, None]
        tint = np.where(w < 0.5, STAR_COOL + (1 - STAR_COOL) * w * 2, 1 + (STAR_WARM - 1) * (w - 0.5) * 2)
        glyph = np.where(b > 0.75, G("*"), np.where(b > 0.42, G("+"), G(".")))
        f.dots(r, c, glyph, tint * np.clip(0.25 + 0.8 * b, 0, 1.2)[:, None])
        # the brightest few throw a cross of - and |, twice as long sideways since cells are tall
        for j in np.argsort(-b)[:FLARES]:
            if b[j] < 0.8:
                break
            n = int(1 + 3 * min(b[j], 1.2))
            for i in range(1, n + 1):
                k = tint[j] * 0.75 * min(b[j], 1.1) * (1 - i / (n + 1)) ** 1.4
                f.dots([r[j]] * 4, [c[j] - 2 * i, c[j] - 2 * i + 1, c[j] + 2 * i - 1, c[j] + 2 * i], G("-"), k, brighter_only=True)
                f.dots([r[j] - i, r[j] + i], [c[j]] * 2, G("|"), k, brighter_only=True)

    def draw_meteors(self, f, t):
        # a white head and a tail of strokes along its path, fading in and out; trails do the rest
        for t0, x0, y0, dx, dy, speed, dur in self.meteors:
            a = t - t0
            if not 0 <= a < dur:
                continue
            fade = np.sin(np.pi * a / dur) ** 0.7
            step = np.array([dx, dy * CW / CH])                         # one cell-width along the path
            head = np.array([x0, y0]) + step * speed * a
            tail = int(stroke_for(dx, -dy))
            for i in range(10):
                x, y = head - step * i * 1.2
                if y < self.h0 - 1:
                    k = fade * (1 - i / 10) ** 1.5
                    f.dots(y, x, G("*") if i == 0 else tail, WHITE * (1.25 if i == 0 else 1.0) * k, move=True)

    def draw_moon(self, f, t, uv, tone, rise):
        u, v, d = uv
        # the halo: a sparse ring of dots, shimmering slowly
        strength = np.clip((2.8 - d) / 1.75, 0, 1) ** 1.6
        on = (d > 1.05) & (d < 2.8) & (self.gr < self.h0) & (((self.rand + t * 0.07) % 1.0) < 0.42 * strength)
        f.char[on] = np.where(strength[on] > 0.55, G(":"), G("."))
        f.col[on] = tone * (0.10 + 0.30 * strength[on, None]) * (0.4 + 0.6 * rise)

        inside = d < 1
        if not inside.any():
            return
        # the disk: letters by brightness, darker toward the rim and in the craters
        z = np.sqrt(np.clip(1 - d * d, 0, None))
        cu, cv, cr, depth = self.craters.T
        crater = (depth * np.exp(-((u[..., None] - cu) ** 2 + (v[..., None] - cv) ** 2) / cr ** 2)).sum(-1)
        lum = np.clip(0.48 + 0.42 * z + 0.10 * (u - v) - crater, 0.3, 1.0)
        letters = ramp_pick(MOON_RAMP, (lum - 0.3) / 0.7, self.jitter)
        col = tone * lum[..., None] + (CRATER * tone - tone) * np.clip(crater * 3, 0, 1)[..., None]

        # the rim: strokes along the circle, _ across the top
        open_ = np.pad(~inside, 1, constant_values=True)
        rim = inside & (open_[:-2, 1:-1] | open_[2:, 1:-1] | open_[1:-1, :-2] | open_[1:-1, 2:])
        rc = stroke_for(v * CH, u * CW)
        rc = np.where((np.abs(u * CW) < 0.4 * np.abs(v * CH)) & (v < 0), G("_"), rc)
        col = np.where(rim[..., None], np.minimum(tone * 1.15, 1.2), col)
        f.cover(inside, np.where(rim, rc, letters), col)

    def draw_mountains(self, f, mx, tone, rise):
        # far to near, each range covers what is behind it; slopes facing the moon catch its light
        side = np.sign(mx - (np.arange(self.cols) + 0.5))
        for i, L in enumerate(self.layers):
            facing = np.clip(L["dt"] * side * 1.4, -1, 1)[None, :]
            light = rise * (0.55 + 0.45 * facing) * np.exp(-L["depth"] / (1.6 + 1.4 * i))
            letters = ramp_pick(ROCK_RAMP, 0.08 + light, self.jitter)
            col = L["colour"] * (0.22 + 0.22 * rise) + tone * light[..., None] * 0.42
            col = np.where(L["edge"][..., None], col * 1.45 + tone * 0.12 * rise, col)
            f.cover(L["filled"], np.where(L["edge"], L["stroke"], letters), col)

    def draw_lake(self, f, t, mx, my, tone, rise):
        # everything above, mirrored below the horizon, rippling sideways, broken by streaks of dark
        h0, rows, cols = self.h0, self.rows, self.cols
        j = self.gr[h0:] - h0
        gc = self.gc[h0:]
        nj = rows - h0
        src_r = np.clip(h0 - 1 - j, 0, None)
        wobble = (0.4 + 0.11 * j) * np.sin(j * 1.9 + t * 1.8 + 0.8 * np.sin(gc * 0.07 + t * 0.5 + j * 0.6))
        src_c = np.clip(gc + np.round(wobble).astype(int), 0, cols - 1)
        char = MIRROR[f.char[src_r, src_c]]
        col = f.col[src_r, src_c] * WATER * (0.60 * (1 - 0.45 * j / nj))[..., None]
        move = f.move[src_r, src_c]
        char = np.where((char > 0) & (self.hash[h0:] % 5 == 0), G("~"), char)
        gap = np.sin(gc * 0.31 + j * 2.7 - t * 1.2 + 2 * np.sin(gc * 0.045 + t * 0.3)) > 0.74
        char = np.where(gap, 0, char)

        # the plain water: a scatter of ripples drifting sideways, each row at its own pace
        shift = (t * (0.9 + 0.17 * j[:, :1])).astype(int)
        tex = (self.hash[h0:][np.arange(nj)[:, None], (gc + shift) % cols] % 19 == 0) & (char == 0)
        char = np.where(tex, np.where(self.hash[h0:] % 2 == 0, G("-"), G("~")), char)
        col = np.where(tex[..., None], RIPPLE * (0.55 + 0.45 * j / nj)[..., None], col)

        # the moon's path: glints across the water under it, widening toward you
        if my < h0 and rise > 0:
            width = MOON_R * CH / CW * (0.40 + 0.05 * j)
            dens = np.exp(-((gc + 0.5 - mx) / width) ** 2) * (0.25 + 0.75 * rise)
            glint = (self.rand[h0:] + np.floor(t * 7) * 0.618034) % 1.0 < 0.62 * dens
            b = np.clip(dens * (1.15 - 0.4 * j / nj) + 0.3 * self.rand[h0:], 0, 1.3)
            char = np.where(glint, np.where(b > 0.85, G("="), np.where(b > 0.5, G("~"), G("-"))), char)
            col = np.where(glint[..., None], tone * b[..., None], col)
            move = move | glint

        f.char[h0:], f.col[h0:], f.move[h0:] = char, col, move

    def frame(self, t):
        f = Frame(self.rows, self.cols)
        mx, my, rise, tone = self.moon_at(t)
        uv = self.moon_coords(mx, my)
        self.draw_stars(f, t, uv[2], rise)
        self.draw_meteors(f, t)
        self.draw_moon(f, t, uv, tone, rise)
        self.draw_mountains(f, mx, tone, rise)
        self.draw_lake(f, t, mx, my, tone, rise)
        return f, rise

    def draw(self, t, hud=True):
        if self.last_t is None or t < self.last_t:
            self.trails.clear()                                         # restarted: no trails from before
        self.last_t = t
        f, rise = self.frame(t)
        self.trails.apply(f)
        out = self.canvas.render(f.char, f.col)
        if hud:
            w, h = self.canvas.size
            lines = [(f"{TITLE} · {AUTHOR}", SIGN),
                     (f"moon {rise * 100:5.1f}%    seed {self.seed}", DIM),
                     ("Space pause · R restart · N new landscape · S screenshot · Esc quit", DIM)]
            for i, (text, colour) in enumerate(lines):
                out.blit(self.hud_font.render(text, True, colour), (24, h - 18 - 21 * (len(lines) - i)))
            clock = self.hud_font.render(f"t {t:05.2f}s", True, ACCENT)
            out.blit(clock, (w - 24 - clock.get_width(), 14))
        return out


def main():
    pygame.init()
    show = Moonrise(int(sys.argv[1]) if len(sys.argv) > 1 else None)
    full = show.canvas.size
    info = pygame.display.Info()
    k = min(1.0, 0.9 * info.current_h / full[1], 0.95 * info.current_w / full[0]) if info.current_h > 0 else 1.0
    view = (int(full[0] * k), int(full[1] * k))
    window = pygame.display.set_mode(view)
    pygame.display.set_caption(TITLE)
    clock = pygame.time.Clock()
    t, paused, running = 0.0, False, True
    picture = show.draw(t)
    while running:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    running = False
                elif e.key == pygame.K_SPACE:
                    paused = not paused
                elif e.key == pygame.K_r:
                    t = 0.0
                elif e.key == pygame.K_n:
                    show.build()
                    t = 0.0
                elif e.key == pygame.K_s:
                    pygame.image.save(picture, str(HERE / f"moonrise_{show.seed}_{int(time.time())}.png"))
        step = clock.tick(FPS) / 1000
        if not paused:
            t = (t + min(step, 2 / FPS)) % LOOP
            picture = show.draw(t)
        window.blit(picture if view == full else pygame.transform.smoothscale(picture, view), (0, 0))
        pygame.display.flip()
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
