"""Guided drills. Each drill sets up a scenario across the stations and
checks, live, that you perform each step on the real controls."""
import math
import pygame
from . import ui
from .ui import C, text, Button, Station
from .world import HF_STATIONS, HF_RT, HF_DSC


def _radar_ready(app, **kw):
    r, w = app.radar, app.world
    r.power.set(2)
    r.last_power, r.warm = "TX", 0.0
    r.afc.on = True
    r.tune.set(0.5)
    r.gain.set(0.65)
    r.stc.set(0.0)
    r.ftc.set(0.0)
    r.band.set(0)
    r.pulse.set(1)
    r.sea.set(kw.get("sea", 2))
    r.spd.set(kw.get("spd", 10.0))
    r.hdg.set(kw.get("hdg", 75.0))
    r.ri = kw.get("ri", 5)
    r.rain_b.on, w.rain = False, []
    r.int_b.on = False
    r.sol_b.on = False
    r.eav.on = r.es.on = r.trails.on = False
    w.by_name["SART"].active = False
    r.tracks, r.sel, r.cpa_alarm = [], None, False
    r.clear()
    app.bench.repair("R")


def _place(app, name, rng, brg, cog=None, sog=None):
    w = app.world
    c = w.by_name[name]
    a = math.radians(brg)
    c.x, c.y = w.x + rng * math.sin(a), w.y + rng * math.cos(a)
    if cog is not None:
        c.cog = cog
    if sog is not None:
        c.sog = sog
    c.active = True
    return c


def _on(app, name, d_rng, d_brg):
    """EBL/VRM laid on a contact within tolerance?"""
    r, w = app.radar, app.world
    rng, brg = w.rb(w.by_name[name])
    return (r.ebl_on.on and r.vrm_on.on and abs((r.ebl.val - brg + 180) % 360 - 180) < d_brg
            and abs(r.vrm.val * r.rmax - rng) < d_rng)


def _hf_snr(app, name):
    h, w = app.hf, app.world
    for st in HF_STATIONS:
        if st["name"] == name and abs(st["f"] - h.f) < 0.2:
            return w.hf_rx(st)["snr"]
    return -99


class Drill:
    def __init__(self, title, where, brief, setup, steps):
        self.title, self.where, self.brief, self.setup, self.steps = title, where, brief, setup, steps
        self.best = None


def build():
    D = []

    # ---------------------------------------------------------------- radar
    def s1(app):
        _radar_ready(app, ri=5)
        r = app.radar
        r.power.set(0)
        r.last_power, r.warm = "OFF", 20.0
        r.afc.on = False
        r.tune.set(0.22)
        r.gain.set(0.1)
    D.append(Drill("Radar 1: switch on, tune and set gain", "RADAR",
        "The set is cold and mis-adjusted. Bring it up in the correct order: stand-by, warm-up, "
        "transmit, range, tune, gain. Tune BEFORE judging gain - a detuned receiver looks like low gain.",
        s1, [
            ("Turn POWER to STBY and wait for the magnetron warm-up", lambda a: a.radar.power.value != "OFF" and a.radar.warm <= 0),
            ("Turn POWER to TX", lambda a: a.radar.transmitting),
            ("Select the 12 NM range scale", lambda a: a.radar.rmax == 12),
            ("With AFC off, adjust TUNE for a maximum on the TUNE bar", lambda a: a.radar.tune_ind > 0.9 and not a.radar.afc.on),
            ("Set GAIN so a light noise speckle just shows (about 55-78 %)", lambda a: 0.55 <= a.radar.gain.val <= 0.78),
            ("Switch AFC on to hold the tuning as the magnetron drifts", lambda a: a.radar.afc.on and a.radar.tune_ind > 0.9),
        ]))

    def s2(app):
        _radar_ready(app, sea=4, spd=0.0, ri=4)
        _place(app, "SY KITTIWAKE", 1.4, 300, 0, 0).rcs = 10
        app.radar.eav.on = False
    D.append(Drill("Radar 2: small target in sea clutter", "RADAR",
        "Sea state 4. A yacht with a poor radar reflector lies about 1.4 NM to the north-west, buried "
        "in sea clutter. Shorten the pulse to shrink the clutter cell, use just enough STC, then average. "
        "A real target stays in the same place sweep after sweep; clutter spikes do not.",
        s2, [
            ("Select SHORT pulse", lambda a: a.radar.pulse.value == "SHORT"),
            ("Raise SEA (STC) until the clutter just breaks up (45-80 %)", lambda a: 0.45 <= a.radar.stc.val <= 0.8),
            ("Switch on EAV (echo averaging) and wait a few sweeps", lambda a: a.radar.eav.on),
            ("Lay the EBL and VRM on the yacht (steady echo, NW, ~1.4 NM)", lambda a: _on(a, "SY KITTIWAKE", 0.12, 3.5)),
        ]))

    def s3(app):
        _radar_ready(app, sea=1, spd=0.0, ri=5)
        w = app.world
        app.radar.rain_b.on = True
        w.rain = [[w.x + 3.0, w.y - 2.0, 2.0, 22.0, 0.0, 0.0]]
        _place(app, "FV MORVORAN", 3.4, 118, 0, 0)
    D.append(Drill("Radar 3: target inside a rain squall", "RADAR",
        "A heavy squall lies to the south-east and a fishing vessel is somewhere inside it. On X-band "
        "the rain is a solid block. Use FTC to differentiate it away, then compare with S-band, "
        "which rain barely affects.",
        s3, [
            ("Raise RAIN (FTC) above 45 % and watch the block hollow out", lambda a: a.radar.ftc.val > 0.45),
            ("Switch to S-BAND and compare the rain return", lambda a: a.radar.band.idx == 1),
            ("Lay the EBL and VRM on the vessel in the squall", lambda a: _on(a, "FV MORVORAN", 0.2, 3.5)),
        ]))

    def s4(app):
        _radar_ready(app, sea=2, spd=0.0, ri=4)
        app.radar.band.set(1)
        _place(app, "SART", 6.8, 222, 0, 0)
    D.append(Drill("Radar 4: locate a SART", "RADAR",
        "A liferaft with an active SART is within 8 NM. A SART only answers 9 GHz (X-band) radars. "
        "Its response is a line of 12 dots leading AWAY from it: the dot nearest to you is the SART.",
        s4, [
            ("Select X-BAND (an S-band radar cannot trigger a SART)", lambda a: a.radar.band.idx == 0),
            ("Select the 12 NM range scale", lambda a: a.radar.rmax == 12),
            ("Lay the EBL along the line of dots", lambda a: abs((a.radar.ebl.val - a.world.rb(a.world.by_name["SART"])[1] + 180) % 360 - 180) < 3),
            ("Set the VRM on the NEAREST dot - that is the SART's position", lambda a: _on(a, "SART", 0.35, 3)),
        ]))

    def s5(app):
        _radar_ready(app, sea=1, spd=10.0, hdg=75.0, ri=6)
        w = app.world
        c = _place(app, "NORDIC STAR", 6.0, 100)
        a, b = math.radians(75), math.radians(100 + 180 + 1.5)
        vx, vy = 10 * math.sin(a) + 24 * math.sin(b), 10 * math.cos(a) + 24 * math.cos(b)
        c.cog, c.sog = math.degrees(math.atan2(vx, vy)) % 360, math.hypot(vx, vy)
        c.box = (-60, 60, -60, 60)
    D.append(Drill("Radar 5: ARPA collision assessment", "RADAR",
        "A ship fine on the starboard bow shows a steady bearing and closing range. Plot it with ARPA, "
        "read the CPA and TCPA, then take action. A crossing vessel on your starboard side is the "
        "stand-on vessel: you give way with a bold alteration to starboard.",
        s5, [
            ("Click the echo about 6 NM on the starboard bow to acquire it", lambda a: any(t["c"].name == "NORDIC STAR" for t in a.radar.tracks)),
            ("Wait for the plot: CPA under 0.5 NM raises the collision alarm", lambda a: any(t.get("danger") for t in a.radar.tracks)),
            ("Acknowledge the alarm (ALARM ACK)", lambda a: not a.radar.cpa_alarm),
            ("Alter course to starboard until the CPA exceeds 1.0 NM", lambda a: any(t["c"].name == "NORDIC STAR" and t.get("ready") and t.get("cpa", 0) > 1.0 and a.radar.hdg.val > 80 for t in a.radar.tracks)),
        ]))

    # ------------------------------------------------------------------ VHF
    def v_clean(app):
        v = app.vuhf
        v.flags.clear()
        v.distress, v.dsc_alarm, v.work, v.last_rx = None, False, None, None
        v.pwr.on = True
        v.sql.set(0.3)
        v.hilo.on = False

    def s6(app):
        v_clean(app)
        app.vuhf.ch = 12
        app.vuhf.nature.set(0)
    D.append(Drill("VHF 1: DSC distress alert and MAYDAY", "VHF / UHF",
        "Fire in the engine room, out of control. Send a designated DSC distress alert, then make the "
        "MAYDAY call and message by voice on channel 16. The prompter panel gives you the exact words.",
        s6, [
            ("Set NATURE OF DISTRESS to FIRE, EXPLOSION", lambda a: a.vuhf.nature.value == "FIRE, EXPLOSION"),
            ("Lift the cover and hold DISTRESS for 3 seconds", lambda a: "distress_sent" in a.vuhf.flags),
            ("Wait for the coast station's DSC acknowledgement", lambda a: "distress_acked" in a.vuhf.flags),
            ("Silence the alarm", lambda a: "alarm_silenced" in a.vuhf.flags),
            ("Hold PTT on CH16 for 4 s or more and read the MAYDAY message", lambda a: "mayday_voiced" in a.vuhf.flags),
        ]))

    def s7(app):
        v_clean(app)
        w, v = app.world, app.vuhf
        v.ch = 67
        src = _place(app, "NORDIC STAR", 8.0, 140, 250, 0)
        w.say(70, src, "", 5.0, "dsc", dict(cat="DISTRESS", nature="FIRE, EXPLOSION", pos="49°44'N 005°22'W"))
        w.say(16, src, "MAYDAY, MAYDAY, MAYDAY. THIS IS NORDIC STAR, NORDIC STAR, NORDIC STAR. CALL SIGN LAXR7. "
              "MAYDAY NORDIC STAR. POSITION 49 DEGREES 44 MINUTES NORTH, 005 DEGREES 22 MINUTES WEST. FIRE IN "
              "ENGINE ROOM. 21 PERSONS ON BOARD. REQUIRE IMMEDIATE ASSISTANCE. OVER.", 22.0)
        w._next = w.t + 70
    D.append(Drill("VHF 2: receiving another ship's distress", "VHF / UHF",
        "You are working channel 67 when a DSC distress alert arrives. A ship does NOT acknowledge "
        "by DSC - that would stop the alert repeating before a coast station hears it. Listen on 16, "
        "and if no coast station answers, acknowledge by voice.",
        s7, [
            ("Wait for the DSC distress alarm", lambda a: "dsc_rx_distress" in a.vuhf.flags),
            ("Silence the alarm and read the DSC display", lambda a: "alarm_silenced" in a.vuhf.flags),
            ("Select CH16 and listen to the MAYDAY", lambda a: a.vuhf.ch == 16 and "heard:NORDIC STAR" in a.vuhf.flags),
            ("Acknowledge by voice: hold PTT on CH16 for 3 s (MAYDAY... RECEIVED MAYDAY)", lambda a: "mayday_ack_voiced" in a.vuhf.flags),
        ]))

    def s8(app):
        v_clean(app)
        app.vuhf.ch = 16
        app.vuhf.addr.set(0)
        _place(app, "NORDIC STAR", 6.0, 60)
    D.append(Drill("VHF 3: routine DSC call to a ship", "VHF / UHF",
        "Call NORDIC STAR without using channel 16 for the initial call. A DSC individual call rings "
        "only her radio and agrees the working channel automatically.",
        s8, [
            ("Set ADDRESS to NORDIC STAR", lambda a: a.vuhf.addr.value == "NORDIC STAR"),
            ("Set WORK CH to 72", lambda a: a.vuhf.wch.value == "72"),
            ("Press INDIVIDUAL CALL", lambda a: "indiv_sent" in a.vuhf.flags),
            ("Wait for her acknowledgement - the radio moves to CH72", lambda a: "indiv_acked" in a.vuhf.flags and a.vuhf.ch == 72),
            ("Hold PTT for 2 s or more to pass your message", lambda a: "work_voiced" in a.vuhf.flags),
        ]))

    # ------------------------------------------------------------------- HF
    def h_clean(app):
        h = app.hf
        h.flags.clear()
        h.set_freq(2182.0)
        h.mode.set(0)
        h.rit.set(0)
        h.atu_f, h.distress = None, None
        app.bench.repair("S")

    def s9(app):
        h_clean(app)
        app.hf.rit.set(-170)
        app.hf.pred_i = 0
    D.append(Drill("HF 1: work a coast station on the right band", "MF / HF SSB",
        "Call NORTHSEA RADIO, about 1100 km away. She transmits on ITU channels 421, 816, 1221 and "
        "1621 (4, 8, 12, 16 MHz). Use the propagation panel to pick the band that is open NOW, then "
        "clarify, tune the antenna and call. Try it again after pressing UTC +1h a few times.",
        s9, [
            ("Enter the ITU channel with the best signal (e.g. 816 then CH)", lambda a: a.hf.split != 0 and _hf_snr(a, "NORTHSEA RADIO") > 10),
            ("Adjust the CLARIFIER until the voice is readable (copy 40 characters)", lambda a: a.hf.flags.get("copy:NORTHSEA RADIO", 0) >= 40),
            ("Press TUNE to match the antenna on the transmit frequency", lambda a: a.hf.atu_f and abs(a.hf.atu_f - a.hf.txf) / a.hf.txf < 0.004),
            ("Hold PTT for 3 s or more to call, and get an answer", lambda a: "hf_contact:NORTHSEA RADIO" in a.hf.flags),
        ]))

    D.append(Drill("HF 2: NAVTEX on 518 kHz", "MF / HF SSB",
        "NAVTEX broadcasts navigational and weather warnings as 100-baud FSK (SITOR-B) on 518 kHz. "
        "It is a ground-wave service, good for about 250-400 NM from the transmitter.",
        h_clean, [
            ("Enter 518 then kHz", lambda a: abs(a.hf.f - 518.0) < 0.12),
            ("Select FSK mode", lambda a: a.hf.mode.value == "FSK"),
            ("Copy 60 characters of the broadcast", lambda a: a.hf.flags.get("copy:PENHALE NAVTEX", 0) >= 60),
        ]))

    D.append(Drill("HF 3: DSC distress on the best HF band", "MF / HF SSB",
        "Outside VHF and MF range you alert by HF DSC. 8414.5 kHz is the usual first choice, but only "
        "if the path is open. Check the propagation panel for a distant station, choose the DSC band "
        "accordingly, send, and after the acknowledgement go to the paired R/T frequency.",
        h_clean, [
            ("Lift the cover and hold DISTRESS 3 s on a band that is open", lambda a: "hf_distress_sent" in a.hf.flags),
            ("Obtain a DSC acknowledgement (if none comes, change band and resend)", lambda a: "hf_distress_acked" in a.hf.flags),
            ("Press TO R/T FREQ to go to the associated radiotelephone frequency", lambda a: a.hf.f in HF_RT and HF_RT.index(a.hf.f) == HF_DSC.index(a.hf.flags["hf_distress_acked"])),
        ]))

    # ------------------------------------------------------------ satellite
    def s12(app):
        s = app.satcom
        s.flags.clear()
        s.region.set(3)
        s.az.set(0.0)
        s.el.set(10.0)
        s.b_auto.on = s.b_sol.on = False
        s.logged, s.msg, s.dial, s.call = None, "", "", None
    D.append(Drill("Inmarsat: acquire the satellite, log in, send", "INMARSAT",
        "The terminal is set to the Pacific satellite, which is below your horizon. Choose a visible "
        "ocean region, point the dish (use SHOW SOLUTION if you need to), lock, log in, send a "
        "message and place a medical-advice call.",
        s12, [
            ("Select an OCEAN REGION whose satellite is more than 5° above the horizon", lambda a: a.satcom.look()[1] > 5),
            ("Point the dish: get C/N0 above 46 dB-Hz", lambda a: a.satcom.cn0 > 46),
            ("Engage AUTO TRACK", lambda a: a.satcom.tracking),
            ("LOG IN to the ocean region", lambda a: a.satcom.logged),
            ("Type a message and SEND it", lambda a: "c_sent" in a.satcom.flags),
            ("Dial 32 and press CALL (radio medical advice)", lambda a: "call:32" in a.satcom.flags),
        ]))

    def s13(app):
        s = app.sarsat
        s.reset()
        s.flags.clear()
        s.sw.set(0)
        s.b_gnss.on, s.b_meo.on = True, False
        s.warp.set(0)
        s.sart.set(0)
    D.append(Drill("COSPAS-SARSAT: beacon without GNSS", "COSPAS-SARSAT",
        "See why a GNSS-equipped EPIRB matters. With no encoded position and no MEOSAR, the beacon "
        "can only be located by LEOSAR Doppler, and that means waiting for satellite passes.",
        s13, [
            ("Switch GNSS ENCODED off (MEOSAR is already off)", lambda a: not a.sarsat.b_gnss.on and not a.sarsat.b_meo.on),
            ("Turn the BEACON SWITCH to ON", lambda a: a.sarsat.active),
            ("Raise SIM TIME and wait for a LEOSAR Doppler location", lambda a: "doppler" in a.sarsat.flags),
            ("Wait for a second pass to resolve the A/B ambiguity", lambda a: a.sarsat.resolved),
            ("Switch the SART to ON for the final radar homing", lambda a: a.sarsat.sart.value == "ON"),
        ]))

    # --------------------------------------------------------------- faults
    def s14(app):
        _radar_ready(app)
        b = app.bench
        b.b_r.on, b.b_s.on = True, False
        b.inject("R", ["trig", "mod", "mag", "trl", "mix", "lo", "ifa", "det", "vid", "ant", "stc"][int(app.world.t * 1000) % 11])
        b._visited = False
    D.append(Drill("Fault-finding: radar transceiver", "CIRCUITS",
        "The radar has developed a fault. Look at the picture and indicators first, then trace the "
        "signal on the bench: find the first stage with good inputs and a dead output.",
        s14, [
            ("Observe the symptom on the RADAR tab", lambda a: a.station is a.radar),
            ("On the CIRCUITS tab, probe the stages and DECLARE the faulty block", lambda a: "diagnosed_R" in a.bench.flags),
        ]))

    def s15(app):
        h_clean(app)
        b = app.bench
        b.b_r.on, b.b_s.on = False, True
        b.inject("S", ["afa", "bal", "sbf", "cosc", "synth", "txm", "pa", "rxm", "ifl", "pdet", "afo"][int(app.world.t * 1000) % 11])
    D.append(Drill("Fault-finding: SSB transceiver", "CIRCUITS",
        "The MF/HF set is faulty. Check receive (S-meter, scope, audio) and transmit (PO meter on "
        "PTT) at the MF / HF tab to decide which chain is affected, then trace it on the bench. "
        "Use KEY TX on the bench to energise the transmit chain.",
        s15, [
            ("Observe the symptom on the MF / HF SSB tab", lambda a: a.station is a.hf),
            ("On the CIRCUITS tab (SSB TRANSCEIVER), DECLARE the faulty block", lambda a: "diagnosed_S" in a.bench.flags),
        ]))

    # -------------------------------------------------------------- capstone
    def s16(app):
        s6(app)
        h_clean(app)
        s12(app)
        app.satcom.region.set(1)
        s13(app)
        app.sarsat.b_gnss.on = True
    D.append(Drill("CAPSTONE: abandon ship - alert by every means", "ALL STATIONS",
        "Uncontrolled flooding, you will abandon ship. Alert by VHF DSC and voice, MF/HF DSC, "
        "Inmarsat-C, then activate the EPIRB and SART you will take to the liferaft. Work fast: "
        "the clock is running.",
        s16, [
            ("VHF: send a DSC distress alert (nature FLOODING or SINKING)", lambda a: a.vuhf.flags.get("distress_nature") in ("FLOODING", "SINKING", "ABANDONING SHIP")),
            ("VHF: voice MAYDAY on CH16 (PTT 4 s)", lambda a: "mayday_voiced" in a.vuhf.flags),
            ("MF/HF: send a DSC distress alert and get it acknowledged", lambda a: "hf_distress_acked" in a.hf.flags),
            ("INMARSAT-C: send a distress alert", lambda a: "c_distress" in a.satcom.flags),
            ("EPIRB: switch ON", lambda a: a.sarsat.active),
            ("SART: switch ON", lambda a: a.sarsat.sart.value == "ON"),
        ]))
    return D


class Training(Station):
    name = "TRAINING"
    hint = "Pick a drill and press START. The current step stays visible at the bottom right on every tab."

    def __init__(self, app):
        super().__init__(app)
        self.drills = build()
        self.sel, self.active, self.step, self.t0, self.done_t = 0, None, 0, 0.0, None
        self.btns = []
        for i, d in enumerate(self.drills):
            self.btns.append(self.add(Button((36, 84 + i * 47, 438, 40), d.title, d.brief, size=11)))
        self.b_start = self.add(Button((1250, 84, 150, 44), "START DRILL", "Set up the scenario and start the clock.", color="green", size=13))
        self.b_stop = self.add(Button((1410, 84, 164, 44), "ABANDON DRILL", "Stop the current drill.", color="red", size=13))
        self.b_go = self.add(Button((516, 304, 240, 34), "GO TO STATION", "Jump to the station where this drill takes place."))

    def start(self, i):
        d = self.drills[i]
        self.active, self.step, self.t0, self.done_t = d, 0, self.world.t, None
        d.setup(self.app)

    def update(self, dt):
        for i, b in enumerate(self.btns):
            if b.pop():
                self.sel = i
            b.on = i == self.sel
        if self.b_start.pop():
            self.start(self.sel)
            ui.sfx("beep2")
        if self.b_stop.pop():
            self.active = None
        if self.b_go.pop():
            wh = self.drills[self.sel].where
            if wh != "ALL STATIONS":
                self.app.goto(wh)
        d = self.active
        if d and self.done_t is None:
            while self.step < len(d.steps):
                try:
                    ok = d.steps[self.step][1](self.app)
                except Exception:
                    ok = False
                if not ok:
                    break
                self.step += 1
                ui.sfx("ok")
            if self.step >= len(d.steps):
                self.done_t = self.world.t - self.t0
                ui.sfx("done")
                if d.best is None or self.done_t < d.best:
                    d.best = self.done_t

    def draw_status(self, s, r):
        d = self.active
        if not d:
            text(s, "No drill running - see the TRAINING tab (F7)", (r.x + 8, r.y + 9), 11, C["dim"], mono=False)
            return
        if self.done_t is not None:
            text(s, "DRILL COMPLETE in %d s: %s" % (self.done_t, d.title), (r.x + 8, r.y + 9), 11, C["green"], bold=True, mono=False)
            return
        text(s, "DRILL  step %d/%d   %d s" % (self.step + 1, len(d.steps), self.world.t - self.t0), (r.x + 8, r.y + 2), 10, C["amber"], bold=True)
        ui.text_block(s, d.steps[self.step][0], (r.x + 8, r.y + 15, r.w - 14, 18), 11, C["white"], mono=False, bold=True)

    def draw(self, s):
        ui.panel(s, (20, 54, 470, 806), "DRILLS")
        ui.panel(s, (500, 54, 1090, 806), "BRIEFING")
        d = self.drills[self.sel]
        ui.crt(s, (512, 140, 1064, 150), (4, 9, 7))
        ui.crt(s, (512, 360, 1064, 484), (4, 9, 7))
        text(s, d.title, (516, 84), 20, C["amber"], bold=True, mono=False)
        text(s, "STATION: " + d.where, (516, 116), 12, C["cyan"], bold=True)
        ui.text_block(s, d.brief, (526, 150, 1036, 136), 15, C["lcdfg"], mono=False, lh=23)
        run = self.active is d
        y = 370
        ui.legend(s, "STEPS", (516, y - 28), 11, align="l")
        for i, (st, _) in enumerate(d.steps):
            done = run and i < self.step
            cur = run and i == self.step and self.done_t is None
            col = C["green"] if done else (C["white"] if cur else C["dim"])
            pygame.draw.rect(s, (16, 44, 30) if cur else (8, 18, 14), (522, y, 1044, 40), border_radius=5)
            pygame.draw.circle(s, col, (546, y + 20), 11, 0 if done else 2)
            if done:
                pygame.draw.lines(s, (10, 30, 14), False, [(540, y + 20), (545, y + 25), (553, y + 14)], 3)
            else:
                text(s, str(i + 1), (546, y + 20), 11, col, bold=True, align="m")
            text(s, st, (572, y + 11), 14, col, bold=cur, mono=False)
            y += 46
        y += 10
        if run and self.done_t is not None:
            text(s, "COMPLETE in %d seconds" % self.done_t, (530, y), 22, C["green"], bold=True, mono=False)
        elif run:
            text(s, "RUNNING  %d s" % (self.world.t - self.t0), (530, y), 18, C["amber"], bold=True)
        else:
            text(s, "Press START DRILL. The scenario is set up for you.", (530, y), 14, (90, 150, 110), mono=False)
        super().draw(s)
        for i, dd in enumerate(self.drills):
            if dd.best is not None:
                text(s, "OK %ds" % dd.best, (468, 88 + i * 47), 10, C["green"], bold=True, align="r")
