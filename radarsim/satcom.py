"""Inmarsat station: a stabilised directional antenna you have to point at a
geostationary satellite (azimuth / elevation / blockage), a Fleet voice
handset with the two-digit safety codes, and an Inmarsat-C store-and-forward
terminal with distress alerting and EGC SafetyNET reception.
"""
import math
import pygame
from . import ui, fx
from .ui import C, text, Knob, Selector, Button, Guard, Station
from .world import INMARSAT, geo_look, fmt_lat, fmt_lon, wrap180
from .worldmap import WorldMap
from .radiocore import Monitor, Voice
from .vhf import NATURES

SAC = {
    "32": ("MEDICAL ADVICE", "RADIO MEDICAL SERVICE: DOCTOR ON THE LINE. DESCRIBE THE PATIENT'S AGE, SYMPTOMS, PULSE, TEMPERATURE AND ANY TREATMENT GIVEN."),
    "38": ("MEDICAL ASSISTANCE", "MRCC: MEDICAL ASSISTANCE / EVACUATION DESK. CONFIRM YOUR POSITION, COURSE, SPEED AND THE PATIENT'S CONDITION."),
    "39": ("MARITIME ASSISTANCE", "MRCC: MARITIME ASSISTANCE. STATE THE NATURE OF YOUR DIFFICULTY, POSITION AND PERSONS ON BOARD."),
    "41": ("METEOROLOGICAL REPORTS", "MET OFFICE: READY TO COPY YOUR WEATHER OBSERVATION (OBS)."),
    "42": ("NAVIGATIONAL HAZARDS", "NAVAREA CO-ORDINATOR: READY TO COPY YOUR HAZARD OR DERELICT REPORT."),
    "43": ("SHIP POSITION REPORTS", "POSITION REPORTING SERVICE: READY TO COPY (AMVER / AUSREP FORMAT)."),
}
EGC = [  # (area: NAVAREA number, 0 = addressed to a circle round a position (always for ships inside), -1 = FleetNET)
    (2, "SAFETYNET  NAVAREA II WARNING 318/26. BAY OF BISCAY. DERELICT FISHING VESSEL ADRIFT 46-12N 007-40W. WIDE BERTH REQUESTED."),
    (1, "SAFETYNET  METAREA I HIGH SEAS FORECAST. SOLE, SHANNON: SOUTHWEST 7 TO SEVERE GALE 9, VERY ROUGH OR HIGH, RAIN, MODERATE OR POOR."),
    (1, "SAFETYNET  NAVAREA I WARNING 207/26. ENGLISH CHANNEL WESTERN APPROACHES. CABLE OPERATIONS IN PROGRESS BY CS RESOLUTE 49-20N 006-10W. 1 MILE BERTH."),
    (0, "SAFETYNET  SAR. MRCC REQUESTS VESSELS WITHIN 50 MILES OF 49-30N 006-00W TO REPORT. RED FLARES SIGHTED. KEEP SHARP LOOKOUT."),
    (-1, "FLEETNET  COMPANY CIRCULAR 44. ALL MASTERS: BUNKER SAMPLING PROCEDURE REVISED, SEE SMS SECTION 7."),
    (3, "SAFETYNET  NAVAREA III WARNING 112/26. WESTERN MEDITERRANEAN. NAVAL EXERCISES SOUTH OF SARDINIA, LIVE FIRING."),
]
NAVAREAS = ["I", "II", "III", "IV"]
SAC_VOICE = {"32": "RADIO MEDICAL SERVICE", "38": "MRCC PENHALE", "39": "MRCC PENHALE", "41": "MET OFFICE",
             "42": "NAVAREA CO-ORDINATOR", "43": "POSITION REPORTING"}


class Satcom(Station):
    name = "INMARSAT"
    hint = ("Point the dish with AZIMUTH / ELEVATION until the signal peaks (PEAK TONE helps), engage AUTO TRACK, "
            "then LOG IN. Type on the keyboard to write an Inmarsat-C message.")
    power_key = "SATC"
    pan, bg_pan = 0.0, 0.55

    def __init__(self, app):
        super().__init__(app)
        self.map = WorldMap((30, 80, 880, 440))
        self.mon = Monitor()
        self.mon.snd = "printer"
        self._slew, self._lastp = 0.0, (90.0, 45.0)
        self.flags, self.pending = {}, []
        self.cn0, self.err, self.blocked = 0.0, 99.0, False
        self.tracking = False
        self.logged, self.busy = None, None           # region name; (label, t0, dur)
        self.msg, self.tx_log = "", []
        self.dial, self.call = "", None
        self.next_egc = 25.0
        self.distress = None
        self.voice = Voice("phone")
        self.egc_i, self.navarea_i = 0, 0
        self._locked, self._satc, self._fleet = False, True, True
        self.az = self.add(Knob(330, 622, 24, "AZIMUTH (TRUE)", 0, 360, 90, "Antenna azimuth, degrees true. "
            "The above-deck unit steers RELATIVE to the bow, so heading changes move it too.",
            wrap=True, step=0.5, fmt=lambda v: "%05.1f°" % v))
        self.el = self.add(Knob(430, 622, 24, "ELEVATION", 0, 90, 45, "Antenna elevation above the horizon. "
            "Below about 5° the link is unreliable (sea reflection, horizon).", step=0.5, fmt=lambda v: "%04.1f°" % v))
        self.region = self.add(Selector(540, 622, 24, "OCEAN REGION", [n for n, _ in INMARSAT], 1,
            "Ocean region satellite: AOR-W 54°W, AOR-E 15.5°W, IOR 64°E, POR 178°E. Pick the one "
            "with the highest elevation that also covers the shore station you need."))
        self.b_auto = self.add(Button((620, 580, 130, 38), "AUTO TRACK", "AUTO TRACK: once a signal is acquired "
            "(C/N0 above 44 dB-Hz) the antenna follows the satellite as the ship turns and rolls.", toggle=True, color="green"))
        self.b_sol = self.add(Button((760, 580, 140, 38), "SHOW SOLUTION", "Training aid: display the computed "
            "azimuth and elevation and the satellites on the sky plot.", toggle=True))
        self.b_log = self.add(Button((620, 626, 130, 38), "LOG IN / OUT", "Log the terminal in to the ocean region's "
            "Network Co-ordination Station. Required before sending or receiving."))
        self.b_pos = self.add(Button((760, 626, 140, 38), "SET SHIP POSITION", "Instructor: lit, then click the map to "
            "move the ship anywhere on Earth. Changes satellite geometry AND HF propagation.", toggle=True, size=10))
        y = 392
        self.b_new = self.add(Button((946, y, 116, 34), "NEW MESSAGE", "Clear the message editor."))
        self.les = self.add(Button((1068, y, 116, 34), "LES: x04", "Select the Land Earth Station that will forward the message."))
        self.b_pri = self.add(Button((1190, y, 116, 34), "ROUTINE", "Priority: ROUTINE / SAFETY / URGENCY."))
        self.b_send = self.add(Button((1312, y, 116, 34), "SEND", "Transmit the message (store-and-forward: it is "
            "queued at the LES, then delivered by telex/e-mail).", color="green"))
        self.b_view = self.add(Button((1434, y, 140, 34), "VIEW TX LOG", "Toggle between the editor and the transmit log.", toggle=True))
        self.les_i, self.pri_i = 1, 0
        self.guard = self.add(Guard((946, 440, 124, 104), "DISTRESS", "INMARSAT-C DISTRESS ALERT: lift the cover and "
            "hold 3 s. Sends identity, position, course, speed and nature via the LES straight to an MRCC with top priority."))
        self.nature = self.add(Selector(1160, 506, 22, "NATURE", NATURES, 0, "Nature of distress included in the alert."))
        self.keys = ui.keypad(self, 1440, 436, [["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"], ["*", "0", "#"]],
                              40, 25, 4, snd="dtmf", tip="Fleet voice handset. Two-digit safety codes: 32 medical advice, 38 medical "
                              "assistance, 39 maritime assistance, 41 met reports, 42 navigational hazards. Dial then CALL.")
        self.b_call = self.add(Button((1300, 482, 62, 34), "CALL", "Place the voice call through the directional antenna.", color="green"))
        self.b_end = self.add(Button((1368, 482, 62, 34), "END", "Clear the call / the dialled digits.", color="red"))
        self.b_peak = self.add(Button((300, 826, 130, 28), "PEAK TONE", "PEAK TONE: an audible pointing aid - the "
            "beep rises in pitch and speeds up as the received signal (C/N0) improves. Turn AZIMUTH and ELEVATION "
            "slowly for the highest note.", toggle=True, size=10))
        self.b_pvt = self.add(Button((946, 350, 150, 30), "LINK TEST (PVT)", "PERFORMANCE VERIFICATION TEST: the "
            "network checks the terminal's forward and return links and its distress alert path (no real alert is "
            "sent). Needs the terminal logged in.", size=10))
        self.b_area = self.add(Button((1102, 350, 150, 30), "EGC NAVAREA I", "EGC RECEIVER AREA: SafetyNET warnings "
            "are addressed to NAVAREAs / METAREAs. Select the area you are in (this coast is NAVAREA I) or you will "
            "miss the warnings meant for you.", size=10))
        self.b_msi = self.add(Button((1258, 350, 150, 30), "PRINT: ALL EGC", "EGC printing: ALL EGC, or MSI ONLY "
            "(SafetyNET maritime safety information, suppressing FleetNET commercial messages).", toggle=False, size=10))
        self.msi_only = False

    def after(self, delay, fn):
        self.pending.append((self.world.t + delay, fn))

    @property
    def sat(self):
        return INMARSAT[self.region.idx]

    def look(self):
        return geo_look(self.world.lat, self.world.lon, self.sat[1])

    def c_bars(self):
        """Inmarsat-C omni antenna: only needs the satellite above the horizon."""
        el = self.look()[1]
        return max(0, min(5, int((el + 1) / 4.0)))

    # --------------------------------------------------------------- events
    def handle(self, ev):
        if ev.type == pygame.KEYDOWN and not (ev.mod & pygame.KMOD_CTRL):
            snd = ("type", "type2", "type3")[(ev.key * 7) % 3]
            if ev.key == pygame.K_BACKSPACE:
                self.msg = self.msg[:-1]
                ui.sfx("type2", 0.6, pan=0.5)
                return True
            if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.msg += "\n"
                ui.sfx("type3", 0.8, pan=0.5)
                return True
            if ev.unicode and ev.unicode.isprintable() and len(self.msg) < 420:
                self.msg += ev.unicode.upper()
                ui.sfx(snd, 0.65, pan=0.5)
                return True
        if super().handle(ev):
            return True
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self.map.rect.collidepoint(ev.pos) and self.b_pos.on:
            la, lo = self.map.latlon(ev.pos)
            self.world.set_position(la, lo)
            self.b_pos.on = False
            self.logged, self.tracking, self.b_auto.on = None, False, False
            self.flags["moved"] = self.world.t
            self.mon.note(self.world.utc_str(), "SHIP RELOCATED TO %s %s - RE-ACQUIRE THE SATELLITE AND LOG IN AGAIN." %
                          (fmt_lat(self.world.lat), fmt_lon(self.world.lon)))
            return True
        return False

    def update(self, dt):
        w = self.world
        for item in list(self.pending):
            if w.t >= item[0]:
                self.pending.remove(item)
                item[1]()
        az, el, slant = self.look()
        satc, fleet = self.app.powered("SATC"), self.app.powered("FLEET")
        if satc != self._satc:
            self._satc = satc
            if not satc:
                if self.logged:
                    self.mon.note(w.utc_str(), "INMARSAT-C TERMINAL POWER LOST - LOGGED OUT.", C["red"])
                self.logged, self.busy = None, None
            else:
                self.mon.note(w.utc_str(), "INMARSAT-C TERMINAL RESTARTED. LOG IN AGAIN.", C["amber"])
        if fleet != self._fleet:
            self._fleet = fleet
            if not fleet:
                self.b_auto.on = self.tracking = False
                if self.call:
                    self.call = None
                    self.voice.text = None
                    self.mon.note(w.utc_str(), "FLEET ABOVE-DECK UNIT POWER LOST - CALL DROPPED.", C["red"])
        if (self.az.val, self.el.val) != self._lastp:
            self._lastp, self._slew = (self.az.val, self.el.val), w.t + 0.25
        if self.region.value != getattr(self, "_reg", None):
            self._reg = self.region.value
            if self.logged:
                self.mon.note(w.utc_str(), "OCEAN REGION CHANGED - LOGGED OUT OF %s." % self.logged)
            self.logged, self.tracking, self.b_auto.on = None, False, False
        # dish pointing
        e1, e2 = math.radians(self.el.val), math.radians(el)
        cs = math.sin(e1) * math.sin(e2) + math.cos(e1) * math.cos(e2) * math.cos(math.radians(self.az.val - az))
        self.err = math.degrees(math.acos(max(-1, min(1, cs))))
        rel = (self.az.val - w.hdg) % 360
        self.blocked = abs(wrap180(rel - 180)) < 12 and self.el.val < 25
        cn0 = 55.0 - 12.0 * (self.err / 10.0) ** 2
        if el < 5:
            cn0 -= (5 - el) * 5
        if self.blocked:
            cn0 -= 25
        self.cn0 = max(0.0, cn0) if fleet else 0.0
        if self.cn0 > 46 and not self._locked:
            self._locked = True
            ui.sfx("lock", 0.6, pan=-0.4 if self.app.station is self else self.bg_pan)
        elif self.cn0 < 40 and self._locked:
            self._locked = False
            ui.sfx("unlock", 0.6, pan=-0.4 if self.app.station is self else self.bg_pan)
        if self.b_auto.pop():
            if self.b_auto.on and self.cn0 < 44:
                self.b_auto.on = False
                self.mon.note(w.utc_str(), "AUTO TRACK REFUSED - NO SIGNAL LOCK (C/N0 %.0f dB-Hz). PEAK THE SIGNAL MANUALLY FIRST." % self.cn0, C["red"])
            elif self.b_auto.on:
                self.flags["tracking"] = w.t
        nav = getattr(self.app, "nav", None)
        if self.b_auto.on and nav is not None and not nav.gyro_ok:
            self.b_auto.on = False
            self.mon.note(w.utc_str(), "AUTO TRACK LOST - NO GYRO HEADING: THE DISH CANNOT STABILISE AS THE SHIP TURNS.", C["red"])
            self.mistake("Fleet dish auto-track needs a gyro heading - check the NAV / AIS tab.")
        self.tracking = self.b_auto.on
        if self.tracking:
            if el < 3:
                self.b_auto.on = self.tracking = False
            else:
                self.az.set(round(az * 2) / 2 % 360)
                self.el.set(max(0, round(el * 2) / 2))
        # Inmarsat-C
        if self.b_area.pop():
            self.navarea_i = (self.navarea_i + 1) % len(NAVAREAS)
        self.b_area.label = "EGC NAVAREA " + NAVAREAS[self.navarea_i]
        if self.b_msi.pop():
            self.msi_only = not self.msi_only
        self.b_msi.label = "PRINT: MSI ONLY" if self.msi_only else "PRINT: ALL EGC"
        if self.b_pvt.pop() and not self.busy:
            if not (self.logged and satc):
                ui.sfx("error", 0.6)
                self.mon.note(w.utc_str(), "PV TEST REFUSED - TERMINAL NOT LOGGED IN.", C["red"])
            else:
                self.busy = ("PV TEST WITH NCS %s" % self.logged, w.t, 6.0)
                ui.sfx("data", 0.6)

                def pvt():
                    self.busy = None
                    self.flags["pvt"] = w.t
                    self.mon.note(w.utc_str(), "PERFORMANCE VERIFICATION TEST PASSED: FORWARD LINK OK, RETURN LINK OK, "
                                  "DISTRESS ALERT TEST OK (NOT FORWARDED TO AN RCC). TERMINAL FULLY OPERATIONAL.", C["green"])
                    ui.sfx("chime", 0.6)
                self.after(6.0, pvt)
        if self.b_log.pop() and not self.busy:
            if not satc:
                ui.sfx("error", 0.6)
                self.mon.note(w.utc_str(), "TERMINAL HAS NO POWER - CHECK THE INMARSAT-C BREAKER ON THE POWER TAB.", C["red"])
            elif self.logged:
                self.mon.note(w.utc_str(), "LOGGED OUT OF %s." % self.logged)
                self.logged = None
            elif self.c_bars() < 1:
                self.mon.note(w.utc_str(), "LOGIN FAILED - %s SATELLITE IS BELOW THE HORIZON (ELEVATION %.0f°). SELECT ANOTHER OCEAN REGION." % (self.sat[0], el), C["red"])
            else:
                reg = self.sat[0]
                self.busy = ("SEARCHING NCS COMMON CHANNEL", w.t, 3.5)
                ui.sfx("login")

                def done():
                    self.busy, self.logged = None, reg
                    self.flags["logged_in"] = w.t
                    self.mon.note(w.utc_str(), "LOGIN ACKNOWLEDGED BY NCS %s. TERMINAL READY. EGC RECEIVER ENABLED." % reg, C["green"])
                self.after(3.5, done)
        if self.b_new.pop():
            self.msg = ""
        if self.les.pop():
            self.les_i = (self.les_i + 1) % 3
        if self.b_pri.pop():
            self.pri_i = (self.pri_i + 1) % 3
        self.les.label = "LES: %d%02d" % (self.region.idx, (1, 4, 2)[self.les_i])
        self.b_pri.label = ("ROUTINE", "SAFETY", "URGENCY")[self.pri_i]
        if self.b_send.pop() and not self.busy:
            if not self.logged:
                ui.sfx("error", 0.6)
                self.mon.note(w.utc_str(), "CANNOT SEND - NOT LOGGED IN TO AN OCEAN REGION.", C["red"])
            elif not self.msg.strip():
                self.mon.note(w.utc_str(), "CANNOT SEND - MESSAGE IS EMPTY. TYPE ON THE KEYBOARD.", C["red"])
            else:
                body, les = self.msg, self.les.label
                self.busy = ("TRANSMITTING TO " + les, w.t, 4.0)
                ui.sfx("data")

                def sent():
                    self.busy = None
                    self.tx_log.append((w.utc_str()[:5], les, self.b_pri.label, len(body), "STORED AT LES"))
                    self.flags["c_sent"] = w.t
                    self.mon.note(w.utc_str(), "MESSAGE %d CHARS ACCEPTED BY %s. REFERENCE %06d." % (len(body), les, int(w.t * 97) % 999999), C["green"])

                    def delivered():
                        self.tx_log[-1] = self.tx_log[-1][:4] + ("DELIVERED",)
                        self.mon.note(w.utc_str(), "DELIVERY NOTIFICATION: MESSAGE DELIVERED TO ADDRESSEE.", C["green"])
                    self.after(8, delivered)
                self.after(4.0, sent)
        if self.guard.pop_fired():
            self._distress()
        # EGC
        if self.logged and w.t > self.next_egc:
            self.next_egc = w.t + 45
            area, msg = EGC[self.egc_i % len(EGC)]
            self.egc_i += 1
            sel = self.navarea_i + 1
            if area == 0 or area == sel or (area == -1 and not self.msi_only):
                self.mon.note("%s  EGC RECEIVED VIA %s" % (w.utc_str(), self.logged), msg, C["lcdfg"])
                self.flags["egc"] = w.t
                if area == 1:
                    self.flags["egc_navarea1"] = w.t
        # handset
        for k, b in self.keys.items():
            if b.pop() and len(self.dial) < 14 and not self.call:
                self.dial += k
        if self.b_end.pop():
            self.dial, self.call = "", None
            self.voice.text = None
        if self.b_call.pop() and self.dial and not self.call:
            if self.cn0 < 46:
                ui.sfx("busy", 0.7)
                self.mon.note(w.utc_str(), "CALL FAILED - NO SATELLITE LINK ON THE DIRECTIONAL ANTENNA (C/N0 %.0f dB-Hz, need 46)." % self.cn0, C["red"])
                self.mistake("Inmarsat voice call attempted without a satellite lock on the Fleet dish.")
            else:
                num = self.dial.rstrip("#")
                self.call = "DIALLING"
                ui.sfx("ring")

                def conn():
                    if self.call is None:
                        return
                    self.call = "CONNECTED"
                    ui.sfx("connect")
                    self.flags["call:" + num] = w.t
                    if num in SAC:
                        self.mon.note("%s  VOICE  CODE %s  %s" % (w.utc_str(), num, SAC[num][0]), SAC[num][1], C["cyan"])
                        self.voice.say(SAC[num][1], SAC_VOICE.get(num, "MRCC PENHALE"), w.t, 0.6)
                    else:
                        self.mon.note("%s  VOICE  %s" % (w.utc_str(), num), "RINGING... SUBSCRIBER ANSWERED. (ONE-WAY DELAY %.0f ms - PAUSE BEFORE REPLYING.)" % (slant / 299.79 * 2), C["cyan"])
                        self.voice.say("PENHALE SHIPPING, OPERATIONS DESK. GOOD DAY CAPTAIN, GO AHEAD PLEASE.", "PENHALE SHIPPING", w.t, 0.6)
                self.after(3, conn)
        if self.call and self.cn0 < 40:
            self.call = None
            self.voice.text = None
            ui.sfx("busy", 0.6)
            self.mon.note(w.utc_str(), "CALL DROPPED - SATELLITE LINK LOST.", C["red"])

    def _distress(self):
        w = self.world
        if self.c_bars() < 1:
            self.mon.note(w.utc_str(), "DISTRESS ALERT NOT SENT - NO SATELLITE IN VIEW IN THIS OCEAN REGION.", C["red"])
            return
        nat, les = self.nature.value, self.les.label
        self.distress = dict(t0=w.t, acked=False)
        self.flags["c_distress"] = w.t
        ui.sfx("data")
        self.mon.note("%s  DISTRESS ALERT TRANSMITTED" % w.utc_str(),
                      "TO %s  MES 4%d  POS %s %s  UTC %s  CSE %03d SPD %d  NATURE: %s" %
                      (les, w.mmsi // 10, fmt_lat(w.lat), fmt_lon(w.lon), w.utc_str()[:5], w.hdg, w.spd, nat), C["red"])
        d = self.distress

        def ack():
            d["acked"] = True
            self.flags["c_distress_acked"] = w.t
            self.mon.note("%s  DISTRESS ACKNOWLEDGEMENT" % w.utc_str(),
                          "ALERT RECEIVED BY %s AND ROUTED TO THE ASSOCIATED MRCC. FOLLOW UP WITH A DISTRESS-PRIORITY "
                          "MESSAGE GIVING FULL DETAILS. KEEP THE TERMINAL ON." % les, C["yellow"])
        self.after(6, ack)

    def audio(self, syn, n):
        out = None
        if self.call == "CONNECTED":
            v = self.voice.chunk(n, self.world.t, 1.0)
            out = (syn.noise(n) * 0.01) if v is None else v + syn.noise(n) * 0.01
        if self.b_peak.on and self.app.powered("FLEET"):
            q = max(0.0, min(1.0, self.cn0 / 60.0))
            t = syn._time(n)
            rate = 1.5 + 9.0 * q ** 2
            gate = ((t * rate) % 1) < (0.5 if q < 0.76 else 0.9)
            tone = syn.osc("peak", 300.0 + 1400.0 * q ** 1.5, n) * gate * 0.14
            out = tone if out is None else out + tone
        return out

    def bg_audio(self, syn, n):
        out = None
        if self.world.t < self._slew and self.app.station is self and self.app.powered("FLEET"):   # antenna drive motors
            out = syn.osc("dish", 210.0, n) * 0.02 + syn.rumble("dishn", n, 8) * 0.07
        d = self.distress
        if d and d["acked"] and self.world.t - d["t0"] < 9:
            out = (0 if out is None else out) + syn.beep("satb", n, 1500.0, 5.0) * 0.3
        return out

    # ----------------------------------------------------------------- draw
    def tip_at(self, pos):
        t = super().tip_at(pos)
        if t:
            return t
        if self.map.rect.collidepoint(pos):
            return ("Coverage map: each dotted ring is the 5° elevation limit of one satellite (about 76° of "
                    "arc from the sub-satellite point). The poles are outside Inmarsat coverage - that is Sea Area A4.")
        if pygame.Rect(30, 560, 250, 290).collidepoint(pos):
            return "SKY PLOT: centre = zenith, outer ring = horizon, top = true north. The cross is where the dish points; the grey wedge is the mast blockage astern."
        if pygame.Rect(946, 80, 628, 262).collidepoint(pos):
            return "Inmarsat-C terminal (omnidirectional antenna, 600 bit/s store-and-forward). Type to edit the message."
        return ""

    def draw(self, s):
        w = self.world
        az, el, slant = self.look()
        ui.panel(s, (20, 54, 900, 470), "INMARSAT COVERAGE  -  FOUR OCEAN REGIONS (GEOSTATIONARY, 35 786 km)")
        ui.panel(s, (20, 532, 900, 328), "FLEET ABOVE-DECK ANTENNA  -  POINTING")
        ui.panel(s, (930, 54, 660, 500), "INMARSAT-C TERMINAL  (L-BAND  TX 1626.5-1646.5  RX 1530-1545 MHz)   |   FLEET HANDSET")
        ui.panel(s, (930, 562, 660, 298), "PRINTER / EVENT LOG")
        ui.crt(s, self.map.rect, gain=80)
        self.map.draw(s)
        cols = [(255, 120, 90), (255, 200, 70), (110, 220, 255), (190, 140, 255)]
        for i, (nm, lon) in enumerate(INMARSAT):
            sel = i == self.region.idx
            self.map.footprint(s, 0, lon, 76.3, cols[i], 3 if sel else 6, 2 if sel else 1)
            self.map.marker(s, 0, lon, cols[i], nm, "sq", 5 if sel else 4)
        x, y = self.map.marker(s, w.lat, w.lon, C["white"], None, "tri", 6)
        text(s, w.name, (x + 9, y - 5), 10, C["white"], bold=True)
        if self.b_pos.on and int(w.t * 2) % 2:
            text(s, "CLICK THE MAP TO PLACE THE SHIP", self.map.rect.center, 18, C["yellow"], bold=True, align="m")
        # sky plot
        cx, cy, R = 150, 700, 118
        pygame.draw.circle(s, (6, 14, 24), (cx, cy), R)
        for rr in (R, R * 2 // 3, R // 3):
            pygame.draw.circle(s, (40, 60, 84), (cx, cy), rr, 1)
        for d, lab in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
            a = math.radians(d)
            text(s, lab, (cx + math.sin(a) * (R + 10), cy - math.cos(a) * (R + 10)), 10, C["dim"], bold=True, align="m")

        def sky(a_, e_):
            a = math.radians(a_)
            k = R * (90 - max(0, e_)) / 90.0
            return cx + math.sin(a) * k, cy - math.cos(a) * k

        a0 = w.hdg + 180
        pygame.draw.polygon(s, (50, 50, 56), [sky(a0 - 12, 0), sky(a0 - 12, 25), sky(a0, 25), sky(a0 + 12, 25), sky(a0 + 12, 0)])
        hx, hy = sky(w.hdg, 0)
        pygame.draw.line(s, C["green"], (cx, cy), (hx, hy), 1)
        text(s, "BOW", (hx, hy - 12), 9, C["green"], bold=True, align="c")
        if self.b_sol.on:
            for i, (nm, lon) in enumerate(INMARSAT):
                a_, e_, _ = geo_look(w.lat, w.lon, lon)
                if e_ > 0:
                    p = sky(a_, e_)
                    pygame.draw.circle(s, cols[i], p, 5)
                    text(s, nm, (p[0] + 7, p[1] - 6), 9, cols[i], bold=True)
        p = sky(self.az.val, self.el.val)
        col = C["green"] if self.cn0 > 46 else (C["amber"] if self.cn0 > 30 else C["red"])
        pygame.draw.circle(s, col, p, 9, 2)
        pygame.draw.line(s, col, (p[0] - 13, p[1]), (p[0] + 13, p[1]), 1)
        pygame.draw.line(s, col, (p[0], p[1] - 13), (p[0], p[1] + 13), 1)
        mult, add = fx.round_glass(R)
        s.blit(mult, (cx - R, cy - R), special_flags=pygame.BLEND_RGB_MULT)
        s.blit(add, (cx - R, cy - R), special_flags=pygame.BLEND_RGB_ADD)
        pygame.draw.circle(s, (14, 15, 17), (cx, cy), R + 4, 5)
        pygame.draw.circle(s, (86, 90, 96), (cx, cy), R + 6, 1)
        text(s, "30°", (cx + 3, cy - R * 2 // 3 - 1), 8, C["dim"])
        text(s, "60°", (cx + 3, cy - R // 3 - 1), 8, C["dim"])
        # signal + data
        ui.meter(s, (296, 690, 210, 130), self.cn0 / 60.0, "C/N0  %.0f dB-Hz" % self.cn0,
                 [(0, "0"), (1 / 3, "20"), (2 / 3, "40"), (46 / 60, ""), (1, "60")], red_from=None)
        l = ui.lcd(s, (520, 680, 384, 168))
        fg = C["lcdfg"]
        rows = ["SAT   %s  %g\u00b0%s" % (self.sat[0], abs(self.sat[1]), "E" if self.sat[1] > 0 else "W"),
                "DISH  AZ %05.1f T (%05.1f REL)  EL %04.1f" % (self.az.val, (self.az.val - w.hdg) % 360, self.el.val),
                ("NEED  AZ %05.1f T  EL %04.1f   ERR %.1f" % (az, el, self.err)) if self.b_sol.on else "NEED  (press SHOW SOLUTION)",
                "RANGE %d km   DELAY ~%d ms via satellite" % (slant, slant / 299.79 * 2),
                "PATH LOSS %.1f dB @ 1.64 GHz" % (32.45 + 20 * math.log10(1640) + 20 * math.log10(slant)),
                "STATE %s" % ("BLOCKED BY MAST" if self.blocked else "BELOW HORIZON" if el < 0 else
                              "TRACKING" if self.tracking else "LOCK" if self.cn0 > 46 else "SEARCHING")]
        for i, r in enumerate(rows):
            text(s, r, (l.x + 10, l.y + 8 + i * 20), 12, fg if i != 5 else (C["green"] if self.cn0 > 46 else C["amber"]), bold=i in (0, 5))
        text(s, "beamwidth ~10°  |  need el > 5°", (l.x + 10, l.y + 148), 10, C["dim"])
        ui.led(s, (640, 566), "green", self.cn0 > 46, "SIGNAL LOCK", 5)
        ui.led(s, (760, 566), "red", self.blocked, "BLOCKAGE", 5)
        # Inmarsat-C screen
        l = ui.lcd(s, (946, 80, 628, 262), (8, 12, 30))
        fg = (150, 200, 255)
        bars = self.c_bars()
        text(s, "INMARSAT-C  MES 4%d  %s  %s" % (w.mmsi // 10, self.sat[0], ("LOGGED IN" if self.logged else "NOT LOGGED IN")),
             (l.x + 10, l.y + 6), 12, C["green"] if self.logged else C["amber"], bold=True)
        ui.bar(s, (l.right - 96, l.y + 8, 84, 12), bars / 5.0, "green", 5)
        text(s, "SIG", (l.right - 126, l.y + 7), 11, fg, bold=True)
        pygame.draw.line(s, (50, 70, 120), (l.x + 6, l.y + 26), (l.right - 6, l.y + 26), 1)
        if self.b_view.on:
            text(s, "UTC    LES       PRIORITY  CHARS  STATUS", (l.x + 10, l.y + 34), 12, fg, bold=True)
            for i, row in enumerate(self.tx_log[-12:]):
                text(s, "%-6s %-9s %-9s %-6d %s" % row, (l.x + 10, l.y + 54 + i * 18), 12, fg)
            if not self.tx_log:
                text(s, "(no messages sent)", (l.x + 10, l.y + 54), 12, C["dim"])
        else:
            text(s, "TO: %s    PRIORITY: %s    POS: %s %s" % (self.les.label, self.b_pri.label, fmt_lat(w.lat), fmt_lon(w.lon)),
                 (l.x + 10, l.y + 34), 12, fg)
            body = self.msg + ("_" if int(w.t * 2) % 2 else " ")
            if not self.msg:
                text(s, "Type your message here...", (l.x + 10, l.y + 60), 13, (70, 90, 130))
            ui.text_block(s, body, (l.x + 10, l.y + 60, l.w - 20, 160), 13, C["white"], lh=18)
        if self.busy:
            lab, t0, dur = self.busy
            f = min(1.0, (w.t - t0) / dur)
            pygame.draw.rect(s, (30, 40, 80), (l.x + 6, l.bottom - 26, l.w - 12, 20))
            pygame.draw.rect(s, (70, 120, 220), (l.x + 6, l.bottom - 26, (l.w - 12) * f, 20))
            text(s, "%s  %d%%" % (lab, f * 100), (l.centerx, l.bottom - 16), 11, C["white"], bold=True, align="m")
        else:
            text(s, "STATUS: IDLE   %d/420 chars" % len(self.msg), (l.x + 10, l.bottom - 20), 11, C["dim"])
        # handset
        l2 = ui.lcd(s, (1300, 440, 130, 34))
        text(s, self.dial[-12:] or "-", (l2.x + 8, l2.y + 8), 15, C["lcdfg"], bold=True)
        text(s, self.call or ("READY" if self.cn0 > 46 else "NO LINK"), (1365, 522), 10,
             C["green"] if self.call == "CONNECTED" else C["dim"], bold=True, align="c")
        self.mon.draw(s, (946, 588, 628, 260), 12)
        super().draw(s)
