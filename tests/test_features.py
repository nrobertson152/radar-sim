"""Headless checks of the expanded console: every new drill completed on the
real controls, plus focused tests of power, sensors, AIS, NAVTEX, the VHF
message composer, SATCOM 2, radar ARPA / guard zone, the HF receiver and the
stereo audio paths.

    python tests/test_features.py [screenshot_dir]
"""
import os
import sys
import time
import math

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np  # noqa: E402
import pygame  # noqa: E402
from radarsim.main import App  # noqa: E402
from radarsim.world import Msg, HF_STATIONS  # noqa: E402
from radarsim.speech import SR  # noqa: E402
from radarsim.composer import OWN_VOICE  # noqa: E402
from radarsim.vhf import NATURES  # noqa: E402

SHOTS = sys.argv[1] if len(sys.argv) > 1 else None
app = App()
T = app.training
w = app.world
r, v, h, s, q, n, p, nt, b = (app.radar, app.vuhf, app.hf, app.satcom, app.sat2, app.nav, app.power, app.navtex, app.bench)
E = pygame.event.Event


def run(sec, dt=1 / 30.0, audio=True):
    for _ in range(int(sec / dt)):
        app.step(dt)
        if audio:
            a = app.gen_audio(app.audio.syn, 2208)
            assert a.shape == (2208, 2) and np.isfinite(a).all(), "bad audio on %s" % app.station.name
            app.audio.syn.t += 2208


def until(cond, limit, what, step=0.5):
    t = 0.0
    while not cond():
        run(step)
        t += step
        assert t <= limit, "timed out waiting for: " + what
    return t


def shot(name):
    app.draw()
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        pygame.image.save(app.screen, os.path.join(SHOTS, name + ".png"))


def fire(guard):
    c = guard.rect.center
    for typ in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEBUTTONDOWN):
        guard.handle(E(typ, pos=c, button=1))
    time.sleep(guard.hold_s + 0.15)
    guard.update()
    run(0.1)


def ptt(st, sec):
    st.key_ptt = True
    run(sec)
    st.key_ptt = False
    run(0.2)


def start(i, tab=None):
    T.start(i)
    if tab:
        app.goto(tab)
    run(0.2)
    return T.active


def done(d):
    assert T.done_t is not None, "drill '%s' stuck at step %d: %s" % (d.title, T.step + 1, d.steps[min(T.step, len(d.steps) - 1)][0])
    print("ok  ", d.title, "  grade", T.result[1], " errors", T.result[0])


def compose(keys):
    v.comp.items = []
    for k in keys:
        v.comp.add(k)
    run(0.6)
    app.speech.wait()
    run(0.1)


def send_composed(extra=0.6):
    clip = Msg.speech.get(v.comp.text(), OWN_VOICE) if Msg.speech.ok else None
    dur = (len(clip) / SR + 0.3) if clip is not None else len(v.comp.text()) / 15.0 + 0.5
    ptt(v, dur + extra)


def click_ppi(xy, button=1):
    r.handle(E(pygame.MOUSEBUTTONDOWN, pos=(int(xy[0]), int(xy[1])), button=button))


MAYDAY = ["MAYDAY"] * 3 + ["THISIS"] + ["NAME"] * 3 + ["CALLSIGN", "MMSI", "MAYDAY", "NAME", "POSITION", "NATURE",
                                                       "ASSIST", "POB", "OVER"]

# ------------------------------------------------------------------ audio
for i in range(len(app.stations)):
    app.cur = i
    for mon in (True, False):
        app.monitor_all = mon
        run(0.3)
app.monitor_all = True
print("ok   stereo audio on every station, monitor all on and off")

# ------------------------------------------------------------- the drills
names = [d.title for d in T.drills]
assert len(names) == 34, len(names)

d = start(16, "RADAR")                                       # guard zone
r.vrm.set(3.0 / r.rmax); r.gz_b.click(); run(0.3)
until(lambda: "gz_alarm" in r.flags, 150, "guard zone alarm")
shot("gz_alarm")
r.ack.click(); run(0.3)
c = w.by_name["FV MORVORAN"]
click_ppi(r.to_xy(*w.rb(c))); run(0.3); done(d)

d = start(17, "RADAR")                                       # AIS and radar
r.ais_b.click(); run(11)
fer = next(rep for rep in w.ais.values() if rep["name"] == "PENHALE FERRY")
click_ppi(r.to_xy(*r._rb(fer["x"], fer["y"]))); run(0.2)
assert r.ais_sel == fer["mmsi"], "AIS click did not select the AIS target"
ky = w.by_name["SY KITTIWAKE"]
assert ky.mmsi not in w.ais, "yacht without AIS appears on AIS"
click_ppi(r.to_xy(*w.rb(ky))); run(0.2)
r.vect_b.click(); run(0.3); shot("ais_overlay"); done(d)

d = start(18, "NAV SENSORS / AIS")                           # gyro / log errors
run(0.5)
assert abs(n.gyro_error()) > 2.0, "gyro error not produced by wrong corrections: %.2f" % n.gyro_error()
assert abs(r.gerr - n.gyro_error()) < 0.05
n.gy_spd.set(10); n.gy_lat.set(50); run(0.5)
n.log_cal.set(0.0); run(0.3); app.goto("RADAR"); run(0.5); done(d)

d = start(19, "NAV SENSORS / AIS")                           # GPS failure
until(lambda: n.fix == "NO FIX", 15, "GPS fix lost")
assert app.dsc_position() is None
n.gps_ack.click(); run(0.2)
n.b_load.click(); run(0.1); n.b_enter.click(); run(0.3)
app.goto("VHF / UHF"); run(0.3); shot("gps_fail_manual"); done(d)

d = start(20, "NAV SENSORS / AIS")                           # AIS-SART
until(lambda: "ais_sart_seen" in n.flags, 5, "AIS-SART on the MKD")
n.ais_ack.click(); run(0.2)
tg = n.targets()
n.cur_i = next(i for i, x in enumerate(tg) if str(x["mmsi"]).startswith("970"))
n.ais_ent.click(); run(0.2)
shot("ais_sart_mkd")
app.goto("RADAR"); r.ais_b.on = False; r.ais_b.click(); run(0.4); done(d)

d = start(21, "NAVTEX RECEIVER")                             # NAVTEX setup
nt.b1["L"].click(); nt.b1["O"].click(); nt.b2["D"].click(); run(0.2)
assert nt.b2["D"].on, "subject D could be rejected"
nt.b2["H"].click(); nt.b_test.click(); run(0.3)
until(lambda: bool(nt.mem), 240, "a NAVTEX message")
nt.page = "LIST"; nt.k_read.click(); run(0.2); shot("navtex"); done(d)

d = start(22, "NAVTEX RECEIVER")                             # NAVTEX SAR alarm
until(lambda: "sar_rx" in nt.flags, 120, "NAVTEX SAR alarm")
nt.b_ack.click(); run(0.1); nt.page = "LIST"; nt.cursor = 0; nt.k_read.click(); run(0.2); done(d)

d = start(23, "VHF / UHF")                                   # composed MAYDAY
v.nature.set(NATURES.index("SINKING")); run(0.1)
fire(v.guard); run(1.0)
compose(MAYDAY)
send_composed(); run(3); shot("vhf_composed_mayday"); done(d)
assert v.comp.debrief and all(ok for ok, _, _ in v.comp.debrief["chk"]), v.comp.debrief["chk"]

d = start(24, "VHF / UHF")                                   # incoming DSC call
until(lambda: "indiv_rx" in v.flags, 10, "incoming DSC call")
v.b_sil.click(); run(0.2)
until(lambda: v.flags.get("heard:PENHALE COASTGUARD", 0) > v.flags["indiv_accept"], 30, "coastguard on CH67")
ptt(v, 3); run(1); done(d)

d = start(25, "VHF / UHF")                                   # SECURITE
v.b_saf.click(); run(1.0)
compose(["SECURITE"] * 3 + ["ALLST"] * 3 + ["THISIS"] + ["NAME"] * 3 + ["HAZARD", "POSITION", "OUT"])
send_composed(); run(1); done(d)

d = start(26, "MF / HF SSB")                                 # HF static / AGC / NB
assert h.agc == "OFF"
h.agc_b.click(); h.nb_b.click(); run(0.2)
until(lambda: h.flags.get("copy:NORTHSEA RADIO", 0) >= 40, 60, "HF copy with NB")
done(d)

d = start(27, "INMARSAT")                                    # point by ear
s.b_peak.click(); run(0.3)
az, el, _ = s.look(); s.az.set(round(az * 2) / 2); s.el.set(round(el * 2) / 2); run(0.3)
s.b_auto.click(); run(0.2); s.b_log.click(); run(4.5); s.b_pvt.click(); run(7); done(d)

d = start(28, "SATCOM 2")                                    # SSAS + LRIT
fire(q.ssas1); run(0.2)
until(lambda: "ssas_test_ack" in q.flags, 15, "CSO confirms SSAS test")
q.ssas_rst.click(); run(0.2); q.lrit_test.click(); run(0.3); shot("satcom2"); done(d)

d = start(29, "SATCOM 2")                                    # Iridium distress
until(lambda: q.registered, 30, "Iridium registration")
q.nature.set(NATURES.index("FLOODING")); run(0.1)
fire(q.guard)
until(lambda: "ir_distress_acked" in q.flags, 15, "RCC acknowledgement"); run(5)
assert q.call == "CONNECTED", "RCC did not call back"
done(d)

d = start(30, "RADIO POWER")                                 # battery check
p.b_test.down = True; run(2.5); p.b_test.down = False; run(0.2)
p.b_ins.click(); run(0.2); done(d)

d = start(31, "RADIO POWER")                                 # blackout
run(0.5)
assert p.dc_from == "BATT" and not r.powered and v.on, "blackout: radios not on battery / radar not dead"
p.b_ack.click(); run(0.2)
until(lambda: p.gen == "RUN", 15, "emergency generator")
shot("blackout")
until(lambda: r.transmitting, 40, "radar restart")
s.b_auto.click(); run(0.3); done(d)
p.f_black.set(False); run(1)

d = start(32)                                                # tripped breaker
assert not v.on
app.goto("RADIO POWER"); run(0.2)
p.brk["VHF"].flip(); p.brk["VHF"].flip(); run(0.3)
assert v.on
v.ch = 16; v.comp.items = []; app.goto("VHF / UHF"); ptt(v, 3); run(1); done(d)

d = start(33, "CIRCUITS")                                    # audio tracer
b.tracer.click(); run(0.2)
for bid in ("spk", "afo", "pdet", "ifl"):
    blk = next(x for x in b.blocks if x[0] == bid)
    b.handle(E(pygame.MOUSEBUTTONDOWN, pos=(blk[2] + 10, blk[3] + 10), button=1)); run(0.15)
b.sel["S"] = b.fault["S"]; b.b_dec.click(); run(0.3); done(d)
T.active = None

# ------------------------------------------------------ focused checks
# composer: truncated PTT and a message without position
app.goto("VHF / UHF")
v.ch = 16; v.distress = None
compose(MAYDAY)
ptt(v, 3.0)
assert v.comp.debrief and any(t.startswith("PTT released") and not ok for ok, t, _ in v.comp.debrief["chk"])
compose([k for k in MAYDAY if k != "POSITION"])
send_composed(); run(0.5)
assert any("SAY AGAIN YOUR POSITION" in m.text for m in w.msgs), "coastguard did not ask for the position"
print("ok   composer: truncation and missing-element replies")

# radar: no echo -> no acquisition; lost target; guard zone draw
from radarsim.training import _radar_ready, _baseline  # noqa: E402
_baseline(app); _radar_ready(app, spd=0.0); app.goto("RADAR"); run(3)
nt0 = len(r.tracks)
click_ppi((r.CX + 5, r.CY - 300)); run(0.2)
assert len(r.tracks) == nt0 and "NO ECHO" in r.msg
c = w.by_name["NORDIC STAR"]; c.active = True
a = math.radians(30); c.x, c.y, c.sog = w.x + 4 * math.sin(a), w.y + 4 * math.cos(a), 0
r.ri = 5; r.clear(); run(3)
click_ppi(r.to_xy(*w.rb(c))); run(0.5)
tr = next(t for t in r.tracks if t["c"] is c)
rcs0, c.rcs = c.rcs, 1e-9
until(lambda: tr.get("lost"), 30, "lost target")
assert r.lost_alarm
r.ack.click(); run(0.2)
assert tr not in r.tracks and not r.lost_alarm
c.rcs = rcs0
print("ok   radar: acquisition needs an echo, lost-target alarm")

# gyro failure: radar loses north-up, Inmarsat auto-track drops
r.nup.on = True; run(0.3)
n.f_gyro.set(True); run(0.5)
assert not r.nup.on and not r.hdg_ok
r.nup.click(); run(0.2)
assert not r.nup.on, "north-up allowed without gyro"
n.f_gyro.set(False); run(0.5)
print("ok   gyro failure: radar head-up only")

# power: source selector to MAIN during blackout kills the radio bus
nm = len(app.mistakes)
p.f_black.set(True); run(1)
p.src.set(1); run(0.5)
assert p.dc_from is None and not v.on and len(app.mistakes) > nm
p.src.set(0); p.f_black.set(False); run(1)
assert p.dc_from == "AC" and v.on
p.dim.set(0.2); run(0.2); app.cur = 0; app.draw(); p.dim.set(1.0)
print("ok   power: selector, lighting dimmer")

# SATCOM 2: Fleet Broadband needs the dish
s.cn0 = 0; s.az.set((s.az.val + 90) % 360); run(1)
q.fbb_con.on = False; q.fbb_con.click(); run(0.3)
assert not q.fbb_con.on, "FBB connected without a dish lock"
az, el, _ = s.look(); s.az.set(round(az * 2) / 2); s.el.set(round(el * 2) / 2); run(0.5)
q.fbb_con.click(); run(0.3); assert q.fbb_con.on
q.b_grib.click()
until(lambda: "fbb_file:GRIB" in q.flags, 60, "GRIB download")
print("ok   Fleet Broadband rides on the Inmarsat dish")

# SARSAT: expired HRU, unregistered beacon, dead battery
z = app.sarsat
z.reset(); z.sw.set(1); z.hru.set(True); z.b_imm.click(); run(0.3)
assert not z.active and "hru_fail" in z.flags
z.hru.set(False); z.reg.set(False); z.batt.set(True); z.b_gnss.on = True; z.warp.set(3)
z.b_imm.click(); run(0.5)
assert z.active
until(lambda: z.next_burst is None, 60, "battery exhausted")
assert z.nburst == 3
z.reset(); z.sw.set(0); z.batt.set(False); z.reg.set(True); z.warp.set(0)
print("ok   SARSAT: beacon care faults")

# HF: AGC quietens the noise under a strong signal; QSB fades sky wave
app.goto("MF / HF SSB")
h.set_freq(23000.0); h.agc = "SLOW"; run(1.5)
quiet = np.sqrt(np.mean(app.gen_audio(app.audio.syn, 2208) ** 2))
st = max((x for x in HF_STATIONS if x["name"] == "NORTHSEA RADIO"), key=lambda x: w.hf_rx(x)["snr"])
h.set_freq(st["f"]); run(1.5)
fades = [h.qsb(st, w.hf_rx(st)) for _ in range(5) for __ in [run(1.0)]]
assert min(fades) < -0.5 or w.hf_rx(st)["mode"] == "GROUND", fades
h.agc = "OFF"; run(0.5); h.agc = "SLOW"
print("ok   HF: AGC / QSB (noise-only level %.3f)" % quiet)

# header controls
v0 = app.audio.master
app.handle(E(pygame.KEYDOWN, key=pygame.K_PAGEDOWN, mod=0, unicode=""))
assert app.audio.master < v0
mon = app.monitor_all
app.handle(E(pygame.MOUSEBUTTONDOWN, pos=app.r_mon.center, button=1))
assert app.monitor_all != mon
app.handle(E(pygame.KEYDOWN, key=pygame.K_F12, mod=0, unicode=""))
assert app.station is app.reference
app.handle(E(pygame.KEYDOWN, key=pygame.K_TAB, mod=pygame.KMOD_CTRL, unicode=""))
assert app.station is app.radar
app.handle(E(pygame.KEYDOWN, key=pygame.K_m, mod=pygame.KMOD_CTRL, unicode="m"))
assert app.audio.mute
app.handle(E(pygame.KEYDOWN, key=pygame.K_m, mod=pygame.KMOD_CTRL, unicode="m"))
print("ok   header: volume, monitor, F12, Ctrl+Tab, Ctrl+M")

total = sum(len(st.widgets) for st in app.stations)
print("     controls on the console: %d" % total)
for i in range(len(app.stations)):
    app.cur = i
    run(0.5)
    shot("final_%02d" % (i + 1))
print("ALL FEATURE TESTS PASS")
