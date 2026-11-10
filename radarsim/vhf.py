"""Marine VHF radiotelephone with Class-A DSC controller, plus a V/UHF
AM/FM transceiver (aeronautical 118-137 MHz, UHF 225-400 MHz, on-board UHF).

Signals follow a line-of-sight link budget, so antenna height and distance
decide what you can hear - shown live in the LINK BUDGET panel.
"""
import math
import pygame
from . import ui
from .ui import C, text, Knob, Selector, Button, Guard, Station
from .world import vhf_channel, VHF_CHANNELS, VHF_USE, CPS, Src, fmt_lat, fmt_lon
from .radiocore import Monitor, garble

NATURES = ["UNDESIGNATED", "FIRE, EXPLOSION", "FLOODING", "COLLISION", "GROUNDING",
           "LISTING, CAPSIZING", "SINKING", "DISABLED AND ADRIFT", "ABANDONING SHIP",
           "PIRACY / ARMED ATTACK", "MAN OVERBOARD"]
PRESETS = [(121.5, "GUARD"), (123.1, "SAR"), (118.05, "ATIS"), (243.0, "MIL GUARD"),
           (282.8, "SAR UHF"), (457.525, "ON-BOARD")]
ATIS = ("PENHALE INFORMATION BRAVO. RUNWAY 27 IN USE. WIND 240 DEGREES 18 KNOTS. VISIBILITY 8 "
        "KILOMETRES IN RAIN. CLOUD BROKEN 1200 FEET. QNH 1002. ACKNOWLEDGE INFORMATION BRAVO.     ")
BOOK = ["CG", "NORDIC STAR", "ATLANTIC PEARL", "PENHALE FERRY", "FV MORVORAN"]


class VUHF(Station):
    name = "VHF / UHF"
    hint = ("Marine VHF + DSC on the left, air/UHF transceiver top right. Hold SPACE (or the PTT "
            "button) to transmit. The monitor shows what the loudspeaker is saying.")

    def __init__(self, app):
        super().__init__(app)
        w = self.world
        self.ch, self.mon = 16, Monitor()
        self.rxs = {"M": {}, "A": {}, "G": {}}
        self.key_ptt, self.tx, self.tx_t0 = False, False, 0.0
        self.atx, self.atx_t0 = False, 0.0
        self.dsc_log, self.dsc_alarm, self.distress = [], False, None
        self.burst_until, self.work = 0.0, None
        self.pending, self.seen, self.flags = [], set(), {}
        self.af = 121.5
        self.last_rx = None
        tipdsc = "Digital Selective Calling runs on channel 70 through a separate watch receiver. "
        self.pwr = self.add(Button((36, 246, 64, 40), "PWR", "Radio power.", toggle=True, on=True, color="green"))
        self.b16 = self.add(Button((106, 246, 64, 40), "16", "Instant select channel 16 "
            "(156.800 MHz): international distress, safety and calling.", color="red"))
        self.dual = self.add(Button((176, 246, 64, 40), "DUAL\nWATCH", "DUAL WATCH: keeps sampling "
            "channel 16 while you listen on a working channel; 16 takes priority.", toggle=True, size=10))
        self.hilo = self.add(Button((246, 246, 64, 40), "1W\nLOW", "Transmit power: lit = LOW (1 W), "
            "off = HIGH (25 W). Use low power in harbour and for close-range working.", toggle=True, size=10))
        self.chdn = self.add(Button((316, 246, 56, 40), "CH -", "Previous channel."))
        self.chup = self.add(Button((378, 246, 56, 40), "CH +", "Next channel."))
        self.vol = self.add(Knob(490, 150, 22, "VOLUME", 0, 1, 0.7, "Loudspeaker volume."))
        self.sql = self.add(Knob(570, 150, 22, "SQUELCH", 0, 1, 0.3, "SQUELCH: mutes the receiver "
            "until a signal exceeds the threshold. Set it just past where the noise stops - too "
            "high and you miss weak stations."))
        self.chk = self.add(Knob(676, 150, 34, "CHANNEL", encoder=True, on_turn=self._turn,
            tip="Channel selector. International channels 1-28 and 60-88. Duplex channels "
            "transmit 4.6 MHz below the coast station frequency."))
        self.ptt = self.add(Button((600, 236, 160, 56), "PTT  (SPACE)", "PRESS TO TALK: hold to "
            "transmit, release to listen. Simplex means only one station can talk at a time.", color="red", size=13))
        self.guard = self.add(Guard((456, 392, 120, 96), "DISTRESS", tipdsc + "DISTRESS: lift "
            "the cover, then HOLD the button 3 seconds. Sends MMSI, position, time and nature of "
            "distress to all stations, then switches to channel 16 for the MAYDAY voice call."))
        self.nature = self.add(Selector(668, 444, 22, "NATURE OF DISTRESS", NATURES, 0, tipdsc +
            "Select the nature of distress before sending, if time allows. UNDESIGNATED is sent otherwise."))
        self.addr = self.add(Selector(500, 554, 20, "ADDRESS", BOOK, 0, "DSC address book: the "
            "station (by MMSI) for an individual call."))
        self.wch = self.add(Selector(590, 554, 20, "WORK CH", ["06", "08", "72", "77", "67"], 0,
            "Working channel proposed in the DSC call. Both radios switch to it on acknowledgement."))
        self.b_ind = self.add(Button((660, 506, 104, 36), "INDIVIDUAL\nCALL", tipdsc +
            "Routine call to one station by MMSI - replaces calling by voice on channel 16.", size=10))
        self.b_saf = self.add(Button((660, 548, 104, 36), "ALL SHIPS\nSAFETY", tipdsc +
            "Safety announcement (SECURITE) to all stations, followed by voice on channel 16.", size=10))
        self.b_urg = self.add(Button((660, 590, 104, 36), "ALL SHIPS\nURGENCY", tipdsc +
            "Urgency announcement (PAN PAN) to all stations, followed by voice on channel 16.", size=10))
        self.b_sil = self.add(Button((456, 612, 96, 38), "SILENCE\nALARM", "Silence the DSC alarm "
            "and accept the received call.", size=10, color="green"))
        self.b_can = self.add(Button((558, 612, 96, 38), "CANCEL\nALERT", "FALSE ALERT: stops the "
            "automatic repetition. You must then cancel by voice on channel 16 to all stations.", size=10))
        # air / UHF radio
        self.amhz = self.add(Knob(1220, 140, 22, "MHz", encoder=True, on_turn=lambda n: self._atune(n * 1.0),
                                  tip="Coarse tuning, 1 MHz per click. 118-137 MHz AM air band, 156-174 FM marine, 225-400 AM UHF, 400-470 FM UHF."))
        self.akhz = self.add(Knob(1300, 140, 22, "kHz", encoder=True, on_turn=lambda n: self._atune(n * 0.025),
                                  tip="Fine tuning, 25 kHz per click."))
        self.avol = self.add(Knob(1380, 140, 22, "VOLUME", 0, 1, 0.7, "Loudspeaker volume."))
        self.asql = self.add(Knob(1460, 140, 22, "SQUELCH", 0, 1, 0.3, "Squelch threshold."))
        self.agrd = self.add(Selector(1540, 140, 22, "GUARD RX", ["OFF", "121.5", "243.0"], 1,
            "GUARD RECEIVER: a second receiver fixed on the emergency frequency (121.5 MHz civil, "
            "243.0 MHz military) regardless of the main frequency."))
        self.aptt = self.add(Button((1116, 84, 60, 102), "PTT", "Transmit on the air/UHF radio.", color="red"))
        self.apre = []
        for i, (f, nm) in enumerate(PRESETS):
            self.apre.append(self.add(Button((806 + i * 129, 240, 123, 38), "%.3f\n%s" % (f, nm),
                "Preset: %s %.3f MHz" % (nm, f), size=10)))

    # ---------------------------------------------------------------- helpers
    def after(self, delay, fn):
        self.pending.append((self.world.t + delay, fn))

    def _turn(self, n):
        i = VHF_CHANNELS.index(self.ch)
        self.ch = VHF_CHANNELS[(i + n) % len(VHF_CHANNELS)]

    def _atune(self, d):
        f = round((self.af + d) / 0.025) * 0.025
        self.af = max(108.0, min(470.0, f))

    @property
    def amode(self):
        return "AM" if (self.af < 137 or 225 <= self.af < 400) else "FM"

    @property
    def power_w(self):
        return 1.0 if (self.hilo.on or self.ch in (15, 17, 75, 76)) else 25.0

    def log(self, msg, color=None):
        self.dsc_log.append((self.world.utc_str()[:5], msg, color or C["lcdfg"]))
        del self.dsc_log[:-40]

    def beacons(self):
        w = self.world
        out = [dict(f=118.05, src=w.srcs["ATIS"], kind="voice", text=ATIS, key="atis")]
        if w.epirb_on:
            out.append(dict(f=121.5, src=Src("406 EPIRB HOMER (OWN)", w.x + 0.02, w.y, 2, 0.05),
                            kind="sweep", text="[SWEEP TONE] ", key="epirb"))
        return out

    def _rx(self, rid, f, thr, label):
        w, st = self.world, self.rxs[rid]
        best = None
        for m in w.msgs:
            if m.kind == "voice" and m.active(w.t) and abs(m.f - f) < 0.004:
                l = w.los_link(m.src, m.f)
                if best is None or l["pr"] > best[1]["pr"]:
                    best = (m, l, True)
        for b in self.beacons():
            if abs(b["f"] - f) < 0.004:
                l = w.los_link(b["src"], f)
                if best is None or l["pr"] > best[1]["pr"]:
                    best = (b, l, False)
        st.update(sig=None, link=None, open=False, kind=None, thr=thr, f=f)
        if not best or best[1]["pr"] < -121:
            return st
        m, l, is_msg = best
        st.update(sig=m, link=l, open=l["pr"] > thr, kind=m.kind if is_msg else m["kind"])
        q = min(1.0, max(0.2, (l["pr"] + 121) / 12.0))
        src = m.src if is_msg else m["src"]
        hdr = "%s  %s  %s  %d dBm" % (w.utc_str(), label, src.name, l["pr"])
        if is_msg:
            n = min(len(m.text), int((w.t - m.t0) * CPS))
            p = m.prog.get(rid, 0)
            if st["open"]:
                for i in range(p, n):
                    self.mon.feed((rid, id(m)), hdr, garble(m.text[i], q, i))
                if n > p:
                    self.flags["heard:" + src.name] = w.t
            m.prog[rid] = n
        elif st["open"]:
            i = int(w.t * CPS)
            if i != st.get("bi"):
                st["bi"] = i
                self.mon.feed((rid, m["key"]), hdr, garble(m["text"][i % len(m["text"])], q, i))
        return st

    # ------------------------------------------------------------------ DSC
    def send_distress(self):
        w = self.world
        nat = self.nature.value
        self.distress = dict(t0=w.t, nature=nat, acked=False, voiced=False, cancelled=False)
        self.flags["distress_sent"] = w.t
        self.flags["distress_nature"] = nat
        self.burst_until = w.t + 0.8
        self.ch = 16
        self.hilo.on = False
        self.log("TX DISTRESS ALERT  %s" % nat, C["red"])
        self.log("  POS %s %s" % (fmt_lat(w.lat), fmt_lon(w.lon)), C["red"])
        self.log("  AUTO CH16 - AWAIT ACKNOWLEDGEMENT", C["red"])
        d = self.distress

        def ack():
            if d is self.distress and not d["cancelled"]:
                if w.los_link(w.srcs["CG"], 156.525)["pr"] > -112:
                    d["acked"] = True
                    self.flags["distress_acked"] = w.t
                    self.log("RX DISTRESS ACK FROM 002320777", C["yellow"])
                    self.log("  PENHALE COASTGUARD (MRCC)", C["yellow"])
                    self.dsc_alarm = True
                else:
                    self.log("NO ACK - ALERT REPEATS AUTOMATICALLY", C["amber"])
                    self.after(20, ack)
        self.after(7, ack)

    def dsc_call(self, kind):
        w = self.world
        self.burst_until = w.t + 0.6
        if kind == "IND":
            who = self.addr.value
            src = w.srcs[who]
            wc = int(self.wch.value)
            self.log("TX INDIVIDUAL ROUTINE > %09d" % src.mmsi)
            self.log("  %s  PROPOSE CH%02d" % (src.name, wc))
            self.flags["indiv_sent"] = w.t

            def ack():
                if w.los_link(src, 156.525)["pr"] > -112 and getattr(src, "active", True):
                    use = 67 if who == "CG" else wc
                    self.log("RX ACK < %09d ABLE TO COMPLY CH%02d" % (src.mmsi, use), C["yellow"])
                    self.ch, self.work = use, (use, src)
                    self.flags["indiv_acked"] = w.t
                    w.say(use, src, "%s, THIS IS %s. RECEIVED YOUR D-S-C CALL. GO AHEAD. OVER." % (w.name, src.name), 2.0)
                else:
                    self.log("NO ACKNOWLEDGEMENT (OUT OF RANGE?)", C["amber"])
            self.after(4, ack)
        else:
            self.log("TX ALL SHIPS %s  WORK CH16" % kind, C["amber"])
            self.flags["allships_" + kind.lower()] = w.t
            self.ch = 16

    def _dsc_rx(self):
        w = self.world
        for m in w.msgs:
            if m.kind == "dsc" and m.t0 <= w.t and id(m) not in self.seen:
                self.seen.add(id(m))
                if not self.pwr.on or w.los_link(m.src, 156.525)["pr"] < -112:
                    continue
                d = m.dsc
                col = C["red"] if d["cat"] in ("DISTRESS", "DISTRESS RELAY") else C["yellow"]
                self.log("RX %s FROM %09d" % (d["cat"], m.src.mmsi), col)
                self.log("  %s" % m.src.name, col)
                if d.get("nature"):
                    self.log("  NATURE: %s" % d["nature"], col)
                if d.get("pos"):
                    self.log("  POS %s" % d["pos"], col)
                self.log("  LISTEN CH16. DO NOT ACK BY DSC.", col)
                self.dsc_alarm = True
                self.flags["dsc_rx_" + d["cat"].lower()] = w.t
                self.last_rx = m

    # --------------------------------------------------------------- update
    def handle(self, ev):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_SPACE:
            self.key_ptt = True
            return True
        if ev.type == pygame.KEYUP and ev.key == pygame.K_SPACE:
            self.key_ptt = False
            return True
        return super().handle(ev)

    def update(self, dt):
        w = self.world
        for item in list(self.pending):
            if w.t >= item[0]:
                self.pending.remove(item)
                item[1]()
        if self.b16.pop():
            self.ch = 16
        if self.chdn.pop():
            self._turn(-1)
        if self.chup.pop():
            self._turn(1)
        for b, (f, _) in zip(self.apre, PRESETS):
            if b.pop():
                self.af = f
        on = self.pwr.on
        if self.guard.pop_fired() and on:
            self.send_distress()
        if self.b_ind.pop() and on:
            self.dsc_call("IND")
        if self.b_saf.pop() and on:
            self.dsc_call("SAFETY")
        if self.b_urg.pop() and on:
            self.dsc_call("URGENCY")
        if self.b_sil.pop():
            if self.dsc_alarm:
                self.flags["alarm_silenced"] = w.t
            self.dsc_alarm = False
        if self.b_can.pop() and self.distress and not self.distress["cancelled"]:
            self.distress["cancelled"] = True
            self.flags["distress_cancelled"] = w.t
            self.log("ALERT REPETITION STOPPED", C["amber"])
            self.log("  NOW CANCEL BY VOICE ON CH16", C["amber"])
        self._dsc_rx()
        self.alert = self.dsc_alarm
        # marine PTT
        tx = on and (self.ptt.down or (self.key_ptt and self.app.station is self))
        if tx and not self.tx:
            self.tx_t0 = w.t
        if self.tx and not tx:
            self._released(w.t - self.tx_t0)
        self.tx = tx
        atx = self.aptt.down
        if atx and not self.atx:
            self.atx_t0 = w.t
        if self.atx and not atx:
            self._a_released(w.t - self.atx_t0)
        self.atx = atx
        # receivers
        thr = -124 + 40 * self.sql.val
        if on and not self.tx:
            st = self._rx("M", vhf_channel(self.ch)[1], thr, "CH%02d" % self.ch)
            if self.dual.on and self.ch != 16:
                g = self._rx("G", 156.8, thr, "CH16 (DW)")
                if g["open"]:
                    self.rxs["M"] = dict(g)
                    self.rxs["G"] = {}
        else:
            self.rxs["M"] = dict(open=False, sig=None, link=None, thr=thr)
        athr = -124 + 40 * self.asql.val
        if not self.atx:
            st = self._rx("A", self.af, athr, "%.3f %s" % (self.af, self.amode))
            if not st["open"] and self.agrd.idx:
                gf = float(self.agrd.value)
                self._rx("A", gf, athr, "GUARD %.1f" % gf)
        else:
            self.rxs["A"] = dict(open=False, sig=None, link=None, thr=athr)

    def _released(self, dur):
        w = self.world
        if self.ch == 70:
            self.mon.note(w.utc_str() + "  CH70", "[CHANNEL 70 IS DSC ONLY - VOICE TRANSMISSION INHIBITED]", C["red"])
            return
        if dur < 1.2:
            return
        self.mon.note("%s  TX CH%02d  %d W" % (w.utc_str(), self.ch, self.power_w),
                      "[YOU TRANSMITTED FOR %.0f s]" % dur, C["cyan"])
        self.flags["tx_ch%d" % self.ch] = w.t
        cg = w.srcs["CG"]
        ok = w.los_link(cg, 156.8, pw=self.power_w)["pr"] > -110
        d = self.distress
        if self.ch == 16 and d and not d["voiced"] and dur >= 4:
            if d["cancelled"]:
                self.flags["cancel_voiced"] = w.t
                if ok:
                    w.say(16, cg, "%s, THIS IS PENHALE COASTGUARD. YOUR CANCELLATION OF THE FALSE "
                          "DISTRESS ALERT IS RECEIVED. OUT." % w.name, 2.5)
                self.distress = None
                return
            d["voiced"] = True
            self.flags["mayday_voiced"] = w.t
            if ok:
                w.say(16, cg, "MAYDAY. %s, %s, %s. THIS IS PENHALE COASTGUARD, PENHALE COASTGUARD. "
                      "RECEIVED MAYDAY. RESCUE HELICOPTER 193 IS TASKED TO YOUR POSITION, ESTIMATED "
                      "20 MINUTES. ACTIVATE YOUR SART AND EPIRB. OVER." % (w.name, w.name, w.name), 3.0)
                heli = w.by_name["RESCUE 193"]
                heli.active = True
                heli.x, heli.y, heli.sog, heli.cog = w.x + 9, w.y + 13, 110, 215
                self.after(22, lambda: w.say(16, heli, "%s, THIS IS RESCUE 193. AIRBORNE AND PROCEEDING "
                           "TO YOUR POSITION. REQUEST YOU STAND BY 123 DECIMAL 1 AND FIRE A FLARE ON "
                           "REQUEST. OVER." % w.name))
        elif self.ch == 16 and dur >= 3 and not d and self.last_rx and w.t - self.last_rx.t0 < 400:
            src = self.last_rx.src
            self.flags["mayday_ack_voiced"] = w.t
            w.say(16, src, "MAYDAY. %s, THIS IS %s. THANK YOU FOR YOUR ACKNOWLEDGEMENT. FIRE IS IN THE ENGINE ROOM, "
                  "21 PERSONS ON BOARD. REQUEST YOU STAND BY TO ASSIST AND RELAY TO THE COASTGUARD. OVER." % (w.name, src.name), 2.5)
            self.last_rx = None
        elif self.ch == 16 and dur >= 2.5 and not d:
            if ok:
                self.flags["radio_check"] = w.t
                w.say(16, cg, "STATION CALLING PENHALE COASTGUARD, THIS IS PENHALE COASTGUARD. YOU ARE "
                      "LOUD AND CLEAR. FOR ROUTINE TRAFFIC USE CHANNEL 67. OUT.", 2.5)
            else:
                self.mon.note(w.utc_str(), "[NO REPLY - YOU ARE BEYOND RADIO RANGE AT THIS POWER]", C["amber"])
        elif self.work and self.ch == self.work[0] and dur >= 2:
            src = self.work[1]
            self.flags["work_voiced"] = w.t
            w.say(self.ch, src, "%s, %s. ROGER, ALL COPIED. BACK TO CHANNEL 16. OUT." % (w.name, src.name), 2.0)
            self.work = None

    def _a_released(self, dur):
        w = self.world
        if dur < 1.2:
            return
        self.mon.note("%s  TX %.3f MHz %s" % (w.utc_str(), self.af, self.amode), "[YOU TRANSMITTED FOR %.0f s]" % dur, C["cyan"])
        self.flags["atx_%.3f" % self.af] = w.t
        heli = w.by_name["RESCUE 193"]
        if abs(self.af - 123.1) < 0.004 and heli.active and w.los_link(heli, 123.1)["pr"] > -112:
            w.say(123.1, heli, "%s, RESCUE 193 ON 123 DECIMAL 1. READING YOU FIVE. I HAVE YOUR SART ON "
                  "RADAR, VISUAL IN TWO MINUTES. PREPARE TO RECEIVE THE WINCHMAN ON YOUR PORT QUARTER. OVER." % w.name, 2.0)

    # ----------------------------------------------------------------- audio
    def _radio_audio(self, syn, n, st, vol, sql_open, key):
        if st.get("open") and st.get("sig") is not None:
            if st["kind"] == "sweep":
                return syn.sweep(key, n) * vol
            src = st["sig"].src if hasattr(st["sig"], "src") else st["sig"]["src"]
            weak = max(0.0, min(1.0, (-104 - st["link"]["pr"]) / 16.0))
            return (syn.voice(key + src.name, n) * 1.6 + syn.noise(n) * weak) * vol
        if sql_open:
            return syn.noise(n) * 0.5 * vol
        return None

    def audio(self, syn, n):
        w = self.world
        out = 0
        if self.pwr.on and not self.tx:
            a = self._radio_audio(syn, n, self.rxs["M"], self.vol.val, self.sql.val < 0.12, "vm")
            if a is not None:
                out = out + a
        if not self.atx:
            a = self._radio_audio(syn, n, self.rxs["A"], self.avol.val, self.asql.val < 0.12, "va")
            if a is not None:
                out = out + a
        if w.t < self.burst_until:
            out = out + syn.fsk("dscv", n, 1200, 1700.0, 800.0) * 0.6
        return out if not isinstance(out, int) else None

    def bg_audio(self, syn, n):
        if self.dsc_alarm:
            return syn.alarm("dscal", n) * 0.35
        return None

    # ------------------------------------------------------------------ draw
    def tip_at(self, pos):
        t = super().tip_at(pos)
        if t:
            return t
        if pygame.Rect(790, 298, 800, 170).collidepoint(pos):
            return ("LINK BUDGET: received power = TX power + antenna gains - free-space loss - "
                    "diffraction loss beyond the radio horizon. Horizon (nm) = 2.22 x (sqrt(h1) + sqrt(h2)), heights in metres.")
        if pygame.Rect(790, 476, 800, 384).collidepoint(pos):
            return "RECEIVE MONITOR: a caption of the loudspeaker. '~' marks syllables lost to a weak signal."
        if pygame.Rect(20, 670, 760, 190).collidepoint(pos):
            return "PROCEDURE PROMPTER: the correct spoken procedure for the current situation, filled in with your ship's details."
        return ""

    def draw(self, s):
        w = self.world
        on = self.pwr.on
        ui.panel(s, (20, 54, 760, 300), "MARINE VHF RADIOTELEPHONE  156-162 MHz  FM (G3E)")
        ui.panel(s, (20, 362, 760, 300), "DSC CONTROLLER  CLASS A  -  CH70 WATCH RECEIVER")
        ui.panel(s, (20, 670, 760, 190), "PROCEDURE PROMPTER")
        ui.panel(s, (790, 54, 800, 236), "V/UHF AM-FM TRANSCEIVER  108-470 MHz  (AIR BAND / UHF / ON-BOARD)")
        ui.panel(s, (790, 298, 800, 170), "LINK BUDGET  -  LINE OF SIGHT")
        ui.panel(s, (790, 476, 800, 384), "RECEIVE MONITOR (LOUDSPEAKER CAPTION)")
        fg = C["lcdfg"]
        # --- marine LCD
        l = ui.lcd(s, (36, 80, 400, 150))
        st = self.rxs["M"]
        if on:
            tx_f, rx_f, dup = vhf_channel(self.ch)
            text(s, "%02d" % self.ch, (l.x + 14, l.y + 2), 76, fg, bold=True)
            text(s, "%.3f MHz" % (tx_f if self.tx else rx_f), (l.x + 130, l.y + 12), 22, fg, bold=True)
            text(s, ("DUPLEX  TX %.3f" % tx_f) if dup else "SIMPLEX", (l.x + 130, l.y + 42), 13, fg)
            text(s, "%d W %s" % (self.power_w, "LOW" if self.power_w < 2 else "HIGH"), (l.x + 130, l.y + 60), 13, fg)
            text(s, VHF_USE.get(self.ch, "PUBLIC CORRESPONDENCE" if dup else "INTERSHIP / PORT"), (l.x + 130, l.y + 78), 11, C["amber"], bold=True)
            pr = st["link"]["pr"] if st.get("link") else -130
            text(s, "SIG", (l.x + 14, l.y + 102), 11, fg, bold=True)
            ui.bar(s, (l.x + 46, l.y + 102, 190, 12), 1.0 if self.tx else (pr + 122) / 60.0,
                   "red" if self.tx else "green")
            text(s, "GPS %s %s  UTC %s" % (fmt_lat(w.lat), fmt_lon(w.lon), w.utc_str()[:5]), (l.x + 14, l.y + 126), 11, fg)
            ui.led(s, (l.x + 300, l.y + 107), "red", self.tx, "TX", 5)
            ui.led(s, (l.x + 340, l.y + 107), "green", bool(st.get("open")), "BUSY", 5)
            if self.dual.on:
                text(s, "DW 16", (l.x + 340, l.y + 60), 12, C["amber"], bold=True)
        # --- DSC LCD
        l = ui.lcd(s, (36, 390, 400, 256))
        if on:
            text(s, "DSC  MMSI %09d  WATCH CH70" % w.mmsi, (l.x + 10, l.y + 6), 12, fg, bold=True)
            ui.led(s, (l.right - 16, l.y + 14), "red" if self.dsc_alarm else "green",
                   not self.dsc_alarm or int(w.t * 4) % 2 == 0, None, 5)
            pygame.draw.line(s, (40, 80, 60), (l.x + 8, l.y + 26), (l.right - 8, l.y + 26), 1)
            lines = self.dsc_log[-13:]
            if not lines:
                text(s, "NO CALLS RECEIVED", (l.x + 10, l.y + 36), 12, C["dim"])
            for i, (tm, msg, col) in enumerate(lines):
                text(s, tm if not msg.startswith("  ") else "", (l.x + 10, l.y + 34 + i * 16), 11, C["dim"])
                text(s, msg[:44], (l.x + 52, l.y + 34 + i * 16), 11, col, bold=True)
            d = self.distress
            if d and not d["cancelled"]:
                msg = "DISTRESS ACKNOWLEDGED - VOICE MAYDAY ON CH16" if d["acked"] else \
                    "DISTRESS ALERT ACTIVE - NEXT REPEAT %3d s" % (240 - (w.t - d["t0"]) % 240)
                pygame.draw.rect(s, (120, 20, 16), (l.x + 4, l.bottom - 24, l.w - 8, 20))
                text(s, msg, (l.centerx, l.bottom - 14), 11, C["white"], bold=True, align="m")
        text(s, "1. LIFT   2. HOLD 3 s", (516, 492), 9, C["dim"], bold=True, align="c")
        # --- prompter
        ui.text_block(s, self.prompt(), (36, 694, 730, 162), 12, C["text"], lh=16)
        # --- air radio LCD
        l = ui.lcd(s, (806, 80, 300, 110))
        sa = self.rxs["A"]
        text(s, "%07.3f" % self.af, (l.x + 12, l.y + 6), 44, fg, bold=True)
        text(s, "MHz  %s" % self.amode, (l.x + 214, l.y + 14), 14, fg, bold=True)
        band = ("VHF AIR BAND" if self.af < 137 else "VHF MARINE/LAND" if self.af < 225 else
                "UHF MILITARY AIR" if self.af < 400 else "UHF LAND / ON-BOARD")
        text(s, band, (l.x + 12, l.y + 62), 12, C["amber"], bold=True)
        pr = sa["link"]["pr"] if sa.get("link") else -130
        ui.bar(s, (l.x + 12, l.y + 86, 180, 12), 1.0 if self.atx else (pr + 122) / 60.0, "red" if self.atx else "green")
        ui.led(s, (l.x + 214, l.y + 91), "red", self.atx, "TX", 5)
        ui.led(s, (l.x + 254, l.y + 91), "green", bool(sa.get("open")), "RX", 5)
        if self.agrd.idx:
            text(s, "G " + self.agrd.value, (l.x + 214, l.y + 62), 12, C["red"], bold=True)
        # --- link budget
        self._draw_link(s)
        self.mon.draw(s, (806, 502, 768, 346), 12)
        super().draw(s)

    def _draw_link(self, s):
        w = self.world
        x, y = 806, 322
        cols = [0, 96, 300, 372, 452, 528, 604, 690]
        for c, h in zip(cols, ["RADIO", "SOURCE", "DIST nm", "HORIZ nm", "FSPL dB", "RX dBm", "SQL dBm", "STATE"]):
            text(s, h, (x + c, y), 10, C["dim"], bold=True)
        show = None
        for i, (rid, nm) in enumerate((("M", "MARINE VHF"), ("A", "AIR / UHF"))):
            st = self.rxs[rid]
            yy = y + 18 + i * 18
            text(s, nm, (x, yy), 12, C["text"], bold=True)
            if st.get("link"):
                l = st["link"]
                src = st["sig"].src if hasattr(st["sig"], "src") else st["sig"]["src"]
                show = show or (l, src)
                beyond = l["over"] > 0
                vals = [src.name[:22], "%.1f" % l["d"], "%.1f" % l["horizon"], "%.1f" % l["fspl"], "%.0f" % l["pr"],
                        "%.0f" % st["thr"], ("OPEN" if st["open"] else "SQUELCHED") + (" (BEYOND HORIZON)" if beyond else "")]
                for c, v in zip(cols[1:], vals):
                    text(s, v, (x + c, yy), 12, C["green"] if st["open"] else C["amber"])
            else:
                text(s, "no carrier on frequency", (x + cols[1], yy), 12, C["dim"])
                if "thr" in st:
                    text(s, "%.0f" % st["thr"], (x + cols[6], yy), 12, C["dim"])
        # geometry sketch
        gx, gy, gw = 830, 458, 730
        pts = [(gx + gw * i / 40, gy - 16 * (1 - ((i - 20) / 20.0) ** 2)) for i in range(41)]
        pygame.draw.lines(s, C["blue"], False, pts, 2)
        a, b = pts[3], pts[37]
        h1 = 6 + min(14, w.h_ant * 0.5)
        pygame.draw.line(s, C["text"], a, (a[0], a[1] - h1), 2)
        text(s, "OWN ANT %d m" % w.h_ant, (a[0] + 8, a[1] - h1 - 6), 10, C["dim"], bold=True)
        if show:
            l, src = show
            h2 = 6 + min(30, math.sqrt(src.h) * 2.4)
            pygame.draw.line(s, C["text"], b, (b[0], b[1] - h2), 2)
            text(s, "%s %d m" % (src.name[:20], src.h), (b[0] - 8, b[1] - h2 - 6), 10, C["dim"], bold=True, align="r")
            col = C["green"] if l["over"] <= 0 else C["red"]
            pygame.draw.line(s, col, (a[0], a[1] - h1), (b[0], b[1] - h2), 1)
            text(s, "%.1f nm  -  radio horizon %.1f nm  -  %s" % (l["d"], l["horizon"],
                 "LINE OF SIGHT" if l["over"] <= 0 else "%.1f nm BEYOND HORIZON (diffraction loss)" % l["over"]),
                 (gx + gw / 2, 380), 11, col, bold=True, align="c")
        else:
            text(s, "Radio horizon (nm) = 2.22 x ( \u221ah1 + \u221ah2 )   heights in metres", (gx + gw / 2, 380), 11, C["dim"], align="c")

    def prompt(self):
        w = self.world
        pos = "%s %s" % (fmt_lat(w.lat), fmt_lon(w.lon))
        d = self.distress
        if d and d["cancelled"]:
            return ("FALSE ALERT CANCELLATION - hold PTT on CH16 and say:\n"
                    "ALL STATIONS, ALL STATIONS, ALL STATIONS. THIS IS %s, %s, %s, CALL SIGN %s, MMSI %d, "
                    "POSITION %s. CANCEL MY DISTRESS ALERT OF %s UTC. OVER." % (w.name, w.name, w.name, w.cs, w.mmsi, pos, w.utc_str()[:5]))
        if d:
            head = ("DSC ALERT ACKNOWLEDGED. " if d["acked"] else "DSC ALERT SENT - do not wait for the ack. ")
            if d["voiced"]:
                return ("MAYDAY CALL AND MESSAGE SENT. Keep watch on CH16, follow the coastguard's "
                        "instructions, prepare SART and EPIRB (see COSPAS-SARSAT tab). Use the "
                        "air radio on 123.100 MHz for the helicopter.")
            return (head + "Hold PTT on CH16 (4 s or more) and say:\n"
                    "MAYDAY, MAYDAY, MAYDAY. THIS IS %s, %s, %s. CALL SIGN %s, MMSI %d.\n"
                    "MAYDAY %s. MY POSITION IS %s. %s. I REQUIRE IMMEDIATE ASSISTANCE. "
                    "(number of persons on board, any other information). OVER."
                    % (w.name, w.name, w.name, w.cs, w.mmsi, w.name, pos, d["nature"]))
        m = self.last_rx
        if self.dsc_alarm and m:
            return ("DSC %s RECEIVED. 1) Silence the alarm. 2) Listen on CH16 for the voice message - "
                    "do NOT acknowledge by DSC (the coast station does that). 3) Log it. 4) If no "
                    "coast station responds and you can assist, acknowledge BY VOICE on CH16:\n"
                    "MAYDAY. %s (x3), THIS IS %s (x3). RECEIVED MAYDAY." % (m.dsc["cat"], m.src.name, w.name))
        if self.work:
            return ("DSC individual call acknowledged. Both radios are now on CH%02d. Hold PTT and pass "
                    "your message to %s, ending with OVER." % (self.work[0], self.work[1].name))
        return ("ROUTINE: call a known station with a DSC INDIVIDUAL CALL (pick ADDRESS and WORK CH) "
                "instead of hailing on CH16. RADIO CHECK: hold PTT on CH16 for 3 s.\n"
                "DISTRESS (grave and imminent danger only): select NATURE if time allows, lift the "
                "cover, hold DISTRESS for 3 s. The radio sends the alert on CH70 and moves to CH16. "
                "Then speak the MAYDAY call and message. Priorities: MAYDAY (distress) > PAN PAN "
                "(urgency) > SECURITE (safety) > routine.")
