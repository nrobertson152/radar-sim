"""Headless end-to-end check: every drill can be completed on the real
controls, and every injectable fault renders without errors.

    python tests/test_drills.py [screenshot_dir]
"""
import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pygame  # noqa: E402
from radarsim.main import App  # noqa: E402
from radarsim import ui  # noqa: E402

SHOTS = sys.argv[1] if len(sys.argv) > 1 else None
app = App()
T = app.training
w = app.world


def run(sec, dt=1 / 30.0):
    for _ in range(int(sec / dt)):
        app.step(dt)
        app.gen_audio(app.audio.syn, 2208)
        app.audio.syn.t += 2208


def shot(name):
    app.draw()
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        pygame.image.save(app.screen, os.path.join(SHOTS, name + ".png"))


def click(widget):
    widget.click()


def fire(guard):
    """Lift the cover and hold a guarded button (real time, 3 s)."""
    c = guard.rect.center
    for typ in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEBUTTONDOWN):
        guard.handle(pygame.event.Event(typ, pos=c, button=1))
    time.sleep(guard.hold_s + 0.15)
    guard.update()
    run(0.1)


def ptt(st, sec):
    st.key_ptt = True
    run(sec)
    st.key_ptt = False
    run(0.2)


def start(i, tab):
    T.start(i)
    app.goto(tab)
    run(0.2)
    return T.active


def done(d):
    assert T.done_t is not None, "drill '%s' stuck at step %d: %s" % (d.title, T.step + 1, d.steps[min(T.step, len(d.steps) - 1)][0])
    print("ok  ", d.title)


def lay(name):
    rng, brg = w.rb(w.by_name[name])
    app.radar.ebl.set(brg)
    app.radar.vrm.set(rng / app.radar.rmax)


r = app.radar
# --- Radar 1
d = start(0, "RADAR")
r.power.set(1); run(21); r.power.set(2); run(0.5)
r.ri = 6; run(0.2)
best = max((i / 200.0 for i in range(201)), key=lambda v: (r.tune.set(v), run(0.04), r.tune_ind)[2])
r.tune.set(best); run(0.3)
r.gain.set(0.66); run(0.2); r.afc.on = True; run(2)
shot("drill_radar1"); done(d)
# --- Radar 2
d = start(1, "RADAR"); run(4); shot("drill_radar2_before")
r.pulse.set(0); run(0.2); r.stc.set(0.62); run(0.2); r.eav.on = True; run(9); lay("SY KITTIWAKE"); run(0.3)
shot("drill_radar2_after"); done(d)
# --- Radar 3
d = start(2, "RADAR"); run(4); shot("drill_radar3_before")
r.ftc.set(0.7); run(4); shot("drill_radar3_ftc"); r.band.set(1); run(4); lay("FV MORVORAN"); run(0.3)
shot("drill_radar3_sband"); done(d)
# --- Radar 4
d = start(3, "RADAR"); r.band.set(0); r.ri = 6; r.clear(); run(5); lay("SART"); run(0.3)
shot("drill_radar4_sart"); done(d)
# --- Radar 5
d = start(4, "RADAR"); run(3)
c = w.by_name["NORDIC STAR"]
x, y = r.to_xy(*w.rb(c))
r.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(x, y), button=1))
run(12); shot("drill_radar5_arpa")
assert r.cpa_alarm, "no CPA alarm"
click(r.ack); run(0.2); r.hdg.set(140); run(3); shot("drill_radar5_after"); done(d)
# --- VHF 1
v = app.vuhf
d = start(5, "VHF / UHF"); v.nature.set(1); run(0.2); fire(v.guard); run(9); shot("drill_vhf1_ack")
click(v.b_sil); run(0.2); ptt(v, 5); run(8); shot("drill_vhf1_mayday"); done(d)
# --- VHF 2
d = start(6, "VHF / UHF"); run(7); assert v.dsc_alarm; click(v.b_sil); run(0.3); v.ch = 16; run(40)
ptt(v, 4); run(6); shot("drill_vhf2"); done(d)
# --- VHF 3
d = start(7, "VHF / UHF"); v.addr.set(1); v.wch.set(2); run(0.2); click(v.b_ind); run(9); ptt(v, 3); run(5)
shot("drill_vhf3"); done(d)
# --- HF 1
h = app.hf
d = start(8, "MF / HF SSB")
from radarsim.world import HF_STATIONS  # noqa: E402
bst = max((s for s in HF_STATIONS if s["name"] == "NORTHSEA RADIO"), key=lambda s: w.hf_rx(s)["snr"])
ch = {4417.0: "421", 8764.0: "816", 13137.0: "1221", 17302.0: "1621"}[bst["f"]]
for k in ch:
    h._key(k)
h._key("CH"); run(3); shot("drill_hf1_mistuned")
h.rit.set(0); run(6); click(h.b_tune); run(3); ptt(h, 4); run(10); shot("drill_hf1_contact"); done(d)
# --- HF 2
d = start(9, "MF / HF SSB")
for k in "518":
    h._key(k)
h._key("kHz"); h.mode.select("FSK"); run(12); shot("drill_hf2_navtex"); done(d)
# --- HF 3
d = start(10, "MF / HF SSB")
for band in (3, 1, 2, 4, 0, 5):
    h.dband.set(band); run(0.1); fire(h.guard); run(10)
    if "hf_distress_acked" in h.flags:
        break
click(h.b_rt); run(0.3); shot("drill_hf3"); done(d)
# --- Inmarsat
s = app.satcom
d = start(11, "INMARSAT"); s.region.set(1); run(0.2)
az, el, _ = s.look(); s.az.set(az); s.el.set(el); run(0.2); s.b_auto.click(); run(0.3)
click(s.b_log); run(4.5)
for ch_ in "MEDICO":
    s.handle(pygame.event.Event(pygame.KEYDOWN, key=ord(ch_.lower()), unicode=ch_, mod=0))
click(s.b_send); run(5)
s.keys["3"].click(); run(0.1); s.keys["2"].click(); run(0.2); click(s.b_call); run(4); shot("drill_inmarsat"); done(d)
fire(s.guard); run(8); assert "c_distress_acked" in s.flags
# --- COSPAS-SARSAT
q = app.sarsat
d = start(12, "COSPAS-SARSAT"); q.b_gnss.on = False; run(0.2); q.sw.set(3); q.warp.set(3); run(0.5)
n = 0
while not q.resolved and n < 900:
    run(1.0); n += 1
    if n == 6:
        shot("drill_sarsat_early")
q.sart.set(2); run(0.3); shot("drill_sarsat_done"); done(d)
print("     sim time to resolve: %.1f h, events %d" % ((q.st - q.t0) / 3600.0, len(q.events)))
# --- faults
b = app.bench
for i, kind in ((13, "R"), (14, "S")):
    d = start(i, "RADAR" if kind == "R" else "MF / HF SSB"); run(0.5)
    app.goto("CIRCUITS"); run(0.3); b.sel[kind] = b.fault[kind]; click(b.b_dec); run(0.3); done(d)
from radarsim.world import RADAR_BLOCKS, SSB_BLOCKS  # noqa: E402
T.active = None
r.power.set(2); r.warm = 0
for kind, ids, tab in (("R", RADAR_BLOCKS, "RADAR"), ("S", SSB_BLOCKS, "MF / HF SSB")):
    b.b_r.on, b.b_s.on = kind == "R", kind == "S"
    for f in ids:
        b.repair(kind); b.inject(kind, f)
        for t in (tab, "CIRCUITS"):
            app.goto(t)
            for sel in ids:
                b.sel[kind] = sel
                run(0.07)
                app.draw()
        if kind == "S":
            b.b_spec.on = not b.b_spec.on
            ptt(h, 2)
    b.repair(kind)
print("ok   all faults render")
# --- capstone
d = start(15, "VHF / UHF"); v.nature.set(2); run(0.2); fire(v.guard); run(1); ptt(v, 5)
for band in (3, 1, 2, 4, 0, 5):
    h.dband.set(band); run(0.1); fire(h.guard); run(10)
    if "hf_distress_acked" in h.flags:
        break
fire(s.guard); run(1); q.sw.set(3); run(0.3); q.sart.set(2); run(0.5); done(d)
for i in range(len(app.stations)):
    app.cur = i
    run(1.0)
    shot("final_%d" % (i + 1))
print("ALL DRILLS PASS")
