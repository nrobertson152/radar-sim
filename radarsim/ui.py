"""Panel widgets: knobs, selectors, buttons, guarded buttons, meters, LCDs.

Everything is drawn on a fixed 1600x900 logical canvas (pygame.SCALED handles
the window scaling), so all coordinates in the stations are absolute pixels.
"""
import math
import pygame
from . import fx

W, H = 1600, 900
TOP, BOT = 46, 866          # station area is between the tab bar and status bar

C = {
    "bg": (13, 15, 18), "panel": (33, 37, 43), "panel2": (45, 50, 58),
    "edge": (72, 79, 90), "text": (208, 213, 220), "dim": (125, 134, 146),
    "amber": (255, 178, 46), "green": (70, 255, 120), "red": (255, 66, 56),
    "cyan": (90, 215, 255), "blue": (80, 140, 255), "yellow": (255, 236, 90),
    "lcd": (12, 22, 17), "lcdfg": (120, 255, 170), "black": (0, 0, 0),
    "white": (240, 242, 245), "off": (52, 56, 62),
}

MOUSE = [0, 0]              # logical mouse position, kept current by the app
_MONO = "dejavusansmono,consolas,menlo,liberationmono,couriernew,courier"
_SANS = "dejavusans,segoeui,arial,helvetica,liberationsans"
_fonts, _tc, _wc = {}, {}, {}


def font(size, bold=False, mono=True):
    k = (size, bold, mono)
    if k not in _fonts:
        path = pygame.font.match_font(_MONO if mono else _SANS, bold=bold)
        _fonts[k] = pygame.font.Font(path, size)
    return _fonts[k]


def text(s, msg, pos, size=13, color=None, bold=False, align="l", mono=True):
    """Draw cached text. align: l / c (mid-top) / r / m (centre)."""
    color = color or C["text"]
    msg = str(msg)
    k = (msg, size, color, bold, mono)
    img = _tc.get(k)
    if img is None:
        if len(_tc) > 6000:
            _tc.clear()
        img = _tc[k] = font(size, bold, mono).render(msg, True, color)
    r = img.get_rect()
    if align == "l":
        r.topleft = pos
    elif align == "c":
        r.midtop = pos
    elif align == "r":
        r.topright = pos
    else:
        r.center = pos
    s.blit(img, r)
    return r


def wrap(msg, size, width, mono=True, bold=False):
    k = (msg, size, width, mono, bold)
    if k in _wc:
        return _wc[k]
    f = font(size, bold, mono)
    out = []
    for para in str(msg).split("\n"):
        line = ""
        for word in para.split(" "):
            t = (line + " " + word) if line else word
            if f.size(t)[0] <= width:
                line = t
            else:
                out.append(line)
                line = word
        out.append(line)
    if len(_wc) > 3000:
        _wc.clear()
    _wc[k] = out
    return out


def text_block(s, msg, rect, size=13, color=None, lh=None, mono=True, bold=False):
    r = pygame.Rect(rect)
    lh = lh or int(size * 1.45)
    y = r.y
    for line in wrap(msg, size, r.w, mono, bold):
        if y + lh > r.bottom + 2:
            break
        text(s, line, (r.x, y), size, color, bold, mono=mono)
        y += lh
    return y


GLASS = []                  # display faces drawn this frame, glazed in finish()
SFX = None                  # set by the app: callable(name, volume)


def sfx(name, vol=1.0):
    if SFX:
        SFX(name, vol)


def legend(s, msg, pos, size=10, color=(196, 200, 204), align="c", bold=True, mono=True):
    """Silk-screened panel legend (light paint with a hair of shadow)."""
    text(s, msg, (pos[0] + 1, pos[1] + 1), size, (8, 9, 10), bold, align, mono)
    return text(s, msg, pos, size, color, bold, align, mono)


def panel(s, rect, title=None, color=None):
    """A wrinkle-painted steel plate screwed to the console, with an
    engraved label plate for its title."""
    r = pygame.Rect(rect)
    s.blit(fx.plate(r), r)
    if title:
        f = font(10, True)
        tw = f.size(title)[0]
        lr = pygame.Rect(r.x + 22, r.y + 5, tw + 14, 15)
        pygame.draw.rect(s, (12, 13, 14), lr, border_radius=2)
        pygame.draw.line(s, (70, 74, 78), (lr.x + 1, lr.bottom - 1), (lr.right - 2, lr.bottom - 1), 1)
        pygame.draw.line(s, (2, 2, 3), (lr.x + 1, lr.y), (lr.right - 2, lr.y), 1)
        text(s, title, (lr.x + 7, lr.y + 2), 10, (214, 212, 196), bold=True)
    return r


def lcd(s, rect, bg=None, tint=None, kind="lcd", gain=120):
    """A display window recessed into the panel behind glass."""
    r = pygame.Rect(rect)
    bg = bg or C["lcd"]
    fx.draw_well(s, r, bg, tint or (bg[0] * 3, bg[1] * 3, bg[2] * 3))
    GLASS.append((r, kind, gain))
    return r


def crt(s, rect, bg=(3, 9, 7), tint=(18, 56, 34), gain=150):
    """A raster CRT face: scan lines, vignette, bloom and glass reflection."""
    return lcd(s, rect, bg, tint, "crt", gain)


def finish(s):
    """Glaze every display drawn this frame (bloom, shadow mask, reflection)."""
    for r, kind, gain in GLASS:
        fx.finish_glass(s, r, kind, gain)
    del GLASS[:]


def _rgb(color):
    return C[color] if isinstance(color, str) else tuple(color)


def led(s, pos, color, on, label=None, r=6, size=10):
    col = _rgb(color)
    if on:
        g = fx.glow(r + 2, col)
        s.blit(g, (pos[0] - g.get_width() // 2, pos[1] - g.get_height() // 2), special_flags=pygame.BLEND_RGB_ADD)
    sp = fx.lamp(r, col, bool(on))
    s.blit(sp, (pos[0] - sp.get_width() // 2, pos[1] - sp.get_height() // 2))
    if label:
        legend(s, label, (pos[0] + r + 8, pos[1] - size // 2 - 2), size, align="l")


def bar(s, rect, frac, color="green", segs=24, peak=None):
    """Segmented LED bargraph."""
    r = pygame.Rect(rect)
    pygame.draw.rect(s, (3, 4, 4), r)
    sw = r.w / segs
    n = int(max(0, min(1, frac)) * segs + 0.5)
    for i in range(segs):
        col = _rgb(color)
        if peak is not None and i / segs >= peak:
            col = C["red"]
        if i >= n:
            col = tuple(c // 7 for c in col)
        pygame.draw.rect(s, col, (r.x + i * sw + 1, r.y + 1, max(1, sw - 2), r.h - 2))


def meter(s, rect, frac, label, marks=(), color=None, red_from=None):
    """Moving-coil panel meter behind glass. marks = [(frac, text), ...]."""
    r = pygame.Rect(rect)
    fx.draw_well(s, r, (224, 216, 188), (60, 56, 40))
    for i in range(r.h):                                   # lamp-lit card: warm at the top
        k = 1.0 - 0.28 * (i / r.h) ** 1.5
        pygame.draw.line(s, (int(232 * k), int(222 * k), int(190 * k)), (r.x, r.y + i), (r.right - 1, r.y + i))
    cx, cy = r.centerx, r.bottom + r.h * 0.25
    rad = r.h * 1.02
    a0, a1 = -42, 42

    def pt(fr, rr, ox=0, oy=0):
        a = math.radians(a0 + (a1 - a0) * fr)
        return cx + math.sin(a) * rr + ox, cy - math.cos(a) * rr + oy

    pygame.draw.lines(s, (30, 30, 30), False, [pt(i / 30, rad) for i in range(31)], 2)
    if red_from is not None:
        pygame.draw.lines(s, (190, 30, 30), False, [pt(red_from + (1 - red_from) * i / 10, rad - 4) for i in range(11)], 4)
    for fr, tx in marks:
        pygame.draw.line(s, (30, 30, 30), pt(fr, rad), pt(fr, rad + 6), 2)
        text(s, tx, pt(fr, rad + 15), 10, (30, 30, 30), bold=True, align="m")
    frac = max(-0.03, min(1.04, frac))
    pygame.draw.line(s, (150, 140, 120), pt(frac, rad * 0.35, 3, 4), pt(frac, rad + 4, 3, 4), 3)     # needle shadow
    pygame.draw.line(s, color or (170, 20, 20), pt(frac, rad * 0.35), pt(frac, rad + 4), 2)
    text(s, label, (r.centerx, r.bottom - 17), 10, (50, 46, 40), bold=True, align="c")
    pygame.draw.rect(s, (16, 16, 18), (r.x, r.bottom - 3, r.w, 3))
    GLASS.append((r, "lcd", 0))


class Widget:
    def __init__(self, rect, label="", tip=""):
        self.rect = pygame.Rect(rect)
        self.label, self.tip, self.visible = label, tip, True

    def hit(self, p):
        return self.visible and self.rect.collidepoint(p)

    def handle(self, ev):
        return False

    def draw(self, s):
        pass


class Knob(Widget):
    """Rotary control. Drag up/right or use the mouse wheel. SHIFT = fine.

    encoder=True makes an endless detented encoder that calls on_turn(steps).
    """

    def __init__(self, cx, cy, r, label, lo=0.0, hi=1.0, val=0.0, tip="", step=0,
                 wrap=False, fmt=None, encoder=False, on_turn=None, color=None):
        super().__init__((cx - r - 6, cy - r - 6, 2 * r + 12, 2 * r + 12), label, tip)
        self.cx, self.cy, self.r = cx, cy, r
        self.lo, self.hi, self.val, self.step, self.wrap = lo, hi, val, step, wrap
        self._raw = val
        self.fmt, self.encoder, self.on_turn = fmt, encoder, on_turn
        self.drag, self.last, self.acc, self.spin, self._tick = False, (0, 0), 0.0, 0.0, 0.0

    def set(self, v):
        self._raw = self.val = v

    def turn(self, frac, clicks=0.0):
        if self.encoder:
            self.acc += clicks
            n = int(self.acc)
            if n:
                self.acc -= n
                self.spin += n * 12
                sfx("detent", 0.6)
                if self.on_turn:
                    self.on_turn(n)
            return
        span = self.hi - self.lo
        old = self.val
        self._raw += frac * span
        if self.wrap:
            self._raw = self.lo + (self._raw - self.lo) % span
        else:
            self._raw = max(self.lo, min(self.hi, self._raw))
        v = self._raw
        if self.step:
            v = round(v / self.step) * self.step
            if self.wrap and v >= self.hi:
                v = self.lo
        self.val = v
        if self.step:
            if v != old:
                sfx("detent", 0.5)
        else:                                   # smooth pot: faint wiper noise every few degrees
            self._tick += abs(v - old) / span
            if self._tick > 0.03:
                self._tick = 0.0
                sfx("pot", 0.35)

    def handle(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self.hit(ev.pos):
            self.drag, self.last = True, ev.pos
            return True
        if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            self.drag = False
        elif ev.type == pygame.MOUSEMOTION and self.drag:
            d = (self.last[1] - ev.pos[1]) + (ev.pos[0] - self.last[0])
            self.last = ev.pos
            fine = 0.2 if pygame.key.get_mods() & pygame.KMOD_SHIFT else 1.0
            self.turn(d / 220.0 * fine, d / 5.0)
            return True
        elif ev.type == pygame.MOUSEWHEEL and self.hit(MOUSE):
            fine = 0.2 if pygame.key.get_mods() & pygame.KMOD_SHIFT else 1.0
            if self.step and not self.encoder:
                self.turn(ev.y * self.step / (self.hi - self.lo))
            else:
                self.turn(ev.y * 0.02 * fine, ev.y)
            return True
        return False

    def angle(self):
        if self.encoder:
            return self.spin
        f = (self.val - self.lo) / (self.hi - self.lo)
        return 360 * f if self.wrap else -135 + 270 * f

    style = "fluted"

    def _body(self, s):
        cx, cy, r = self.cx, self.cy, self.r
        sh = fx.knob_shadow(r)
        s.blit(sh, (cx - sh.get_width() // 2, cy - sh.get_height() // 2))
        sp = fx.knob(r, self.angle(), "spun" if self.encoder else self.style)
        s.blit(sp, (cx - sp.get_width() // 2, cy - sp.get_height() // 2))
        if self.drag or self.hit(MOUSE):
            pygame.draw.circle(s, C["amber"], (cx, cy), r + 3, 1)

    def draw(self, s):
        cx, cy, r = self.cx, self.cy, self.r
        if not self.encoder:
            n, a0, step = (12, 0, 30) if self.wrap else (11, -135, 27)
            for i in range(n):
                a = math.radians(a0 + step * i)
                sa, ca = math.sin(a), math.cos(a)
                k = 9 if (i % 5 == 0 and not self.wrap) or (self.wrap and i % 3 == 0) else 6
                pygame.draw.aaline(s, (206, 208, 200), (cx + sa * (r + 3), cy - ca * (r + 3)),
                                   (cx + sa * (r + 3 + k), cy - ca * (r + 3 + k)))
        self._body(s)
        legend(s, self.label, (cx, cy + r + 12), 10)
        if self.fmt:
            text(s, self.fmt(self.val), (cx, cy - r - 27), 12, C["amber"], bold=True, align="c")


class Selector(Knob):
    """Detented rotary switch: click left/right half or use the wheel."""
    style = "bar"

    def __init__(self, cx, cy, r, label, options, idx=0, tip=""):
        super().__init__(cx, cy, r, label, 0, max(1, len(options) - 1), idx, tip)
        self.options, self.idx = options, idx

    @property
    def value(self):
        return self.options[self.idx]

    def set(self, idx):
        self.idx = max(0, min(len(self.options) - 1, int(idx)))
        self.val = self.idx

    def select(self, opt):
        self.set(self.options.index(opt))

    def _step(self, d):
        old = self.idx
        self.set(self.idx + d)
        sfx("clunk" if self.idx != old else "stop", 0.9)

    def handle(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button in (1, 3) and self.hit(ev.pos):
            self._step(1 if (ev.pos[0] >= self.cx) == (ev.button == 1) else -1)
            return True
        if ev.type == pygame.MOUSEWHEEL and self.hit(MOUSE):
            self._step(1 if ev.y > 0 else -1)
            return True
        return False

    def angle(self):
        n = len(self.options)
        span = min(270, 45 * (n - 1))
        return -span / 2 + span * self.idx / max(1, n - 1)

    def draw(self, s):
        cx, cy, r = self.cx, self.cy, self.r
        n = len(self.options)
        span = min(270, 45 * (n - 1))
        for i in range(n):
            a = math.radians(-span / 2 + span * i / max(1, n - 1))
            p = (cx + math.sin(a) * (r + 8), cy - math.cos(a) * (r + 8))
            if i == self.idx:
                g = fx.glow(3, C["amber"], 0.55)
                s.blit(g, (p[0] - g.get_width() // 2, p[1] - g.get_height() // 2), special_flags=pygame.BLEND_RGB_ADD)
            pygame.draw.circle(s, C["amber"] if i == self.idx else (150, 152, 148), p, 2)
        self._body(s)
        legend(s, self.label, (cx, cy + r + 12), 10)
        text(s, self.value, (cx, cy - r - 27), 12, C["amber"], bold=True, align="c")


class Button(Widget):
    """Illuminated legend push-button. snd = sound played on press."""

    def __init__(self, rect, label, tip="", toggle=False, color="amber", on=False,
                 on_click=None, size=11, snd="press"):
        super().__init__(rect, label, tip)
        self.toggle, self.color, self.on, self.on_click, self.size = toggle, color, on, on_click, size
        self.down, self._clicked, self._t, self.snd = False, False, 0, snd

    @property
    def hold(self):
        return (pygame.time.get_ticks() - self._t) / 1000.0 if self.down else 0.0

    def pop(self):
        c, self._clicked = self._clicked, False
        return c

    def click(self):
        if self.toggle:
            self.on = not self.on
        self._clicked = True
        if self.on_click:
            self.on_click(self)

    def handle(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self.hit(ev.pos):
            self.down, self._t = True, pygame.time.get_ticks()
            sfx(self.snd, 0.9)
            return True
        if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1 and self.down:
            self.down = False
            sfx("release", 0.7)
            if self.hit(ev.pos):
                self.click()
            return True
        return False

    def draw(self, s):
        r = self.rect
        col = _rgb(self.color)
        lit = bool(self.on or self.down)
        if lit:
            h = fx.halo(r.w, r.h, col)
            s.blit(h, (r.x - 16, r.y - 16), special_flags=pygame.BLEND_RGB_ADD)
        s.blit(fx.button(r.w, r.h, col, lit, bool(self.down)), r)
        if self.hit(MOUSE) and not lit:
            pygame.draw.rect(s, C["amber"], r.inflate(2, 2), 1, border_radius=6)
        lines = self.label.split("\n")
        dy = 1 if self.down else 0
        y = r.centery - (len(lines) - 1) * (self.size * 0.62) + dy
        tc = (26, 16, 6) if lit else (208, 210, 206)
        for ln in lines:
            text(s, ln, (r.centerx, y), self.size, tc, bold=True, align="m")
            y += self.size * 1.25


class Guard(Button):
    """Distress button under a spring cover: click to lift, then hold to send."""

    def __init__(self, rect, label="DISTRESS", tip="", hold_s=3.0):
        super().__init__(rect, label, tip, color="red")
        self.hold_s, self.open_until, self._fired, self.armed, self._was_open = hold_s, 0, False, True, False

    def pop_fired(self):
        f, self._fired = self._fired, False
        return f

    @property
    def cover_open(self):
        return pygame.time.get_ticks() < self.open_until

    def handle(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self.hit(ev.pos):
            if not self.cover_open:
                self.open_until = pygame.time.get_ticks() + 12000
                sfx("cover", 1.0)
            else:
                self.down, self._t, self.armed = True, pygame.time.get_ticks(), True
                sfx("press", 1.0)
            return True
        if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1 and self.down:
            self.down = False
            sfx("release", 0.8)
            return True
        return False

    def update(self):
        if self.down and self.armed and self.hold >= self.hold_s:
            self._fired, self.armed = True, False
            self.open_until = 0
            self.down = False
            sfx("thunk", 1.0)
        if self._was_open and not self.cover_open:
            sfx("cover", 0.7)
        self._was_open = self.cover_open

    def draw(self, s):
        self.update()
        r = self.rect
        op = self.cover_open
        if op:
            h = fx.halo(r.w, r.h, (255, 40, 30), 0.22 + 0.2 * (pygame.time.get_ticks() // 250 % 2))
            s.blit(h, (r.x - 16, r.y - 16), special_flags=pygame.BLEND_RGB_ADD)
        s.blit(fx.guard(r.w, r.h, op, bool(self.down)), r)
        if op:
            text(s, "HOLD", (r.centerx, r.centery + 2), 11, C["white"], bold=True, align="m")
            if self.down:
                f = min(1, self.hold / self.hold_s)
                pygame.draw.arc(s, C["yellow"], r.inflate(-10, -10), math.pi / 2 - f * 2 * math.pi, math.pi / 2, 5)
        else:
            legend(s, self.label, (r.centerx, r.centery - 15), 12, C["white"])
            legend(s, "LIFT COVER", (r.centerx, r.centery + 3), 9, C["white"])
        if self.hit(MOUSE):
            pygame.draw.rect(s, C["yellow"], r.inflate(4, 4), 1, border_radius=9)


def keypad(station, x, y, rows, w=44, h=34, gap=6, tip="Keypad", snd="key"):
    """Add a grid of buttons to a station; returns {label: Button}."""
    keys = {}
    for j, row in enumerate(rows):
        for i, k in enumerate(row):
            if k:
                sn = (snd + k) if snd == "dtmf" else snd
                keys[k] = station.add(Button((x + i * (w + gap), y + j * (h + gap), w, h), k, tip, snd=sn))
    return keys


class Station:
    """One equipment position (a tab). update() runs every frame for ALL
    stations so the sim keeps going in the background."""
    name = ""
    hint = ""

    def __init__(self, app):
        self.app, self.world, self.widgets, self.alert = app, app.world, [], False

    def add(self, w):
        self.widgets.append(w)
        return w

    def handle(self, ev):
        for w in self.widgets:
            if w.visible and w.handle(ev):
                return True
        return False

    def tip_at(self, pos):
        for w in self.widgets:
            if w.hit(pos) and w.tip:
                return w.tip
        return ""

    def update(self, dt):
        pass

    def draw(self, s):
        for w in self.widgets:
            if w.visible:
                w.draw(s)

    def audio(self, syn, n):
        return None
