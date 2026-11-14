"""Guided drills. Each drill sets up a scenario across the stations and
checks, live, that you perform each step on the real controls."""
import math
import pygame
from . import ui
from .ui import C, text, Button, Station
from .world import HF_STATIONS, HF_RT, HF_DSC


def _baseline(app):
    """Clear power, sensor and instructor faults left over from free play, so
    every drill starts from a healthy ship."""
    w = app.world
    p = getattr(app, "power", None)
    if p is not None:
        for t in (p.f_black, p.f_gen, p.f_weak, p.f_chg, p.f_earth):
            t.set(False)
        for b in p.brk.values():
            b.set(True)
        p.src.set(0)
        p.gsel.set(0)
        p.chg.set(1)
        p.dim.set(1.0)
        p.soc = max(p.soc, 0.9)
        p.acked |= p.active
    n = getattr(app, "nav", None)
    if n is not None:
        for t in (n.f_ant, n.f_jam, n.f_gyro, n.f_log, n.f_ais, n.dev_on, n.ais_silent):
            t.set(False)
        w.ais_device = None
        for t in (n.gps_pwr, n.gy_pwr, n.gps_hold):
            t.set(True)
        n.gps_datum.set(0)
        n.log_cal.set(0.0)
        n.gy_lat.set(round(w.lat))
        n.gy_spd.set(round(w.spd))
        n.man = None
        n.jam = 0.0
        n.ack_gps |= n.alarms_gps
        n.ack_ais |= n.alarms_ais
        n.alarms_ais.discard("NEW SRM")
    for st in ("vuhf", "hf", "navtex", "sat2"):
        x = getattr(app, st, None)
        if x is None:
            continue
        b = getattr(x, "pwr", None) if st != "hf" else x.pwr_b
        if b is not None:
            b.on = True
    app.mistakes = []


def _radar_ready(app, **kw):
    r, w = app.radar, app.world
    r.power.set(2)
    r.last_power, r.warm = "TX", 0.0
    r.spin = 1.0
    r.gz_b.on = r.ais_b.on = r.pm_b.on = False
    r.gz_alarm = r.lost_alarm = r.hdg_alarm = False
    r.vect_rel, r.vmin_i, r.ais_sel = False, 1, None
    r.nup.on = False
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
    n = getattr(app, "nav", None)
    if n is not None:
        n.gy_spd.set(round(kw.get("spd", 10.0)))
        n.gy_lat.set(round(w.lat))


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
        v.scan.on = False
        v.incoming = None
        v.comp.items, v.comp.debrief = [], None

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

    # ======================================================= new systems
    def s17(app):
        _radar_ready(app, sea=1, spd=0.0, ri=5)
        c = _place(app, "FV MORVORAN", 3.7, 200, 20, 18)
        c.box = (-60, 60, -60, 60)
    D.append(Drill("Radar 6: guard zone alarm", "RADAR",
        "A fishing vessel is closing from the south-south-west. Put a guard zone round the ship at 3 NM so the "
        "radar warns you of anything that comes inside - set the VRM first, the zone runs 0.5 NM out from it.",
        s17, [
            ("Set the VRM to about 3 NM, then switch GUARD ZONE on", lambda a: a.radar.gz_b.on and 2.5 <= (a.radar.gz_r0 or 0) <= 3.5),
            ("Wait for the GUARD ZONE alarm as the vessel runs in", lambda a: "gz_alarm" in a.radar.flags),
            ("Acknowledge it (ALARM ACK)", lambda a: not a.radar.gz_alarm and "alarm_ack" in a.radar.flags),
            ("Acquire the fishing vessel with ARPA", lambda a: any(t["c"].name == "FV MORVORAN" for t in a.radar.tracks)),
        ]))

    def s18(app):
        _radar_ready(app, sea=1, spd=0.0, ri=4)
        _place(app, "SY KITTIWAKE", 1.6, 320, 0, 0)
        _place(app, "PENHALE FERRY", 2.2, 40, 150, 12).box = (-60, 60, -60, 60)
    D.append(Drill("Radar 7: AIS and radar together", "RADAR",
        "AIS shows where targets SAY they are, a few seconds late; radar shows what is there now. A small yacht "
        "without AIS is near you. Use both.",
        s18, [
            ("Switch the AIS overlay on (ARPA panel)", lambda a: a.radar.ais_b.on),
            ("Click an AIS triangle and read its MMSI and call sign", lambda a: a.radar.ais_sel is not None),
            ("Acquire the echo that has NO AIS symbol - the yacht", lambda a: any(t["c"].name == "SY KITTIWAKE" for t in a.radar.tracks)),
            ("Change to RELATIVE vectors", lambda a: getattr(a.radar, "vect_rel", False)),
        ]))

    def s19(app):
        _radar_ready(app, sea=1, spd=10.0, ri=5, hdg=5.0)
        n = app.nav
        n.gy_spd.set(25)
        n.gy_lat.set(70)
        n.log_cal.set(6.0)
    D.append(Drill("Sensors 1: gyro and log errors", "NAV SENSORS / AIS",
        "The gyro's speed and latitude corrections have been left wrong and the speed log is out of calibration. "
        "Every radar bearing is turned by the gyro error and ARPA's true vectors are wrong. Correct them.",
        s19, [
            ("Open the NAV / AIS tab and read the gyro ERROR", lambda a: a.station is a.nav),
            ("Set SPEED CORR to the ship's speed and LAT CORR to her latitude (error under 0.2°)", lambda a: abs(a.nav.gyro_error()) < 0.2),
            ("Set the speed log CAL to 0 %", lambda a: abs(a.nav.log_cal.val) < 0.3),
            ("On the RADAR tab check that ARPA shows no gyro or log warning", lambda a: a.station is a.radar and abs(a.radar.gerr) < 0.3),
        ]))

    def s20(app):
        app.nav.f_ant.set(True)
    D.append(Drill("Sensors 2: GPS failure - manual DSC position", "NAV SENSORS / AIS",
        "The GPS antenna has failed. Without a position every DSC distress alert goes out with the 'position "
        "unknown' code. Enter the position by hand - and remember to update it.",
        s20, [
            ("Watch the GPS lose its fix (NO FIX)", lambda a: a.nav.fix == "NO FIX"),
            ("Acknowledge the GPS alarm", lambda a: "NO FIX" in a.nav.ack_gps),
            ("Set the position wheels (LOAD DR copies the chart position) and press ENTER", lambda a: a.nav.man is not None),
            ("Check the VHF DSC position source now reads MANUAL", lambda a: a.station is a.vuhf and (a.dsc_position() or (0, 0, ""))[2] == "MANUAL"),
        ]))

    def s21(app):
        n = app.nav
        n.dev_sel.set(0)
        n.dev_on.set(True)
        n._dev_idx = -1
    D.append(Drill("Sensors 3: AIS-SART detected", "NAV SENSORS / AIS",
        "An AIS-SART (MMSI 970...) has been switched on in a liferaft nearby. It shows on the AIS display and the "
        "radar AIS overlay as a red circle with a cross.",
        s21, [
            ("Acknowledge the AIS-SART alarm on the MKD", lambda a: "ais_ack" in a.nav.flags and "ais_sart_seen" in a.nav.flags),
            ("Select it in TARGETS (cursor) and open DETAIL with ENT", lambda a: str(a.nav.sel_mmsi or "").startswith("970") and a.nav.page == "DETAIL"),
            ("On the RADAR tab switch the AIS overlay on and find it", lambda a: a.station is a.radar and a.radar.ais_b.on),
        ]))

    def s22(app):
        nt = app.navtex
        for b in list(nt.b1.values()) + list(nt.b2.values()):
            b.on = True
        nt.flags.clear()
        nt.freq.set(0)
    D.append(Drill("NAVTEX: set up the receiver", "NAVTEX RECEIVER",
        "Select the stations and subjects you need. Distant transmitters only waste paper - but some subjects "
        "can never be switched off.",
        s22, [
            ("Deselect B1 stations L (NORTHSEA) and O (KERNVIK) - too far away", lambda a: not a.navtex.b1["L"].on and not a.navtex.b1["O"].on),
            ("Try to reject subject D (SAR) and see why you cannot", lambda a: "tried_reject" in a.navtex.flags),
            ("Reject subject H (LORAN messages)", lambda a: not a.navtex.b2["H"].on),
            ("Run a SELF TEST", lambda a: "self_test" in a.navtex.flags),
            ("Receive a message, select it and READ it", lambda a: a.navtex.page == "TEXT" and bool(a.navtex.mem)),
        ]))

    def s23(app):
        nt = app.navtex
        nt.flags.clear()
        nt.d_alarm.set(True)
        nt.b_inj.click()
    D.append(Drill("NAVTEX: SAR message alarm", "NAVTEX RECEIVER",
        "A SAR message (subject D) with serial 00 is broadcast: it is always printed and sounds the alarm.",
        s23, [
            ("Wait for the SAR alarm", lambda a: "sar_rx" in a.navtex.flags),
            ("Silence it (ALARM OFF)", lambda a: "alarm_ack" in a.navtex.flags),
            ("READ the message on the display", lambda a: a.navtex.page == "TEXT" and a.navtex.mem and a.navtex.mem[0]["b2"] == "D"),
        ]))

    def s24(app):
        v_clean(app)
        app.vuhf.ch = 16
        app.vuhf.nature.set(0)
        app.vuhf.comp.items = []
    def _mayday_ok(a):
        c = a.vuhf.comp
        if c.classify(c.keys) != "DISTRESS":
            return False
        _, chk, miss = c.evaluate(dict(keys=c.keys, all=c.keys, truncated=False, text=""))
        return all(ok for ok, _, _ in chk)
    D.append(Drill("VHF 4: compose and send a MAYDAY", "VHF / UHF",
        "Your ship is sinking. Send the DSC alert, then build the complete MAYDAY call and message with the "
        "MESSAGE COMPOSER and hold PTT until it has all been spoken. The coastguard answers what it heard.",
        s24, [
            ("Set NATURE OF DISTRESS to SINKING", lambda a: a.vuhf.nature.value == "SINKING"),
            ("Send the DSC distress alert (lift, hold 3 s)", lambda a: "distress_sent" in a.vuhf.flags),
            ("Compose the full call and message (MAYDAY x3 ... POB, OVER)", _mayday_ok),
            ("Hold PTT on CH16 until the whole message is spoken", lambda a: "mayday_composed_ok" in a.vuhf.flags),
        ]))

    def s25(app):
        v_clean(app)
        w = app.world
        app.vuhf.ch = 16
        app.vuhf.incoming = None
        w.say(70, w.srcs["CG"], "", 4.0, "dsc", dict(cat="INDIVIDUAL", ch=67, to=w.mmsi, text=(
            "MV TRAINER, THIS IS PENHALE COASTGUARD ON CHANNEL 67. A DIVER IS REPORTED MISSING 2 MILES NORTH OF "
            "YOU. PLEASE KEEP A LOOKOUT AND REPORT ANY SIGHTING. OVER.")))
        w._next = w.t + 80
    D.append(Drill("VHF 5: answer a DSC routine call", "VHF / UHF",
        "The coastguard calls you by DSC instead of on channel 16. Accept the call, listen on the working channel "
        "and reply.",
        s25, [
            ("Wait for the incoming individual call", lambda a: "indiv_rx" in a.vuhf.flags),
            ("Press SILENCE / ACCEPT - the radio moves to CH67", lambda a: "indiv_accept" in a.vuhf.flags and a.vuhf.ch == 67),
            ("Listen to the coastguard on CH67", lambda a: a.vuhf.flags.get("heard:PENHALE COASTGUARD", 0) > a.vuhf.flags.get("indiv_accept", 1e9)),
            ("Reply with PTT (2 s or more)", lambda a: "work_voiced" in a.vuhf.flags),
        ]))

    def s26(app):
        v_clean(app)
        app.vuhf.ch = 16
        app.vuhf.comp.items = []
    D.append(Drill("VHF 6: SECURITE broadcast", "VHF / UHF",
        "You have passed a large container floating just awash. Warn all ships: DSC safety announcement, then "
        "SECURITE x3, ALL STATIONS x3, THIS IS, name x3, the hazard, its position, OUT.",
        s26, [
            ("Send the DSC ALL SHIPS SAFETY announcement", lambda a: "allships_safety" in a.vuhf.flags),
            ("Compose and send the SECURITE message on CH16", lambda a: "securite_voiced" in a.vuhf.flags),
        ]))

    def s27(app):
        h_clean(app)
        h = app.hf
        bst = max((st for st in HF_STATIONS if st["name"] == "NORTHSEA RADIO"), key=lambda st: app.world.hf_rx(st)["snr"])
        h.set_freq(bst["f"])
        h.mode.set(0)
        h.agc = "OFF"
        h.nb_b.on = False
        h.rf.set(1.0)
    D.append(Drill("HF 4: static, AGC and the noise blanker", "MF / HF SSB",
        "Atmospheric static crashes are spoiling the copy and the AGC is off, so the strong station overloads "
        "the receiver. Set the receiver up properly.",
        s27, [
            ("Set AGC to SLOW (for SSB voice)", lambda a: a.hf.agc == "SLOW"),
            ("Switch the NOISE BLANKER on", lambda a: a.hf.nb_b.on),
            ("Copy 40 characters from NORTHSEA RADIO", lambda a: a.hf.flags.get("copy:NORTHSEA RADIO", 0) >= 40),
        ]))

    def s28(app):
        s12(app)
        s = app.satcom
        s.region.set(1)
        az, el, _ = s.look()
        s.az.set((az + 25) % 360)
        s.el.set(max(0, el - 12))
        s.b_peak.on = False
    D.append(Drill("Inmarsat 2: point the dish by ear", "INMARSAT",
        "Point the Fleet dish using only the PEAK TONE - no SHOW SOLUTION. Then lock, log in and prove the "
        "terminal with a link test.",
        s28, [
            ("Switch PEAK TONE on", lambda a: a.satcom.b_peak.on),
            ("Point the dish by ear: C/N0 above 50 dB-Hz without SHOW SOLUTION", lambda a: a.satcom.cn0 > 50 and not a.satcom.b_sol.on),
            ("Engage AUTO TRACK and LOG IN", lambda a: a.satcom.tracking and a.satcom.logged),
            ("Run a LINK TEST (PVT)", lambda a: "pvt" in a.satcom.flags),
        ]))

    def _satc_up(app):
        s = app.satcom
        s.region.set(1)
        s._reg = s.region.value
        az, el, _ = s.look()
        s.az.set(round(az * 2) / 2)
        s.el.set(round(el * 2) / 2)
        s.logged, s.busy = s.sat[0], None

    def s29(app):
        _satc_up(app)
        q = app.sat2
        q.flags.clear()
        q.ssas = None
        q.ssas_mode.set(1)
        q.lrit_on.set(True)
    D.append(Drill("SATCOM 2: SSAS test and LRIT", "SATCOM 2",
        "Test the Ship Security Alert System as agreed with the company security officer, and send an LRIT test "
        "report. SSAS goes out silently through Inmarsat-C.",
        s29, [
            ("Check SSAS MODE is TEST", lambda a: a.sat2.ssas_mode.value == "TEST"),
            ("Lift the cover of an SSAS button and hold it 2 s", lambda a: "ssas_test" in a.sat2.flags),
            ("Wait for the CSO's confirmation (printed on the Inmarsat-C printer)", lambda a: "ssas_test_ack" in a.sat2.flags),
            ("RESET the SSAS", lambda a: a.sat2.ssas is None),
            ("Send an LRIT TEST report", lambda a: "lrit_test" in a.sat2.flags),
        ]))

    def s30(app):
        q = app.sat2
        q.flags.clear()
        q.distress = None
        q.nature.set(0)
    D.append(Drill("SATCOM 2: Iridium distress alert", "SATCOM 2",
        "Alert by Iridium: it works everywhere, including the polar regions (Sea Area A4). The rescue "
        "co-ordination centre acknowledges and calls you back by voice.",
        s30, [
            ("Wait until the terminal is REGISTERED", lambda a: a.sat2.registered),
            ("Set NATURE to FLOODING", lambda a: a.sat2.nature.value == "FLOODING"),
            ("Lift the cover and hold DISTRESS 3 s", lambda a: "ir_distress" in a.sat2.flags),
            ("Wait for the RCC acknowledgement and voice call", lambda a: "ir_distress_acked" in a.sat2.flags),
        ]))

    def s31(app):
        app.power.test_res = None
        app.power.flags.clear()
    D.append(Drill("Power 1: daily battery check", "RADIO POWER",
        "Every day: read the radio battery voltage off load and on load, and check the insulation. Log the results.",
        s31, [
            ("Hold ON-LOAD TEST for at least 2 s", lambda a: "load_test" in a.power.flags),
            ("Check the result passed (above 24 V on load)", lambda a: bool(a.power.test_res and a.power.test_res["ok"])),
            ("Run the INSULATION TEST", lambda a: "ins_test" in a.power.flags),
        ]))

    def s32(app):
        _radar_ready(app)
        p = app.power
        p.flags.clear()
        p.f_black.set(True)
        _satc_up(app)
        app.satcom.b_auto.on = True
    D.append(Drill("Power 2: blackout", "RADIO POWER",
        "The main switchboard has failed. The GMDSS radios carry on from the battery; the emergency generator "
        "starts; the radar and the Fleet dish (AC only) go down and must be restarted.",
        s32, [
            ("Acknowledge the power alarms", lambda a: "alarm_ack" in a.power.flags),
            ("Watch the emergency generator start and take the AC load", lambda a: a.power.gen == "RUN"),
            ("Restart the radar: it lost power (STBY, warm-up, TX)", lambda a: a.radar.transmitting),
            ("Re-engage the Fleet dish AUTO TRACK on the INMARSAT tab", lambda a: a.satcom.tracking),
        ]))

    def s33(app):
        v_clean(app)
        app.power.brk["VHF"].set(True)
        app.power.brk["VHF"].trip()
    D.append(Drill("Power 3: tripped breaker", "ALL STATIONS",
        "The VHF has died. Check the obvious first: is it getting power?",
        s33, [
            ("Find the cause on the POWER tab", lambda a: a.station is a.power),
            ("Reset the tripped breaker (click once to OFF, again to ON)", lambda a: a.power.brk["VHF"].on and not a.power.brk["VHF"].tripped),
            ("Prove the VHF: radio check on CH16 (PTT 3 s)", lambda a: "radio_check" in a.vuhf.flags),
        ]))

    def s34(app):
        h_clean(app)
        b = app.bench
        b.b_r.on, b.b_s.on = False, True
        b.tracer.on = False
        b.inject("S", ["afa", "pdet", "afo", "ifl"][int(app.world.t * 1000) % 4])
    D.append(Drill("Fault-finding 3: the audio tracer", "CIRCUITS",
        "Use your ears: put the AUDIO TRACER on the probe and follow the signal until it stops.",
        s34, [
            ("Switch the AUDIO TRACER on", lambda a: a.bench.tracer.on),
            ("Probe at least three stages", lambda a: a.bench.probes >= 3),
            ("DECLARE the faulty block", lambda a: "diagnosed_S" in a.bench.flags),
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
        self.pitch = min(47.0, 768.0 / max(1, len(self.drills)))
        for i, d in enumerate(self.drills):
            self.btns.append(self.add(Button((36, 82 + i * self.pitch, 438, int(self.pitch) - 3), d.title, d.brief,
                                             size=11 if self.pitch > 30 else 9)))
        self.mist0 = 0
        self.b_start = self.add(Button((1250, 84, 150, 44), "START DRILL", "Set up the scenario and start the clock.", color="green", size=13))
        self.b_stop = self.add(Button((1410, 84, 164, 44), "ABANDON DRILL", "Stop the current drill.", color="red", size=13))
        self.b_go = self.add(Button((516, 304, 240, 34), "GO TO STATION", "Jump to the station where this drill takes place."))

    def start(self, i):
        d = self.drills[i]
        self.active, self.step, self.t0, self.done_t = d, 0, self.world.t, None
        _baseline(self.app)
        d.setup(self.app)
        self.app.mistakes = []

    def errors(self):
        return [m for m in self.app.mistakes if m[0] >= self.t0] if self.active else []

    def grade(self, secs, nerr):
        if nerr == 0:
            return "A" if secs < 90 * max(1, len(self.active.steps)) / 3.0 else "B"
        return "B" if nerr == 1 else ("C" if nerr <= 3 else "D")

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
                self.result = (len(self.errors()), self.grade(self.done_t, len(self.errors())))
                if d.best is None or self.done_t < d.best:
                    d.best = self.done_t
                    d.grade = self.result[1]

    def draw_status(self, s, r):
        d = self.active
        if not d:
            text(s, "No drill running - see the TRAINING tab (F11)", (r.x + 8, r.y + 9), 11, C["dim"], mono=False)
            return
        if self.done_t is not None:
            ne, g = getattr(self, "result", (0, "-"))
            text(s, "DRILL COMPLETE in %d s, %d error%s, grade %s: %s" % (self.done_t, ne, "" if ne == 1 else "s", g, d.title),
                 (r.x + 8, r.y + 9), 11, C["green"] if ne == 0 else C["amber"], bold=True, mono=False)
            return
        ne = len(self.errors())
        text(s, "DRILL  step %d/%d   %d s%s" % (self.step + 1, len(d.steps), self.world.t - self.t0,
                                               "   ERRORS %d" % ne if ne else ""), (r.x + 8, r.y + 2), 10,
             C["red"] if ne else C["amber"], bold=True)
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
        errs = self.errors() if run else []
        if run and self.done_t is not None:
            ne, g = getattr(self, "result", (0, "-"))
            text(s, "COMPLETE in %d seconds  -  GRADE %s" % (self.done_t, g), (530, y), 22,
                 C["green"] if ne == 0 else C["amber"], bold=True, mono=False)
        elif run:
            text(s, "RUNNING  %d s" % (self.world.t - self.t0), (530, y), 18, C["amber"], bold=True)
        else:
            text(s, "Press START DRILL. The scenario is set up for you: faults left over from free play are cleared.",
                 (530, y), 14, (90, 150, 110), mono=False)
        if errs:
            y += 36
            text(s, "OPERATING ERRORS (%d)" % len(errs), (530, y), 13, C["red"], bold=True)
            for i, (tm, stn, msg) in enumerate(errs[-6:]):
                ui.text_block(s, "%4d s  %s: %s" % (tm - self.t0, stn, msg), (530, y + 20 + i * 18, 1030, 18), 11,
                              C["amber"], mono=False)
        super().draw(s)
        for i, dd in enumerate(self.drills):
            if dd.best is not None:
                text(s, "%s %ds" % (getattr(dd, "grade", "OK"), dd.best), (468, 84 + i * self.pitch), 9, C["green"], bold=True, align="r")
