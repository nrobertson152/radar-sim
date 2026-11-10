"""Panel widgets: knobs, selectors, buttons, guarded buttons, meters, LCDs.

Everything is drawn on a fixed 1600x900 logical canvas (pygame.SCALED handles
the window scaling), so all coordinates in the stations are absolute pixels.
"""
import math
import pygame

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


def panel(s, rect, title=None, color=None):
    r = pygame.Rect(rect)
    pygame.draw.rect(s, color or C["panel"], r, border_radius=7)
    pygame.draw.rect(s, C["edge"], r, 1, border_radius=7)
    for x, y in ((r.x + 7, r.y + 7), (r.right - 8, r.y + 7),
                 (r.x + 7, r.bottom - 8), (r.right - 8, r.bottom - 8)):
        pygame.draw.circle(s, (20, 22, 26), (x, y), 3)
        pygame.draw.circle(s, C["edge"], (x, y), 3, 1)
    if title:
        text(s, title, (r.x + 18, r.y + 5), 11, C["dim"], bold=True)
    return r


def lcd(s, rect, bg=None):
    r = pygame.Rect(rect)
    pygame.draw.rect(s, bg or C["lcd"], r, border_radius=4)
    pygame.draw.rect(s, (0, 0, 0), r, 2, border_radius=4)
    pygame.draw.rect(s, (60, 66, 74), r.inflate(2, 2), 1, border_radius=5)
    return r


def led(s, pos, color, on, label=None, r=6, size=10):
    col = C[color] if isinstance(color, str) else color
    if on:
        glow = pygame.Surface((r * 6, r * 6), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*col, 55), (r * 3, r * 3), r * 2.4)
        s.blit(glow, (pos[0] - r * 3, pos[1] - r * 3))
    pygame.draw.circle(s, col if on else tuple(c // 5 + 12 for c in col), pos, r)
    pygame.draw.circle(s, (0, 0, 0), pos, r, 1)
    if label:
        text(s, label, (pos[0] + r + 6, pos[1] - size // 2 - 2), size, C["dim"], bold=True)


def bar(s, rect, frac, color="green", segs=24, peak=None):
    """Segmented LED bargraph."""
    r = pygame.Rect(rect)
    pygame.draw.rect(s, (8, 9, 11), r)
    sw = r.w / segs
    n = int(max(0, min(1, frac)) * segs + 0.5)
    for i in range(segs):
        col = C[color] if isinstance(color, str) else color
        if peak is not None and i / segs >= peak:
            col = C["red"]
        if i >= n:
            col = tuple(c // 6 for c in col)
        pygame.draw.rect(s, col, (r.x + i * sw + 1, r.y + 1, max(1, sw - 2), r.h - 2))


def meter(s, rect, frac, label, marks=(), color=None, red_from=None):
    """Analogue moving-coil meter. marks = [(frac, text), ...]."""
    r = pygame.Rect(rect)
    pygame.draw.rect(s, (226, 220, 196), r, border_radius=5)
    pygame.draw.rect(s, (0, 0, 0), r, 2, border_radius=5)
    cx, cy = r.centerx, r.bottom + r.h * 0.25
    rad = r.h * 1.02
    a0, a1 = -42, 42

    def pt(fr, rr):
        a = math.radians(a0 + (a1 - a0) * fr)
        return cx + math.sin(a) * rr, cy - math.cos(a) * rr

    pts = [pt(i / 30, rad) for i in range(31)]
    pygame.draw.lines(s, (40, 40, 40), False, pts, 2)
    if red_from is not None:
        pts = [pt(red_from + (1 - red_from) * i / 10, rad - 4) for i in range(11)]
        pygame.draw.lines(s, (200, 30, 30), False, pts, 4)
    for fr, tx in marks:
        pygame.draw.line(s, (40, 40, 40), pt(fr, rad), pt(fr, rad + 6), 2)
        p = pt(fr, rad + 15)
        text(s, tx, p, 10, (40, 40, 40), bold=True, align="m")
    frac = max(-0.03, min(1.04, frac))
    pygame.draw.line(s, color or (190, 30, 30), pt(frac, rad * 0.35), pt(frac, rad + 4), 2)
    text(s, label, (r.centerx, r.bottom - 17), 10, (60, 60, 60), bold=True, align="c")
    pygame.draw.rect(s, (0, 0, 0), r, 2, border_radius=5)


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
        self.col = color or C["white"]
        self.drag, self.last, self.acc, self.spin = False, (0, 0), 0.0, 0.0

    def set(self, v):
        self._raw = self.val = v

    def turn(self, frac, clicks=0.0):
        if self.encoder:
            self.acc += clicks
            n = int(self.acc)
            if n:
                self.acc -= n
                self.spin += n * 15
                if self.on_turn:
                    self.on_turn(n)
            return
        span = self.hi - self.lo
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

    def draw(self, s):
        cx, cy, r = self.cx, self.cy, self.r
        pygame.draw.circle(s, (9, 10, 12), (cx + 2, cy + 3), r + 3)
        if not self.encoder and not self.wrap:
            for i in range(11):
                a = math.radians(-135 + 27 * i)
                sa, ca = math.sin(a), math.cos(a)
                pygame.draw.line(s, C["dim"], (cx + sa * (r + 4), cy - ca * (r + 4)),
                                 (cx + sa * (r + 8), cy - ca * (r + 8)), 1)
        pygame.draw.circle(s, (60, 65, 74), (cx, cy), r)
        pygame.draw.circle(s, (27, 30, 35), (cx, cy), r - 3)
        pygame.draw.circle(s, (92, 99, 110), (cx, cy), r, 1)
        if self.encoder:
            for i in range(12):
                a = math.radians(self.spin + i * 30)
                pygame.draw.circle(s, (70, 76, 86), (cx + math.sin(a) * (r - 7),
                                                     cy - math.cos(a) * (r - 7)), 2)
            a = math.radians(self.spin)
            pygame.draw.circle(s, (14, 15, 18), (cx + math.sin(a) * r * 0.5,
                                                 cy - math.cos(a) * r * 0.5), max(4, r // 6))
        else:
            a = math.radians(self.angle())
            sa, ca = math.sin(a), math.cos(a)
            pygame.draw.line(s, self.col, (cx + sa * r * 0.3, cy - ca * r * 0.3),
                             (cx + sa * (r - 4), cy - ca * (r - 4)), 3)
        if self.drag or self.hit(MOUSE):
            pygame.draw.circle(s, C["amber"], (cx, cy), r + 2, 1)
        text(s, self.label, (cx, cy + r + 10), 10, C["dim"], bold=True, align="c")
        if self.fmt:
            text(s, self.fmt(self.val), (cx, cy - r - 25), 12, C["amber"], bold=True, align="c")


class Selector(Knob):
    """Detented rotary switch: click left/right half or use the wheel."""

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

    def handle(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button in (1, 3) and self.hit(ev.pos):
            self.set(self.idx + (1 if (ev.pos[0] >= self.cx) == (ev.button == 1) else -1))
            return True
        if ev.type == pygame.MOUSEWHEEL and self.hit(MOUSE):
            self.set(self.idx + (1 if ev.y > 0 else -1))
            return True
        return False

    def angle(self):
        n = len(self.options)
        span = min(270, 45 * (n - 1))
        return -span / 2 + span * self.idx / max(1, n - 1)

    def draw(self, s):
        cx, cy, r = self.cx, self.cy, self.r
        pygame.draw.circle(s, (9, 10, 12), (cx + 2, cy + 3), r + 3)
        n = len(self.options)
        span = min(270, 45 * (n - 1))
        for i in range(n):
            a = math.radians(-span / 2 + span * i / max(1, n - 1))
            p = (cx + math.sin(a) * (r + 7), cy - math.cos(a) * (r + 7))
            pygame.draw.circle(s, C["amber"] if i == self.idx else C["dim"], p, 2)
        pygame.draw.circle(s, (50, 54, 62), (cx, cy), r)
        pygame.draw.circle(s, (22, 24, 28), (cx, cy), r - 3)
        a = math.radians(self.angle())
        sa, ca = math.sin(a), math.cos(a)
        pygame.draw.line(s, (70, 76, 86), (cx - sa * (r - 5), cy + ca * (r - 5)),
                         (cx + sa * (r - 5), cy - ca * (r - 5)), 9)
        pygame.draw.line(s, C["white"], (cx + sa * r * 0.35, cy - ca * r * 0.35),
                         (cx + sa * (r - 5), cy - ca * (r - 5)), 3)
        if self.hit(MOUSE):
            pygame.draw.circle(s, C["amber"], (cx, cy), r + 2, 1)
        text(s, self.label, (cx, cy + r + 10), 10, C["dim"], bold=True, align="c")
        text(s, self.value, (cx, cy - r - 25), 12, C["amber"], bold=True, align="c")


class Button(Widget):
    def __init__(self, rect, label, tip="", toggle=False, color="amber", on=False,
                 on_click=None, size=11):
        super().__init__(rect, label, tip)
        self.toggle, self.color, self.on, self.on_click, self.size = toggle, color, on, on_click, size
        self.down, self._clicked, self._t = False, False, 0

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
            return True
        if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1 and self.down:
            self.down = False
            if self.hit(ev.pos):
                self.click()
            return True
        return False

    def draw(self, s):
        r = self.rect.move(0, 1) if self.down else self.rect
        col = C[self.color]
        lit = self.on or self.down
        pygame.draw.rect(s, (8, 9, 11), self.rect.move(1, 3), border_radius=5)
        body = tuple(int(c * 0.55) for c in col) if lit else (58, 63, 72)
        pygame.draw.rect(s, body, r, border_radius=5)
        pygame.draw.rect(s, col if lit else (98, 105, 117), r, 1, border_radius=5)
        if self.hit(MOUSE) and not lit:
            pygame.draw.rect(s, C["amber"], r, 1, border_radius=5)
        lines = self.label.split("\n")
        y = r.centery - (len(lines) - 1) * (self.size * 0.62)
        for ln in lines:
            text(s, ln, (r.centerx, y), self.size, C["white"] if lit else C["text"],
                 bold=True, align="m")
            y += self.size * 1.25


class Guard(Button):
    """Distress button under a spring cover: click to lift, then hold to send."""

    def __init__(self, rect, label="DISTRESS", tip="", hold_s=3.0):
        super().__init__(rect, label, tip, color="red")
        self.hold_s, self.open_until, self._fired, self.armed = hold_s, 0, False, True

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
            else:
                self.down, self._t, self.armed = True, pygame.time.get_ticks(), True
            return True
        if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1 and self.down:
            self.down = False
            return True
        return False

    def update(self):
        if self.down and self.armed and self.hold >= self.hold_s:
            self._fired, self.armed = True, False
            self.open_until = 0
            self.down = False

    def draw(self, s):
        self.update()
        r = self.rect
        pygame.draw.rect(s, (90, 14, 10), r, border_radius=8)
        pygame.draw.rect(s, C["red"], r, 2, border_radius=8)
        if self.cover_open:
            pygame.draw.circle(s, C["red"] if not self.down else (255, 150, 140),
                               r.center, min(r.w, r.h) // 2 - 8)
            text(s, "HOLD", r.center, 11, C["white"], bold=True, align="m")
            if self.down:
                f = min(1, self.hold / self.hold_s)
                pygame.draw.arc(s, C["yellow"], r.inflate(-6, -6), math.pi / 2 - f * 2 * math.pi,
                                math.pi / 2, 5)
        else:
            for i in range(-r.h, r.w, 14):
                pygame.draw.line(s, (150, 30, 24), (r.x + max(0, i), r.y + max(0, -i)),
                                 (r.x + min(r.w, i + r.h), r.y + min(r.h, r.h - max(0, i + r.h - r.w))), 4)
            pygame.draw.rect(s, (140, 150, 160), r.inflate(-10, -10), 2, border_radius=6)
            text(s, self.label, (r.centerx, r.centery - 8), 12, C["white"], bold=True, align="m")
            text(s, "LIFT COVER", (r.centerx, r.centery + 9), 9, C["white"], bold=True, align="m")
        if self.hit(MOUSE):
            pygame.draw.rect(s, C["yellow"], r.inflate(4, 4), 1, border_radius=9)


def keypad(station, x, y, rows, w=44, h=34, gap=6, tip="Keypad"):
    """Add a grid of buttons to a station; returns {label: Button}."""
    keys = {}
    for j, row in enumerate(rows):
        for i, k in enumerate(row):
            if k:
                keys[k] = station.add(Button((x + i * (w + gap), y + j * (h + gap), w, h), k, tip))
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
