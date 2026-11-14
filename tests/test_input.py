"""Headless check of real mouse/keyboard event paths (knobs, selectors,
tabs, map and waterfall clicks, text entry)."""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pygame  # noqa: E402
from radarsim.main import App  # noqa: E402

app = App()
E = pygame.event.Event


def down(p, b=1):
    app.handle(E(pygame.MOUSEBUTTONDOWN, pos=p, button=b))


def up(p, b=1):
    app.handle(E(pygame.MOUSEBUTTONUP, pos=p, button=b))


def move(p):
    app.handle(E(pygame.MOUSEMOTION, pos=p, rel=(0, 0), buttons=(1, 0, 0)))


def click(p, b=1):
    down(p, b); up(p, b); app.step(1 / 30)


def wheel(p, y):
    move(p); app.handle(E(pygame.MOUSEWHEEL, x=0, y=y)); app.step(1 / 30)


r = app.radar
g0 = r.gain.val
down((r.gain.cx, r.gain.cy)); move((r.gain.cx, r.gain.cy - 60)); up((r.gain.cx, r.gain.cy - 60))
assert r.gain.val > g0 + 0.2, "knob drag"
wheel((r.gain.cx, r.gain.cy), -3)
assert r.gain.val < g0 + 0.27 + 0.01
click((r.power.cx + 8, r.power.cy)); click((r.power.cx + 8, r.power.cy))
assert r.power.value == "TX", "selector click"
click((r.power.cx - 8, r.power.cy)); assert r.power.value == "STBY"
click(r.rup.rect.center); assert r.rmax == 12, "button"
wheel((r.ebl.cx, r.ebl.cy), 5); assert r.ebl.val != 45
click(app.tabs[2].center); assert app.station is app.hf, "tab click"
h = app.hf
f0 = h.f
wheel((h.knob.cx, h.knob.cy), 3); assert abs(h.f - f0 - 0.3) < 1e-6, "encoder wheel %r" % h.f
click((36 + 448 + 100, 600)); assert h.f > f0 + 2, "waterfall click-to-tune"
for ch in "2182":
    app.handle(E(pygame.KEYDOWN, key=ord(ch), unicode=ch, mod=0))
app.handle(E(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r", mod=0)); app.step(0.03)
assert h.f == 2182.0, "keyboard frequency entry"
click(h.keys["8"].rect.center); click(h.keys["1"].rect.center); click(h.keys["6"].rect.center); click(h.keys["CH"].rect.center)
assert (h.f, h.txf, h.chan) == (8764.0, 8240.0, 816), "ITU channel entry"
app.handle(E(pygame.KEYDOWN, key=pygame.K_F4, unicode="", mod=0)); assert app.station is app.satcom
s = app.satcom
click(s.b_pos.rect.center); click(s.map.xy(-33.9, 18.4)); 
assert abs(app.world.lat + 33.9) < 0.6 and abs(app.world.lon - 18.4) < 0.6, "map reposition"
for ch in "Hi there":
    app.handle(E(pygame.KEYDOWN, key=ord(ch.lower()), unicode=ch, mod=0))
assert s.msg == "HI THERE"
app.handle(E(pygame.KEYDOWN, key=pygame.K_F10, unicode="", mod=0))
b = app.bench
click((575, 320)); assert b.sel["R"] == "mix", "block select"
click(b.b_s.rect.center); assert b.which == "S"
app.handle(E(pygame.KEYDOWN, key=pygame.K_F2, unicode="", mod=0))
v = app.vuhf
app.handle(E(pygame.KEYDOWN, key=pygame.K_SPACE, unicode=" ", mod=0)); app.step(0.05); assert v.tx
app.handle(E(pygame.KEYUP, key=pygame.K_SPACE, mod=0)); app.step(0.05); assert not v.tx
wheel((v.chk.cx, v.chk.cy), 1); assert v.ch == 17
click(v.guard.rect.center); assert v.guard.cover_open
for i in range(len(app.stations)):
    app.cur = i
    for p in ((400, 300), (1200, 300), (700, 700), (1300, 700), (150, 150)):
        move(p); app.step(0.02); app.draw()
print("INPUT TESTS PASS")
