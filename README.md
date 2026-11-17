# Moonrise in ASCII

A night scene drawn only in letters, by Clayton Aylor.

![Moonrise in ASCII](images/preview.png)

A big orange moon climbs out from behind three ranges of mountains, cooling to white as it rises.
Its light catches the slopes that face it, drowns the stars near it and lays a path of glints across
the lake, where everything above is mirrored in rippling letters. Now and then a shooting star
crosses the sky, and the water. Every seed draws a new landscape.

## Run it

```
pip install -r requirements.txt
python moonrise.py          # a random landscape
python moonrise.py 7        # a specific one
```

Space pause · R restart · N new landscape · S screenshot · Esc quit

`scene.py` is the original sketch: a still version printed straight to the terminal, no
dependencies needed.

```
python3 scene.py [seed] [width] [height]
```

## How it works

- **Mountains:** each range's ridge is fractal noise folded at zero for sharp peaks. Edges use the
  stroke that follows the slope (`/ | \ - _ ^`), and slopes that face the moon catch its light.
- **Moon:** a disk measured in pixels so it stays round on tall cells, shaded toward the rim and
  in the craters, filled with letters picked by brightness.
- **Lake:** every row above the horizon is mirrored, shifted sideways by ripples, flipped where it
  matters (`/` to `\`, `^` to `v`) and broken by drifting streaks, with glints under the moon.
- **Drawing:** each glyph's coverage mask times its cell's colour, a two-scale glow blurred per
  cell, and trails that let moving letters linger and fade.

Python · NumPy · pygame-ce
