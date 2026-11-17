# Jellyfish in ASCII
# by Clayton Aylor, 2026
#
#   pip install numpy pygame-ce
#   python jellyfish.py [seed]
#
# An underwater scene drawn only in letters. Jellyfish pulse their way up through the water: each
# squeeze of the bell pushes it up, and its tentacles and frilly arms stream behind it. Light
# rays slant down from the rippling surface, marine snow drifts, plankton flicker, bubbles rise
# from vents in the sand, kelp sways on the sea floor and schools of fish swim past.
#
# Space pause · R restart · N new sea · S screenshot · Esc quit

import sys

import numpy as np
import pygame

from moonrise import (AUTHOR, CH, CW, FONT_PX, MONO, TAU, Afterglow, Canvas, Frame, G, RAMP,
                      ease, ramp_pick, ridge, run, stroke_for)

TITLE = "Jellyfish in ASCII"
COLS, ROWS = 132, 62
STEP = 1 / 30                                   # simulation step (s)

# jellyfish
N_JELLIES = 7
JELLY_HUES = np.array([[1.0, 0.45, 0.78], [0.72, 0.52, 1.0], [0.42, 0.90, 1.0],
                       [1.0, 0.68, 0.42], [0.55, 1.0, 0.80]])
BELL_RAMP = RAMP(".,:;-~=+*oaeO0Q@")
HISTORY = 200                                   # how many past bell positions the tentacles can follow

# the sea
TOP, BOTTOM = np.array([8.0, 34.0, 66.0]), np.array([1.0, 5.0, 15.0])   # water, surface to floor (0..255)
SURFACE = np.array([0.55, 0.85, 1.0])
RAY = np.array([0.30, 0.55, 0.72])
SNOW = np.array([0.42, 0.52, 0.62])
PLANKTON = np.array([0.45, 1.0, 0.95])
BUBBLE = np.array([0.70, 0.90, 1.0])
SAND = np.array([0.72, 0.60, 0.40])
SAND_RAMP = RAMP("_.,:;'`~")
KELP = np.array([0.22, 0.70, 0.42])
FISH_COLOURS = np.array([[1.0, 0.62, 0.25], [1.0, 0.86, 0.35], [0.80, 0.85, 0.95]])
SCHOOL_PERIOD = 90.0                            # the fish timetable repeats this often (s)
FISH_SMALL, FISH_BIG = "><>", "><((('>"         # swimming right; flipped to swim left
DIM, SIGN, ACCENT = (110, 140, 160), (170, 200, 215), (120, 220, 230)


def flip(fish):
    return fish[::-1].translate(str.maketrans("<>()", "><)("))


def squeeze(p):
    # the bell's beat over one cycle 0..1: a quick squeeze, then a long slow relax
    return float(ease(p / 0.25)) if p < 0.25 else float(1 - ease((p - 0.25) / 0.75))


class Sea:
    def __init__(self, seed=None, cols=COLS, rows=ROWS):
        pygame.font.init()
        self.cols, self.rows = cols, rows
        self.gr, self.gc = np.mgrid[0:rows, 0:cols]
        self.canvas = Canvas(cols, rows, CW, CH, FONT_PX)
        self.trails = Afterglow(rows, cols)
        self.hud_font = pygame.font.SysFont(MONO, 15)
        w, h = self.canvas.size
        k = (np.arange(h, dtype=np.float32) / (h - 1))[:, None, None] ** 0.8
        self.backdrop = np.ascontiguousarray(np.broadcast_to(TOP + (BOTTOM - TOP) * k, (h, w, 3)), np.float32)
        self.ray_cells = pygame.Surface((cols, rows))
        self.build(seed)

    # one sea, made once per seed

    def build(self, seed=None):
        self.seed = int(np.random.default_rng().integers(1 << 30)) if seed is None else seed
        rng = np.random.default_rng(self.seed)
        rows, cols, gr = self.rows, self.cols, self.gr
        self.hash = rng.integers(0, 9973, (rows, cols))
        self.rand = rng.random((rows, cols))
        self.jitter = rng.integers(-1, 2, (rows, cols))
        self.sim_t = None                                               # the jellies start over on the next frame

        # the sea floor: rolling sand, its edge in strokes that follow the slope
        self.floor = np.clip(rows - 4.5 - 3.0 * ridge(rng, cols, 1.6), rows - 9, rows - 2)
        bed = gr + 0.5 >= self.floor[None, :]
        open_ = np.pad(~bed, 1, constant_values=True)
        self.bed, self.bed_edge = bed, bed & (open_[:-2, 1:-1] | open_[1:-1, :-2] | open_[1:-1, 2:])
        slope = np.gradient(self.floor)
        stroke = np.where(np.abs(slope) < 0.25, G("_"), stroke_for(np.full(cols, float(CW)), -slope * CH))
        self.bed_stroke = np.broadcast_to(stroke, (rows, cols))
        self.bed_depth = gr + 0.5 - self.floor[None, :]

        # kelp, bubble vents, marine snow and glowing plankton
        self.kelp = [dict(x=rng.uniform(2, cols - 2), h=int(rng.uniform(7, 24)), phase=rng.uniform(0, TAU),
                          sway=rng.uniform(1.5, 3.2), shade=rng.uniform(0.6, 1.0))
                     for _ in range(rng.integers(10, 16))]
        self.vents = [dict(x=rng.uniform(0.1, 0.9) * cols, gap=rng.uniform(0.45, 0.9),
                           speed=rng.uniform(6, 9), salt=rng.uniform(0, 100)) for _ in range(3)]
        n = 220
        self.snow = dict(x=rng.random(n) * cols, y=rng.random(n) * rows, fall=rng.uniform(0.2, 0.9, n),
                         wob=rng.uniform(0, TAU, n), b=rng.uniform(0.25, 0.8, n),
                         glyph=np.where(rng.random(n) < 0.8, G("."), G("'")))
        n = 40
        self.plankton = dict(x=rng.random(n) * cols, y=rng.uniform(0.1, 0.85, n) * rows,
                             rate=rng.uniform(0.15, 0.35, n), phase=rng.uniform(0, TAU, n))

        # schools of fish for one period of the timetable
        self.schools, at = [], rng.uniform(4, 8)
        while at < SCHOOL_PERIOD - 10:
            n = int(rng.integers(4, 10))
            big = rng.random() < 0.35
            self.schools.append(dict(t0=at, dir=1 if rng.random() < 0.5 else -1, y=rng.uniform(0.18, 0.7) * rows,
                                     speed=rng.uniform(9, 15) * (0.7 if big else 1.0), behind=rng.uniform(0, 16, n),
                                     dy=rng.uniform(-3, 3, n), ph=rng.uniform(0, TAU, n), big=big,
                                     col=FISH_COLOURS[rng.integers(len(FISH_COLOURS))]))
            at += rng.uniform(10, 20)

    def start_jellies(self):
        self.jelly_rng = np.random.default_rng(self.seed + 1)
        self.jellies = [self.new_jelly(anywhere=True) for _ in range(N_JELLIES)]
        self.trails.clear()

    def new_jelly(self, anywhere):
        rng = self.jelly_rng
        size = rng.uniform(2.8, 6.5)                                    # bell height, rows
        n = int(rng.integers(4, 7))
        u = np.concatenate([np.linspace(-0.8, 0.8, n) + rng.uniform(-0.08, 0.08, n), [-0.14, 0.14]])  # where each hangs
        length = np.concatenate([rng.uniform(1.3, 2.6, n), rng.uniform(1.6, 2.2, 2)]) * size
        j = dict(size=size, x=rng.uniform(0.08, 0.92) * self.cols,
                 y=rng.uniform(0.2, 0.95) * self.rows if anywhere else self.rows + size + 3,
                 rate=rng.uniform(0.35, 0.6), off=rng.random(), drift=rng.uniform(0, TAU),
                 hue=JELLY_HUES[rng.integers(len(JELLY_HUES))], dim=0.55 + 0.45 * (size - 2.8) / 3.7,
                 u=u, length=length, phase=rng.uniform(0, TAU, n + 2), frilly=np.arange(n + 2) >= n, c=0.0)
        j["w"] = 1.1 * size * CH / CW
        j["hist"] = [(j["x"], j["y"], j["w"])] * HISTORY
        return j

    # the jellies move: each squeeze pushes the bell up, it sinks a little as it relaxes

    def step(self, t, dt):
        for i, j in enumerate(self.jellies):
            c = squeeze((t * j["rate"] + j["off"]) % 1.0)
            j["c"] = c
            j["y"] += (0.9 - 3.4 * c) * (0.6 + 0.4 * j["size"] / 5) * dt
            j["x"] = float(np.clip(j["x"] + 0.7 * np.sin(t * 0.11 + j["drift"]) * dt, 0, self.cols))
            j["w"] = 1.1 * j["size"] * CH / CW * (1 - 0.2 * c)
            j["hist"] = j["hist"][1:] + [(j["x"], j["y"], j["w"])]
            if j["y"] < -j["length"].max() - 2:                          # gone out the top: a new one from below
                self.jellies[i] = self.new_jelly(anywhere=False)

    # drawing, back to front

    def rays(self, t):
        # light slanting down from the surface: soft bands that drift slowly, strongest near the top
        across = self.gc * CW - self.gr * CH * 0.55
        i = (0.5 + 0.5 * np.sin(across * 0.011 + t * 0.12)) * (0.5 + 0.5 * np.sin(across * 0.0043 - t * 0.05 + 1.0))
        return i ** 3.0 * np.exp(-self.gr / (self.rows * 0.55))

    def draw_rays(self, f, t, i):
        # ...glowing in the water behind everything, with a few faint \ strokes where they are brightest
        on = ((self.rand + t * 0.04) % 1.0) < 0.16 * i
        f.char[on] = G("\\")
        f.col[on] = RAY * (0.18 + 0.45 * i[on, None])
        pygame.surfarray.blit_array(self.ray_cells, np.clip(RAY * i[..., None] * 70, 0, 255).astype(np.uint8).transpose(1, 0, 2))
        return pygame.surfarray.array3d(pygame.transform.smoothscale(self.ray_cells, self.canvas.size)).transpose(1, 0, 2)

    def draw_surface(self, f, t):
        x = np.arange(self.cols)
        y = 1.6 + 0.7 * np.sin(x * 0.16 + t * 1.1) + 0.4 * np.sin(x * 0.41 - t * 0.7)
        shine = 0.55 + 0.45 * np.sin(x * 0.23 - t * 1.7)
        glyph = np.where(self.hash[0] % 3 == 0, G("-"), G("~"))
        sparkle = (self.hash[1] % 11 == 0) & (np.sin(t * 2.5 + self.hash[1]) > 0.93)
        glyph = np.where(sparkle, G("*"), glyph)
        f.dots(np.round(y), x, glyph, SURFACE * np.where(sparkle, 1.3, shine)[:, None], move=True)

    def draw_specks(self, f, t):
        s = self.snow
        f.dots((s["y"] + s["fall"] * t) % self.rows, (s["x"] + 0.6 * np.sin(t * 0.5 + s["wob"])) % self.cols,
               s["glyph"], SNOW * s["b"][:, None])
        p = self.plankton
        b = np.clip(np.sin(p["rate"] * t * TAU + p["phase"]), 0, 1) ** 30
        lit = b > 0.05
        x = (p["x"] + 0.3 * np.sin(t * 0.3 + p["phase"])) % self.cols
        f.dots(p["y"][lit], x[lit], np.where(b[lit] > 0.5, G("*"), G("+")), PLANKTON * (0.3 + b[lit, None]))

    def draw_jelly(self, f, j, t):
        c, size = j["c"], j["size"]
        hist = np.array(j["hist"][::-1])                                # newest first

        # tentacles: each point follows where the rim was a moment ago, swaying more toward the tip
        for u, length, ph, frilly in zip(j["u"], j["length"], j["phase"], j["frilly"]):
            n = max(3, int(length / 0.8))
            k = np.arange(n)
            lag = np.minimum((k * 1.1).astype(int), HISTORY - 1)
            sway = (0.6 + 0.10 * k) * (k / n) ** 0.8 * np.sin(t * 1.4 - k * 0.3 + ph) * (1.5 if frilly else 1.0)
            x = hist[lag, 0] + u * hist[lag, 2] * 0.92 + sway
            y = hist[lag, 1] + 0.4 + k * 0.8
            dx, dy = np.diff(x, append=2 * x[-1] - x[-2]), np.diff(y, append=2 * y[-1] - y[-2])
            if frilly:                                                  # the frilly arms in the middle: ( ) { }
                bend = np.sin(t * 1.4 - k * 0.3 + ph) > 0
                glyph = np.where(k % 3 == 0, np.where(bend, G("}"), G("{")), np.where(bend, G(")"), G("(")))
            else:                                                       # fine threads: : where they hang straight
                glyph = stroke_for(dx * CW, -dy * CH)
                glyph = np.where(glyph == G("|"), np.where(k % 2 == 0, G(":"), G("'")), glyph)
            glyph = np.where(k == n - 1, G("."), glyph)
            fade = (0.95 if frilly else 0.65) - (0.45 if frilly else 0.5) * k / n
            f.dots(y, x, glyph, j["hue"] * (j["dim"] * fade * (0.85 + 0.3 * c))[:, None], move=True)

        # the bell: a dome with a scalloped skirt, squeezed narrow and tall on each beat
        x, y = j["x"], j["y"]
        hpx, wpx = size * CH * (1 + 0.12 * c), j["w"] * CW
        r0, r1 = max(int(y - size * 1.2) - 1, 0), min(int(y + 2), self.rows)
        c0, c1 = max(int(x - j["w"]) - 1, 0), min(int(x + j["w"]) + 2, self.cols)
        if r0 >= r1 or c0 >= c1:
            return
        gr, gc = self.gr[r0:r1, c0:c1], self.gc[r0:r1, c0:c1]
        u = (gc + 0.5 - x) * CW / wpx
        v = (gr + 0.5 - y) * CH / hpx
        inside = (u * u + v * v < 1) & (v < 0.12 + 0.07 * np.cos(u * np.pi * 6))
        if not inside.any():
            return
        z = np.sqrt(np.clip(1 - u * u - v * v, 0, None))
        lum = 0.30 + 0.45 * (1 - z)                                     # see-through: the edges glow most
        lum += 0.35 * np.exp(-((v + 0.38) / 0.13) ** 2) * (0.5 + 0.5 * np.cos(u * np.pi * 2.6))   # the gonads
        lum += 0.30 * np.exp(-((u + 0.35) ** 2 + (v + 0.72) ** 2) / 0.05)                         # a highlight
        lum = np.clip(lum * (0.85 + 0.3 * c), 0, 1)
        letters = ramp_pick(BELL_RAMP, lum, self.jitter[r0:r1, c0:c1])
        col = j["hue"] * ((0.25 + 0.85 * lum) * j["dim"])[..., None]

        # the rim: strokes along the dome, _ across the top, ~ along the skirt
        open_ = np.pad(~inside, 1, constant_values=True)
        rim = inside & (open_[:-2, 1:-1] | open_[2:, 1:-1] | open_[1:-1, :-2] | open_[1:-1, 2:])
        rc = stroke_for(v / hpx, u / wpx)
        rc = np.where((np.abs(u) < 0.4) & (v < -0.5), G("_"), rc)
        rc = np.where(v > -0.12, G("~"), rc)
        col = np.where(rim[..., None], j["hue"] * j["dim"] * (1.0 + 0.3 * c), col)
        sub_char, sub_col, sub_move = f.char[r0:r1, c0:c1], f.col[r0:r1, c0:c1], f.move[r0:r1, c0:c1]
        sub_char[inside] = np.where(rim, rc, letters)[inside]
        sub_col[inside] = col[inside]
        sub_move[inside] = False

    def draw_fish(self, f, t):
        tt = t % SCHOOL_PERIOD
        for s in self.schools:
            a = tt - s["t0"]
            if a < 0:
                continue
            travel = s["speed"] * a
            lead = -12 + travel if s["dir"] > 0 else self.cols + 12 - travel
            if not -40 < lead < self.cols + 40:
                continue
            text = FISH_BIG if s["big"] else FISH_SMALL
            text = text if s["dir"] > 0 else flip(text)
            glyphs = [G(ch) for ch in text]
            for behind, dy, ph in zip(s["behind"], s["dy"], s["ph"]):
                x = lead - s["dir"] * behind
                y = s["y"] + dy + 0.6 * np.sin(a * 2.0 + ph)
                start = int(x) - len(text) + 1 if s["dir"] > 0 else int(x)   # the head leads
                f.dots([y] * len(text), start + np.arange(len(text)), glyphs, s["col"] * 0.85)

    def draw_bubbles(self, f, t):
        for v in self.vents:
            base = self.floor[int(v["x"])]
            i = np.arange(max(int((t - base / v["speed"] - 1) / v["gap"]), 0), int(t / v["gap"]) + 1)
            birth = i * v["gap"] + 0.5 * v["gap"] * ((np.sin(i * 12.9898 + v["salt"]) * 43758.5453) % 1.0)
            age = t - birth
            y = base - 0.5 - v["speed"] * age * (1 + 0.15 * age)
            wander = 2.5 * ((np.sin(i * 78.233 + v["salt"]) * 12345.678) % 1.0 - 0.5)   # each its own path
            x = v["x"] + (0.6 + 1.4 * np.minimum(age, 1.0)) * np.sin(age * 2.6 + i) + wander * np.minimum(age / 2, 1.0)
            up = 1 - y / base                                           # 0 at the vent, 1 at the surface
            ok = (age >= 0) & (y > 2.5)
            glyph = np.where(up < 0.2, G("."), np.where(up < 0.6, G("o"), G("O")))
            f.dots(y[ok], x[ok], glyph[ok], BUBBLE * (0.5 + 0.35 * up[ok, None]), move=True)

    def draw_kelp(self, f, t):
        for k in self.kelp:
            n = k["h"]
            i = np.arange(n)
            x = k["x"] + k["sway"] * (i / n) ** 1.3 * np.sin(t * 0.8 + k["phase"] - i * 0.22)
            y = self.floor[int(k["x"])] - 0.5 - i
            dx = np.diff(x, append=2 * x[-1] - x[-2])
            glyph = np.where(dx > 0.35, G("/"), np.where(dx < -0.35, G("\\"), np.where(i % 2 == 0, G("("), G(")"))))
            col = KELP * (k["shade"] * (0.35 + 0.55 * i / n))[:, None]
            f.dots(y, x, glyph, col)
            leaf = (i % 4 == 2) & (i < n - 1)                           # little leaves, alternating sides
            side = np.where(i % 8 == 2, 1, -1)
            f.dots(y[leaf], x[leaf] + side[leaf], np.where(side[leaf] > 0, G(")"), G("(")), col[leaf] * 0.9)

    def draw_floor(self, f, t):
        gr, gc = self.gr, self.gc
        light = np.exp(-self.bed_depth / 2.2)
        caustic = np.clip(np.sin(gc * 0.33 + t * 0.9 + 2 * np.sin(gr * 0.7 - t * 0.4)) * np.sin(gc * 0.13 - t * 0.6), 0, 1) ** 2
        lum = 0.15 + 0.5 * light + 0.35 * caustic * light
        col = SAND * (0.18 + 0.55 * lum)[..., None]
        col = np.where(self.bed_edge[..., None], col * 1.3, col)
        f.cover(self.bed, np.where(self.bed_edge, self.bed_stroke, ramp_pick(SAND_RAMP, lum, self.jitter)), col)

    def frame(self, t):
        f = Frame(self.rows, self.cols)
        light = self.draw_rays(f, t, self.rays(t))
        self.draw_surface(f, t)
        self.draw_specks(f, t)
        jellies = sorted(self.jellies, key=lambda j: j["size"])         # small, far ones behind
        for j in jellies[:len(jellies) // 2]:
            self.draw_jelly(f, j, t)
        self.draw_fish(f, t)
        self.draw_bubbles(f, t)
        for j in jellies[len(jellies) // 2:]:
            self.draw_jelly(f, j, t)
        self.draw_kelp(f, t)
        self.draw_floor(f, t)
        return f, light

    def draw(self, t, hud=True):
        if self.sim_t is None or t < self.sim_t:                        # first frame, restart or new sea
            self.start_jellies()
            self.sim_t = t
            self.step(t, 0.0)
        while self.sim_t < t - 1e-9:
            dt = min(STEP, t - self.sim_t)
            self.sim_t += dt
            self.step(self.sim_t, dt)
        f, light = self.frame(t)
        self.trails.apply(f)
        out = self.canvas.render(f.char, f.col, self.backdrop + light)
        if hud:
            w, h = self.canvas.size
            lines = [(f"{TITLE} · {AUTHOR}", SIGN),
                     (f"jellies {len(self.jellies)}    seed {self.seed}", DIM),
                     ("Space pause · R restart · N new sea · S screenshot · Esc quit", DIM)]
            for i, (text, colour) in enumerate(lines):
                out.blit(self.hud_font.render(text, True, colour), (24, h - 18 - 21 * (len(lines) - i)))
            clock = self.hud_font.render(f"t {t:06.2f}s", True, ACCENT)
            out.blit(clock, (w - 24 - clock.get_width(), 14))
        return out


def main():
    pygame.init()
    return run(Sea(int(sys.argv[1]) if len(sys.argv) > 1 else None), TITLE, None, "jellyfish")


if __name__ == "__main__":
    sys.exit(main())
