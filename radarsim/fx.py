"""2.5D look: pre-rendered, lit hardware sprites and CRT glass effects.

No 3D engine. Every piece of equipment is described as a small height map
(how far each pixel stands proud of the panel) plus a material, and is lit
ONCE with a fixed lamp above-left of the console (Lambert + Blinn specular).
The results are cached as ordinary 2D sprites. Knobs are rendered per
rotation angle so the flutes and pointer turn while the highlights stay put,
which is what makes them read as solid objects.

CRT faces are drawn live by the stations and then passed through a cheap
phosphor bloom, scan-line / vignette mask and a glass reflection.
"""
import math
import numpy as np
import pygame

_L = np.array([-0.44, -0.62, 0.65])
_L /= np.linalg.norm(_L)
_H = _L + np.array([0, 0, 1.0])
_H /= np.linalg.norm(_H)
_rng = np.random.default_rng(1986)
_cache = {}


# ------------------------------------------------------------------ basics
def grid(w, h):
    x, y = np.mgrid[0:w, 0:h]
    return x.astype(np.float64), y.astype(np.float64)


def sstep(t):
    t = np.clip(t, 0, 1)
    return t * t * (3 - 2 * t)


def shade(h, albedo, spec=0.25, gloss=20.0, amb=0.45):
    """Light a height map (indexed [x, y]). Flat areas come out as albedo."""
    gx, gy = np.gradient(h)
    inv = 1.0 / np.sqrt(gx * gx + gy * gy + 1.0)
    nx, ny, nz = -gx * inv, -gy * inv, inv
    d = np.clip(nx * _L[0] + ny * _L[1] + nz * _L[2], 0, None) / _L[2]
    s = np.clip(nx * _H[0] + ny * _H[1] + nz * _H[2], 0, 1) ** gloss - _H[2] ** gloss
    lit = amb + (1 - amb) * d
    alb = np.asarray(albedo, dtype=np.float64)
    if alb.ndim == 1:
        alb = alb[None, None, :]
    return np.clip(alb * lit[..., None] + (255.0 * spec) * np.clip(s, 0, None)[..., None], 0, 255)


def surf(rgb, alpha=None):
    w, h = rgb.shape[:2]
    if alpha is None:
        s = pygame.Surface((w, h))
        pygame.surfarray.blit_array(s, np.clip(rgb, 0, 255).astype(np.uint8))
        return s
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    a = pygame.surfarray.pixels3d(s)
    a[:] = np.clip(rgb, 0, 255).astype(np.uint8)
    del a
    a = pygame.surfarray.pixels_alpha(s)
    a[:] = np.clip(alpha, 0, 255).astype(np.uint8)
    del a
    return s


def _fast(s, alpha=False):
    try:
        return s.convert_alpha() if alpha else s.convert()
    except pygame.error:
        return s


def down(s, f):
    return pygame.transform.smoothscale(s, (max(1, s.get_width() // f), max(1, s.get_height() // f)))


def noise(w, h, cell):
    """Smooth value noise in 0..1."""
    sw, sh = max(2, w // cell + 2), max(2, h // cell + 2)
    a = (_rng.random((sw, sh)) * 255).astype(np.uint8)
    s = pygame.Surface((sw, sh))
    pygame.surfarray.blit_array(s, np.dstack([a, a, a]))
    s = pygame.transform.smoothscale(s, (w, h))
    return pygame.surfarray.array3d(s)[:, :, 0] / 255.0


def rrect_sd(x, y, w, h, rad):
    """Signed distance to a rounded rectangle filling (0,0,w,h); <0 inside."""
    qx = np.abs(x - (w - 1) / 2.0) - (w / 2.0 - rad)
    qy = np.abs(y - (h - 1) / 2.0) - (h / 2.0 - rad)
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - rad


def light_at(x, y):
    """Room lighting: one hooded lamp above the middle of the console."""
    f = 1.10 - 0.30 * ((x - 800.0) / 800.0) ** 2 - 0.34 * np.clip((y - 180.0) / 720.0, 0, None) ** 1.6
    return np.clip(f, 0.45, 1.15)


# ------------------------------------------------------------ panel plates
def screw(i=0):
    k = ("screw", i % 4)
    if k not in _cache:
        S, r = 4, 5
        n = (2 * r + 2) * S
        x, y = grid(n, n)
        cx = (n - 1) / 2.0
        dx, dy = x - cx, y - cx
        rho = np.hypot(dx, dy) / (r * S)
        ang = [0.5, 2.1, 1.2, 2.8][i % 4]
        v = np.abs(dx * math.sin(ang) - dy * math.cos(ang)) / (r * S)
        hgt = np.where(rho < 1, 2.6 * S * np.sqrt(np.clip(1 - rho * rho, 0, 1)) * 0.55, 0)
        hgt -= np.where((v < 0.16) & (rho < 0.92), 1.6 * S * sstep((0.16 - v) / 0.1), 0)
        rgb = shade(hgt, (118, 120, 124), spec=0.9, gloss=28, amb=0.3)
        al = 255 * sstep((1.02 - rho) / 0.06)
        _cache[k] = _fast(down(surf(rgb, al), S), True)
    return _cache[k]


def plate(rect, base=(50, 54, 57), screws=True, grain=1.0):
    """Wrinkle-painted steel panel, lit for its position on the console."""
    r = pygame.Rect(rect)
    k = ("plate", r.x, r.y, r.w, r.h, base, screws)
    if k not in _cache:
        w, h = r.w, r.h
        x, y = grid(w, h)
        d = np.minimum(np.minimum(x, w - 1 - x), np.minimum(y, h - 1 - y))
        hgt = np.minimum(d, 3.0) * 0.9 + (_rng.random((w, h)) * 0.42 + noise(w, h, 3) * 1.1) * grain
        alb = np.asarray(base, dtype=np.float64)[None, None, :] * (0.88 + 0.24 * noise(w, h, 56))[..., None]
        rgb = shade(hgt, alb, spec=0.16, gloss=7, amb=0.52)
        rgb *= light_at(r.x + x, r.y + y)[..., None]
        rgb[d < 1] *= 0.35
        s = surf(rgb)
        if screws and w > 120 and h > 80:
            for i, (px, py) in enumerate(((9, 9), (w - 10, 9), (9, h - 10), (w - 10, h - 10))):
                sc = screw(i + r.x // 7)
                s.blit(sc, (px - sc.get_width() // 2, py - sc.get_height() // 2))
        _cache[k] = _fast(s)
    return _cache[k]


def strip(rect, base=(40, 42, 46)):
    """Brushed-metal rail (header / footer of the console)."""
    r = pygame.Rect(rect)
    k = ("strip", r.x, r.y, r.w, r.h, base)
    if k not in _cache:
        w, h = r.w, r.h
        x, y = grid(w, h)
        rows = _rng.random(h) * 0.5 + 0.75
        streak = rows[None, :] * (0.9 + 0.2 * noise(w, h, 90)) * (0.94 + 0.12 * _rng.random((w, h)))
        d = np.minimum(y, h - 1 - y)
        rgb = shade(np.minimum(d, 2.0), np.asarray(base)[None, None, :] * streak[..., None], spec=0.3, gloss=10)
        rgb *= light_at(r.x + x, r.y + y * 0 + 120)[..., None]
        _cache[k] = _fast(surf(rgb))
    return _cache[k]


# ----------------------------------------------------- recessed displays
M = 7          # width of the bezel wall around a recessed display


def well(w, h, tint=(0, 0, 0), rad=6):
    """Bezel of a display set back into the panel: four alpha strips."""
    k = ("well", w, h, tint, rad)
    if k not in _cache:
        W, H = w + 2 * M, h + 2 * M
        x, y = grid(W, H)
        e = rrect_sd(x - M, y - M, w, h, rad)                 # >0 outside the glass
        t = np.clip(e / (M - 2.0), 0, 1)
        hgt = np.where(e <= 0, -7.0, -7.0 * (1 - t))
        hgt = hgt + np.where(e > M - 2.5, 1.6 * np.sin(np.clip((e - (M - 2.5)) / 2.5, 0, 1) * math.pi), 0)
        alb = np.array([34, 36, 39.0])[None, None, :] * (0.9 + 0.2 * _rng.random((W, H)))[..., None]
        rgb = shade(hgt, alb, spec=0.5, gloss=14, amb=0.35)
        glow = (1 - t) * (e > 0)
        rgb += np.asarray(tint, dtype=np.float64)[None, None, :] * (0.16 * glow)[..., None]
        al = 255 * sstep((M + 0.5 - e) / 1.2) * (e > -0.8)
        full = surf(rgb, al)
        c = M + rad
        parts = [((0, 0), (0, 0, W, c)), ((0, H - c), (0, H - c, W, c)),
                 ((0, c), (0, c, c, H - 2 * c)), ((W - c, c), (W - c, c, c, H - 2 * c))]
        _cache[k] = [(off, _fast(full.subsurface(pygame.Rect(src)).copy(), True)) for off, src in parts if src[2] > 0 and src[3] > 0]
    return _cache[k]


def draw_well(s, rect, bg=(4, 9, 8), tint=(0, 0, 0)):
    r = pygame.Rect(rect)
    s.fill(bg, r)
    for (ox, oy), part in well(r.w, r.h, tint):
        s.blit(part, (r.x - M + ox, r.y - M + oy))


def glass(w, h, kind):
    """(multiply mask, additive reflection) for a display face."""
    k = ("glass", w, h, kind)
    if k not in _cache:
        x, y = grid(w, h)
        e = -rrect_sd(x, y, w, h, 7)                          # depth inside the glass
        m = np.ones((w, h))
        m *= 0.50 + 0.50 * sstep(e / 9.0)                     # wall shadow all round
        m *= 0.72 + 0.28 * sstep(np.minimum(x, y * 1.4) / 26.0)   # deeper under the top-left lip
        if kind == "crt":
            m *= 1.0 - 0.13 * (y.astype(int) % 3 == 2)        # scan lines
            u, v = (x - w / 2) / (w / 2), (y - h / 2) / (h / 2)
            m *= 1.0 - 0.30 * np.clip(u * u * v * v * 1.6 + 0.12 * (u * u + v * v), 0, 1)
        m[e < 0] = 0.06
        mult = surf(np.dstack([m, m, m]) * 255)
        band = np.exp(-((x * 0.55 + y - 0.32 * (w * 0.55 + h)) / (0.10 * (w + h))) ** 2)
        band2 = np.exp(-((x * 0.55 + y - 0.47 * (w * 0.55 + h)) / (0.03 * (w + h))) ** 2)
        top = np.exp(-y / (h * 0.16 + 6.0)) * (0.6 + 0.4 * np.exp(-((x - w * 0.3) / (w * 0.45)) ** 2))
        a = (band * 7.0 + band2 * 4.0 + top * (9.0 if kind == "crt" else 6.0)) * (e > 1)
        add = surf(np.dstack([a * 0.92, a, a * 1.06]))
        _cache[k] = (_fast(mult), _fast(add))
    return _cache[k]


def bloom(s, rect, gain=150):
    """Phosphor glow: add a blurred copy of the region to itself."""
    r = pygame.Rect(rect).clip(s.get_rect())
    if r.w < 16 or r.h < 16:
        return
    sub = s.subsurface(r)
    sm = pygame.transform.smoothscale(sub, (max(2, r.w // 4), max(2, r.h // 4)))
    s2 = pygame.transform.smoothscale(sm, (max(2, r.w // 10), max(2, r.h // 10)))
    sm.blit(pygame.transform.smoothscale(s2, sm.get_size()), (0, 0), special_flags=pygame.BLEND_RGB_ADD)
    sm.fill((gain, gain, gain), special_flags=pygame.BLEND_RGB_MULT)
    sub.blit(pygame.transform.smoothscale(sm, r.size), (0, 0), special_flags=pygame.BLEND_RGB_ADD)


def finish_glass(s, rect, kind, gain=150):
    r = pygame.Rect(rect)
    if gain:
        bloom(s, r, gain)
    mult, add = glass(r.w, r.h, kind)
    s.blit(mult, r, special_flags=pygame.BLEND_RGB_MULT)
    s.blit(add, r, special_flags=pygame.BLEND_RGB_ADD)


def round_glass(R):
    """(multiply, add) pair for a circular CRT face of radius R."""
    k = ("rglass", R)
    if k not in _cache:
        n = 2 * R + 1
        x, y = grid(n, n)
        dx, dy = (x - R) / R, (y - R) / R
        rho = np.hypot(dx, dy)
        m = (0.42 + 0.58 * sstep((1 - rho) / 0.07)) * (1.0 - 0.22 * rho ** 3)
        m *= 0.80 + 0.20 * sstep((1 - np.hypot(dx - 0.05, dy - 0.07)) / 0.16)
        m[rho > 1] = 1.0
        hi = np.exp(-(((dx + 0.42) / 0.42) ** 2 + ((dy + 0.50) / 0.20) ** 2)) * 15.0
        hi += np.exp(-(((dx - 0.30) / 0.5) ** 2 + ((dy - 0.74) / 0.07) ** 2)) * 4.0
        hi += 5.0 * np.clip(1 - np.abs(rho - 0.965) / 0.03, 0, 1) * np.clip(-(dx + dy) * 0.7, 0, 1)
        hi *= rho < 0.995
        _cache[k] = (_fast(surf(np.dstack([m, m, m]) * 255)), _fast(surf(np.dstack([hi * 0.9, hi, hi * 1.05]))))
    return _cache[k]


# ------------------------------------------------------------------ knobs
def knob_shadow(r):
    k = ("kshadow", r)
    if k not in _cache:
        n = 2 * r + 30
        x, y = grid(n, n)
        rho = np.hypot(x - n / 2.0 + 4, y - n / 2.0 + 7 - 12) / r
        al = 190 * sstep((1.22 - np.hypot(x - n / 2.0 - 3, y - n / 2.0 - 5) / r) / 0.42)
        _cache[k] = _fast(surf(np.zeros((n, n, 3)), al), True)
        del rho
    return _cache[k]


def knob(r, angle, style="fluted"):
    """Top view of a control knob of radius r turned to `angle` degrees."""
    q = round(angle / 3.0) * 3 % 360 if style != "bar" else round(angle) % 360
    k = ("knob", r, q, style)
    if k in _cache:
        return _cache[k]
    S = 3
    R = r * S
    n = 2 * (r + 3) * S
    x, y = grid(n, n)
    c = (n - 1) / 2.0
    dx, dy = x - c, y - c
    rho = np.hypot(dx, dy) / R
    a = math.radians(q)
    u = (dx * math.sin(a) - dy * math.cos(a)) / R              # along the pointer
    v = (dx * math.cos(a) + dy * math.sin(a)) / R              # across it
    th = np.arctan2(v, u)
    if style == "bar":
        base = rho < 0.93
        hgt = np.where(base, 1.6 * S * sstep((0.93 - rho) / 0.06), 0.0)
        wv = np.where(u < 0.25, 0.31, 0.31 - 0.25 * (u - 0.25) / 0.73)
        inside = (np.abs(v) < wv) & (u > -0.82) & (u < 0.98)
        prof = np.sqrt(np.clip(1 - (v / np.maximum(wv, 1e-3)) ** 2, 0, 1)) ** 0.6
        endf = sstep((u + 0.82) / 0.12) * sstep((0.98 - u) / 0.07)
        hgt = np.where(inside, 1.6 * S + 9.5 * S * prof * endf, hgt)
        alb = np.where(inside[..., None], np.array([24, 24, 26.0]), np.array([74, 77, 82.0]) * (0.85 + 0.3 * np.abs(np.sin(th * 2 + a))[..., None]))
        line = inside & (np.abs(v) < 0.055) & (u > 0.12) & (u < 0.9)
        alb = np.where(line[..., None], np.array([238, 236, 224.0]), alb)
        rgb = shade(hgt, alb, spec=0.55, gloss=26, amb=0.36)
        al = 255 * sstep((0.95 - rho) / 0.03)
        al = np.maximum(al, 255 * inside)
    else:
        nfl = 36 if style == "spun" else 10
        depth = 0.022 if style == "spun" else 0.075
        edge = 0.85 - depth * (0.5 - 0.5 * np.cos(nfl * th)) ** 1.4
        body = rho < edge
        hgt = np.where(rho < 1, 2.4 * S * np.clip((1 - rho) / 0.15, 0, 1), 0.0)
        wall = sstep((edge - rho) / 0.085)
        hgt = np.where(body, 2.4 * S + 8.5 * S * wall + 1.6 * S * (1 - (rho / edge) ** 2), hgt)
        if style == "spun":
            top = rho < edge - 0.10
            ths = np.arctan2(dy, dx)
            spun = 118 + 78 * np.abs(np.cos(ths - 0.9)) ** 3 + 30 * np.abs(np.cos(2 * ths + 0.4))
            ring = 1.0 + 0.05 * np.sin(rho * R * 1.9)
            alb = np.where(top[..., None], (spun * ring)[..., None] * np.array([1.0, 1.0, 1.04]), np.array([26, 26, 28.0]))
            dd = np.hypot(u - 0.50, v) / 0.17
            hgt -= np.where(dd < 1, 3.4 * S * (1 - dd * dd), 0)
            alb = np.where((dd < 1)[..., None], np.array([44, 45, 48.0]), alb)
            rgb = shade(hgt, alb, spec=0.5, gloss=22, amb=0.42)
        else:
            alb = np.where(body[..., None], np.array([33, 33, 36.0]), np.array([42, 42, 46.0]))
            line = (np.abs(v) < 0.075) & (u > 0.18) & (rho < edge - 0.03)
            alb = np.where(line[..., None], np.array([240, 238, 226.0]), alb)
            skl = (np.abs(v) < 0.045) & (u > 0.86) & (rho < 0.985)
            alb = np.where(skl[..., None], np.array([240, 238, 226.0]), alb)
            rgb = shade(hgt, alb, spec=0.6, gloss=30, amb=0.34)
        al = 255 * sstep((1.0 - rho) / 0.02)
    out = _fast(down(surf(rgb, al), S), True)
    if len(_cache) > 9000:
        _cache.clear()
    _cache[k] = out
    return out


# ---------------------------------------------------------------- buttons
def button(w, h, color, lit, pressed):
    """Illuminated legend push-button in a black bezel."""
    k = ("btn", w, h, color, lit, pressed)
    if k not in _cache:
        S = 2
        W, H = w * S, h * S
        x, y = grid(W, H)
        e = -rrect_sd(x, y, W, H, 5 * S)                      # inside distance, whole switch
        cap = e - 3.2 * S                                     # inside distance, lens cap
        hgt = np.minimum(e, 2.0 * S) * 0.9
        up = 1.4 if pressed else 4.2
        hgt = np.where(cap > 0, 1.8 * S - 1.6 * S + up * S * sstep(cap / (2.6 * S)) + 0.6 * S * sstep(cap / (min(W, H) * 0.5)), hgt)
        hgt = np.where((cap <= 0) & (cap > -1.2 * S), 0.4 * S, hgt)
        col = np.asarray(color, dtype=np.float64)
        if lit:
            u, v = (x - W / 2) / (W / 2), (y - H / 2) / (H / 2)
            hot = np.exp(-(u * u * 1.1 + v * v * 1.6))
            em = col[None, None, :] * (0.62 + 0.42 * hot)[..., None] + 105 * (hot ** 2)[..., None]
            sh = shade(hgt, np.array([255, 255, 255.0]), spec=0.2, gloss=20, amb=0.78) / 255.0
            body = shade(hgt, np.array([22, 23, 25.0]), spec=0.5, gloss=18)
            rgb = np.where((cap > 0)[..., None], em * sh, body)
        else:
            dark = col * 0.10 + np.array([40, 42, 46.0])
            alb = np.where((cap > 0)[..., None], dark[None, None, :], np.array([22, 23, 25.0]))
            rgb = shade(hgt, alb, spec=0.55, gloss=24, amb=0.42)
            if pressed:
                rgb *= 0.86
        al = 255 * sstep((e + 0.5) / 1.0)
        _cache[k] = _fast(down(surf(rgb, al), S), True)
    return _cache[k]


def halo(w, h, color, strength=0.34, spread=16):
    """Additive light spill around something lit (blit with BLEND_RGB_ADD)."""
    k = ("halo", w, h, color, strength, spread)
    if k not in _cache:
        W, H = w + 2 * spread, h + 2 * spread
        x, y = grid(W, H)
        e = np.clip(rrect_sd(x - spread, y - spread, w, h, 6), 0, None)
        f = np.exp(-e / (spread * 0.36)) * strength
        _cache[k] = _fast(surf(np.asarray(color, dtype=np.float64)[None, None, :] * f[..., None]))
    return _cache[k]


def lamp(r, color, on):
    """Jewelled indicator lamp in a chrome bezel."""
    k = ("lamp", r, color, on)
    if k not in _cache:
        S = 4
        R = (r + 2.5) * S
        n = int(2 * R + 2 * S)
        x, y = grid(n, n)
        c = (n - 1) / 2.0
        dx, dy = (x - c) / R, (y - c) / R
        rho = np.hypot(dx, dy)
        lens = rho < 0.70
        hgt = np.where(lens, 0.9 * R * np.sqrt(np.clip(1 - (rho / 0.74) ** 2, 0, 1)) * 0.55,
                       0.26 * R * np.sin(np.clip((1 - rho) / 0.30, 0, 1) * math.pi))
        col = np.asarray(color, dtype=np.float64)
        chrome = shade(hgt, np.array([150, 152, 158.0]), spec=0.95, gloss=18, amb=0.3)
        if on:
            core = np.exp(-(rho / 0.42) ** 2)
            em = col[None, None, :] * (0.72 + 0.4 * core)[..., None] + 150 * (core ** 2)[..., None]
            gl = shade(hgt, np.array([255, 255, 255.0]), spec=0.5, gloss=40, amb=0.85) / 255.0
            lensrgb = em * gl
        else:
            lensrgb = shade(hgt, col * 0.20 + 14, spec=0.75, gloss=38, amb=0.4)
        rgb = np.where(lens[..., None], lensrgb, chrome)
        al = 255 * sstep((1.0 - rho) / 0.04)
        _cache[k] = _fast(down(surf(rgb, al), S), True)
    return _cache[k]


def glow(r, color, strength=0.5):
    k = ("glow", r, color, strength)
    if k not in _cache:
        n = r * 8
        x, y = grid(n, n)
        f = np.exp(-(np.hypot(x - n / 2.0, y - n / 2.0) / (r * 1.5)) ** 1.5) * strength
        _cache[k] = _fast(surf(np.asarray(color, dtype=np.float64)[None, None, :] * f[..., None]))
    return _cache[k]


def guard(w, h, is_open, pressed):
    """Distress button: mushroom push under a hinged, striped safety cover."""
    k = ("guard", w, h, is_open, pressed)
    if k not in _cache:
        S = 2
        W, H = w * S, h * S
        x, y = grid(W, H)
        e = -rrect_sd(x, y, W, H, 8 * S)
        if is_open:
            hgt = np.minimum(e, 3.0 * S) * 0.8 - 4.0 * S * sstep((e - 4 * S) / (4.0 * S))
            alb = np.where((e > 5 * S)[..., None], np.array([20, 20, 22.0]), np.array([150, 28, 22.0]))
            R = min(W, H) * 0.34
            rho = np.hypot(x - W / 2.0, y - H / 2.0 - 2 * S) / R
            dome = rho < 1
            hgt = np.where(dome, -4.0 * S + (4.0 if pressed else 9.0) * S + R * 0.42 * np.sqrt(np.clip(1 - rho ** 2, 0, 1)), hgt)
            red = np.array([232, 34, 26.0]) if not pressed else np.array([255, 120, 100.0])
            alb = np.where(dome[..., None], red, alb)
            rgb = shade(hgt, alb, spec=0.75, gloss=26, amb=0.38)
            lid = (y < 7 * S) & (e > 0)                       # cover standing open, seen edge-on
            rgb[lid] = rgb[lid] * 0.35 + np.array([170, 40, 30.0]) * 0.65 * (0.7 + 0.5 * (y[lid] / (7.0 * S)))[:, None]
        else:
            hgt = np.minimum(e, 4.0 * S) * 1.5 + 2.5 * S * sstep(e / (min(W, H) * 0.5))
            stripe = ((x + y) // (9 * S)).astype(int) % 2 == 0
            border = e < 7 * S
            alb = np.where((border & stripe)[..., None], np.array([226, 190, 30.0]),
                           np.where(border[..., None], np.array([24, 24, 24.0]), np.array([190, 26, 20.0])))
            rgb = shade(hgt, alb, spec=0.85, gloss=22, amb=0.42)
            hinge = (y < 5 * S) & (np.abs(x - W / 2.0) < W * 0.32) & (e > 0)
            rgb[hinge] = shade(np.where(hinge, 3.0 * S * np.sin(np.clip(y / (5.0 * S), 0, 1) * math.pi), 0),
                               np.array([120, 122, 128.0]), spec=0.9, gloss=16)[hinge]
        al = 255 * sstep((e + 0.5) / 1.0)
        _cache[k] = _fast(down(surf(rgb, al), S), True)
    return _cache[k]


def module(w, h, sel):
    """Small raised equipment module (block-diagram card)."""
    k = ("module", w, h, sel)
    if k not in _cache:
        S = 2
        W, H = w * S, h * S
        x, y = grid(W, H)
        e = -rrect_sd(x, y, W, H, 6 * S)
        hgt = np.minimum(e, 3.0 * S) * 1.3 + _rng.random((W, H)) * 0.5
        base = np.array([78, 86, 98.0]) if sel else np.array([56, 62, 70.0])
        rgb = shade(hgt, base[None, None, :] * (0.9 + 0.2 * noise(W, H, 30))[..., None], spec=0.3, gloss=12, amb=0.5)
        _cache[k] = _fast(down(surf(rgb, 255 * sstep((e + 0.5) / 1.0)), S), True)
    return _cache[k]


def radar_housing(w, h, cx, cy, R, y0):
    """Cast housing of the PPI with its raised, edge-lit bearing ring."""
    k = ("housing", w, h, cx, cy, R)
    if k not in _cache:
        x, y = grid(w, h)
        d = np.hypot(x - cx, y - cy)
        o = d - R                                             # distance outside the tube face
        hgt = _rng.random((w, h)) * 0.4 + noise(w, h, 3) * 1.0
        collar = (o > 0) & (o < 40)
        prof = np.where(o < 6, -12.0 + 18.0 * sstep(o / 6.0), np.where(o < 34, 6.0, 6.0 * (1 - sstep((o - 34) / 6.0))))
        hgt = np.where(collar, prof, hgt)
        alb = np.array([50, 54, 57.0])[None, None, :] * (0.88 + 0.24 * noise(w, h, 56))[..., None]
        alb = np.where(collar[..., None], np.array([30, 31, 33.0]), alb)
        rgb = shade(hgt, alb, spec=0.3, gloss=9, amb=0.5)
        rgb *= light_at(x, y + y0)[..., None]
        rgb += np.array([10, 34, 18.0])[None, None, :] * (np.clip(1 - o / 7.0, 0, 1) * (o > 0))[..., None]   # tube light on the inner wall
        _cache[k] = surf(rgb, np.where(o > 0, 255, 0))
    return _cache[k]


# ------------------------------------------------- toggles and breakers
def _hexr(ang, r):
    """Radius of a hexagon (flats top and bottom) as a function of angle."""
    return r / np.cos(((ang + np.pi / 6) % (np.pi / 3)) - np.pi / 6)


def toggle(on, style="bat", tripped=False):
    """Bat-handle toggle switch in a hex nut, or a moulded circuit breaker.
    Seen from the operator's position: the lever stands out of the panel
    towards you, so it is lit on its upper face and throws a shadow down and
    to the right."""
    k = ("toggle", bool(on), style, bool(tripped))
    if k in _cache:
        return _cache[k]
    S = 3
    w, h = 34, 52
    W, H = w * S, h * S
    x, y = grid(W, H)
    cx, cy = (W - 1) / 2.0, (H - 1) / 2.0
    dx, dy = (x - cx) / S, (y - cy) / S
    if style == "breaker":
        bw, bh = 13.0, 20.0
        e = rrect_sd(dx + bw, dy + bh, 2 * bw, 2 * bh, 3.0)
        body = e < 0
        hgt = np.where(body, 4.0 * sstep(-e / 1.5), 0.0)
        slot = (np.abs(dx) < 4.6) & (np.abs(dy) < 13.0)
        hgt = np.where(slot, 1.0, hgt)
        alb = np.where(body[..., None], np.array([30, 30, 33.0]), np.array([0, 0, 0.0]))
        alb = np.where(slot[..., None], np.array([12, 12, 13.0]), alb)
        pos = 0.0 if tripped else (-7.5 if on else 7.5)
        lev = (np.abs(dx) < 4.0) & (np.abs(dy - pos) < 5.0)
        prof = np.sqrt(np.clip(1 - (dx / 4.0) ** 2, 0, 1))
        hgt = np.where(lev, 6.0 + 4.0 * prof - 1.5 * ((dy - pos) / 5.0) * (1 if on else -1), hgt)
        alb = np.where(lev[..., None], np.array([235, 233, 222.0]) if not tripped else np.array([240, 140, 40.0]), alb)
        if tripped:
            flag = slot & ~lev & (np.abs(dy) < 9)
            alb = np.where(flag[..., None], np.array([230, 110, 20.0]), alb)
        rgb = shade(hgt * S, alb, spec=0.55, gloss=20, amb=0.4)
        sh = rrect_sd(dx + bw - 2.5, dy + bh - 3.5, 2 * bw, 2 * bh, 3.0) < 0
        al = np.where(body, 255, np.where(sh, 120, 0))
        rgb = np.where(body[..., None], rgb, 0)
    else:
        ang = np.arctan2(dy, dx)
        rr = np.hypot(dx, dy)
        hr = _hexr(ang, 9.0)
        nut = rr < hr
        hgt = np.where(nut, 2.6 * sstep((hr - rr) / 1.1), 0.0)
        bush = rr < 5.3
        thread = 0.25 * np.sin(rr * 9.0)
        hgt = np.where(bush, 2.6 + 2.0 * sstep((5.3 - rr) / 0.9) + thread, hgt)
        alb = np.where(nut[..., None], np.array([150, 152, 157.0]), np.array([0, 0, 0.0]))
        sgn = -1.0 if on else 1.0
        L = 15.0
        if tripped:
            L = 3.0
        along = dy * sgn
        tpar = np.clip(along / L, 0, 1)
        rad = 2.4 - 0.5 * tpar
        shaft = (along > -1.5) & (along < L) & (np.abs(dx) < rad)
        tip = (dx / 3.2) ** 2 + ((along - L) / 4.3) ** 2 < 1.0
        lever = shaft | tip
        lh = 6.0 + 9.0 * tpar + 1.6 * np.sqrt(np.clip(1 - (dx / np.where(tip, 3.2, rad)) ** 2, 0, 1))
        hgt = np.where(lever, np.maximum(hgt, lh), hgt)
        alb = np.where(lever[..., None], np.array([212, 214, 220.0]), alb)
        rgb = shade(hgt * S, alb, spec=0.95, gloss=34, amb=0.33)
        # cast shadow of the lever, down and to the right
        sa = (dy - 4.5) * sgn
        sp = np.clip(sa / L, 0, 1)
        shl = (((sa > -1.5) & (sa < L) & (np.abs(dx - 3.0) < 2.6)) |
               ((((dx - 3.0) / 3.4) ** 2 + ((sa - L) / 4.5) ** 2) < 1.0))
        shadow = shl & ~nut & ~lever
        nsh = (rr > hr) & (np.hypot(dx - 2.0, dy - 2.5) < _hexr(np.arctan2(dy - 2.5, dx - 2.0), 9.0))
        al = np.where(nut | lever, 255, np.where(shadow, 130 * (1 - 0.4 * sp), np.where(nsh, 90, 0)))
        rgb = np.where((nut | lever)[..., None], rgb, 0)
    out = _fast(down(surf(rgb, al), S), True)
    _cache[k] = out
    return out


def thumbwheel(w, h):
    """Housing and drum of a thumbwheel switch (the digit is drawn live)."""
    k = ("thumb", w, h)
    if k not in _cache:
        S = 3
        W, H = w * S, h * S
        x, y = grid(W, H)
        e = -rrect_sd(x, y, W, H, 3 * S)
        win = (np.abs(x - W / 2.0) < W * 0.36) & (np.abs(y - H / 2.0) < H * 0.27)
        hgt = np.minimum(e, 2.0 * S) * 0.9
        v = (y - H / 2.0) / (H * 0.27)
        drum = np.sqrt(np.clip(1 - v * v, 0, 1))
        hgt = np.where(win, -1.5 * S + 2.5 * S * drum, hgt)
        rib = (~win) & (np.abs(x - W / 2.0) < W * 0.32) & ((np.abs(y - H * 0.11) < H * 0.05) | (np.abs(y - H * 0.89) < H * 0.05))
        hgt = np.where(rib, hgt + 1.4 * S, hgt)
        alb = np.where(win[..., None], (np.array([18, 18, 20.0]) + 40 * drum[..., None]), np.array([36, 37, 40.0]))
        alb = np.where(rib[..., None], np.array([70, 72, 76.0]), alb)
        rgb = shade(hgt, alb, spec=0.5, gloss=18, amb=0.42)
        _cache[k] = _fast(down(surf(rgb, 255 * sstep((e + 0.5) / 1.0)), S), True)
    return _cache[k]


def paper(w, h):
    """A strip of thermal / dot-matrix printer paper coming out of a slot."""
    k = ("paper", w, h)
    if k not in _cache:
        x, y = grid(w, h)
        base = np.array([226, 222, 204.0])[None, None, :] * (0.96 + 0.04 * noise(w, h, 7))[..., None]
        base = base * (0.93 + 0.07 * sstep(np.minimum(x, w - 1 - x) / 10.0))[..., None]
        hole = ((x % 1 == 0) & False)
        rgb = shade(noise(w, h, 2) * 0.6, base, spec=0.05, gloss=6, amb=0.85)
        rgb[hole] = 40
        _cache[k] = _fast(surf(rgb))
    return _cache[k]
