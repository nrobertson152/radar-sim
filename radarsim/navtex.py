"""Dedicated NAVTEX receiver.

NAVTEX broadcasts navigational and meteorological warnings and SAR
information as 100-baud FSK on 518 kHz (international, English), 490 kHz
(national language) and 4209.5 kHz. Each message starts ZCZC B1B2B3B4:
  B1  transmitter identity letter (A-Z) - select only the stations that
      cover your area,
  B2  subject (A nav warnings, B met warnings, C ice, D SAR / piracy,
      E forecasts, ...) - A, B, D and L can never be rejected,
  B3B4 serial number - a message already received cleanly is not printed
      again, except serial 00 which is always printed.
Reception follows the same propagation model as the MF/HF set: 518 kHz is a
ground-wave service of a few hundred miles; a weak or distant station prints
'*' for every corrupted character.
"""
import math
import numpy as np
import pygame
from . import ui, fx
from .ui import C, text, Knob, Selector, Button, Toggle, Station

LET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
B2_MEANING = {
    "A": "NAVIGATIONAL WARNINGS", "B": "METEOROLOGICAL WARNINGS", "C": "ICE REPORTS",
    "D": "SEARCH AND RESCUE INFORMATION / PIRACY ATTACK WARNINGS", "E": "METEOROLOGICAL FORECASTS",
    "F": "PILOT AND VTS SERVICE MESSAGES", "G": "AIS MESSAGES", "H": "LORAN MESSAGES", "I": "NOT USED",
    "J": "SATNAV (GNSS) MESSAGES", "K": "OTHER ELECTRONIC NAVAID MESSAGES",
    "L": "NAVIGATIONAL WARNINGS - ADDITIONAL TO A", "T": "TEST TRANSMISSIONS",
    "V": "SPECIAL SERVICES", "W": "SPECIAL SERVICES", "X": "SPECIAL SERVICES", "Y": "SPECIAL SERVICES",
    "Z": "NO MESSAGE ON HAND (QRU)"}
MUST = set("ABDL")
FREQS = [518.0, 490.0, 4209.5]
RATE = 8.0                      # decoded characters per second
SLOT = 40.0                     # seconds per transmitter slot (compressed from 10 minutes every 4 hours)
COLS = 34                       # printer characters per line

TX = [
    dict(b1="E", name="PENHALE", lat=50.2, lon=-5.1, f=518.0, kw=1.0, msgs=[
        ("A", "42", "NAVIGATIONAL WARNING 142. FAIRWAY BUOY 49-54N 005-27W RACON MIKE REPORTED UNRELIABLE."),
        ("B", "07", "GALE WARNING. SOUTHWEST GALE FORCE 8 EXPECTED SOON IN SEA AREAS LUNDY FASTNET AND PLYMOUTH."),
        ("D", "11", "SAR INFORMATION. RED FLARES REPORTED 12 MILES SOUTH OF PENHALE HEAD. VESSELS IN AREA KEEP A "
                    "SHARP LOOKOUT AND REPORT TO PENHALE COASTGUARD."),
        ("E", "23", "WEATHER FORECAST NEXT 24 HOURS. WIND SOUTHWEST 5 TO 7 INCREASING 8. SEA ROUGH. RAIN. "
                    "VISIBILITY MODERATE OCCASIONALLY POOR."),
        ("L", "05", "SURVEY VESSEL WORKING 2 MILES SOUTHWEST OF PENHALE HEAD. WIDE BERTH REQUESTED."),
        ("J", "03", "GNSS TESTING. GPS SIGNALS MAY BE UNRELIABLE WITHIN 50 MILES OF 50-10N 004-00W 0900 TO 1500 UTC."),
        ("F", "02", "PENHALE PILOT BOARDING POSITION MOVED 1 MILE SOUTH UNTIL FURTHER NOTICE.")]),
    dict(b1="O", name="KERNVIK", lat=58.2, lon=-6.4, f=518.0, kw=1.0, msgs=[
        ("A", "17", "NAVIGATIONAL WARNING 217. DANGEROUS WRECK 58-31N 007-02W. MARKED BY EAST CARDINAL BUOY."),
        ("B", "03", "STORM WARNING. SOUTHWEST STORM FORCE 10 IMMINENT IN SEA AREAS HEBRIDES AND BAILEY."),
        ("E", "31", "SHIPPING FORECAST. HEBRIDES SOUTHWEST 7 TO SEVERE GALE 9. HIGH. SQUALLY SHOWERS. POOR."),
        ("C", "01", "ICE REPORT. NO ICE REPORTED IN THE AREA.")]),
    dict(b1="W", name="CORMAC HEAD", lat=51.7, lon=-10.1, f=518.0, kw=1.0, msgs=[
        ("A", "88", "NAVIGATIONAL WARNING 88. CORMAC HEAD LIGHT UNLIT. MARINERS ARE ADVISED TO NAVIGATE WITH CAUTION."),
        ("D", "04", "SAR. FISHING VESSEL GRAINNE MISSING SINCE 0600 UTC IN THE AREA 51-20N 011-00W. VESSELS "
                    "REQUESTED TO KEEP A SHARP LOOKOUT."),
        ("B", "12", "GALE WARNING. WESTERLY GALE FORCE 8 SOLE AND FASTNET LATER."),
        ("E", "40", "FORECAST. FASTNET SOUTHWEST 6 TO GALE 8. ROUGH OR VERY ROUGH. GOOD OCCASIONALLY POOR.")]),
    dict(b1="A", name="BRESTAN", lat=48.4, lon=-4.9, f=518.0, kw=1.0, msgs=[
        ("A", "61", "NAVIGATIONAL WARNING 61. USHANT TRAFFIC SEPARATION SCHEME. CABLE SHIP RESTRICTED IN HER "
                    "ABILITY TO MANOEUVRE IN THE NORTHEAST LANE."),
        ("B", "09", "GALE WARNING. SOUTHWEST GALE FORCE 8 IN SEA AREA BISCAY."),
        ("E", "12", "FORECAST. BISCAY WEST 5 OR 6. MODERATE OR ROUGH. GOOD.")]),
    dict(b1="T", name="OSTMARK", lat=51.2, lon=2.9, f=518.0, kw=0.8, msgs=[
        ("A", "33", "NAVIGATIONAL WARNING 33. BUOYAGE CHANGE IN THE APPROACHES TO OSTMARK. CONSULT LOCAL NOTICES."),
        ("E", "08", "FORECAST. DOVER STRAIT SOUTHWEST 4 OR 5. SLIGHT OR MODERATE. FOG PATCHES."),
        ("G", "02", "AIS BASE STATION OSTMARK OUT OF SERVICE.")]),
    dict(b1="L", name="NORTHSEA", lat=55.5, lon=8.4, f=518.0, kw=1.0, msgs=[
        ("A", "70", "NAVIGATIONAL WARNING 70. DRILLING RIG MOVED TO 55-45N 004-12E. 500 METRE SAFETY ZONE."),
        ("B", "21", "GALE WARNING. NORTHWEST GALE FORCE 8 GERMAN BIGHT."),
        ("E", "15", "FORECAST. GERMAN BIGHT NORTHWEST 6 TO GALE 8. ROUGH. RAIN. MODERATE.")]),
    dict(b1="K", name="PENHALE NATIONAL", lat=50.2, lon=-5.1, f=490.0, kw=0.8, msgs=[
        ("A", "15", "INSHORE WARNING. PENHALE HARBOUR ENTRANCE DREDGING. KEEP CLEAR OF DREDGER ON CHANNEL 12."),
        ("E", "05", "INSHORE FORECAST. PENHALE HEAD TO LIZARD. SOUTHWEST 5 TO 7. MODERATE OR ROUGH. RAIN.")]),
    dict(b1="P", name="ATLANTIC HF NAVTEX", lat=43.4, lon=-8.4, f=4209.5, kw=1.0, msgs=[
        ("A", "90", "HIGH SEAS NAVIGATIONAL WARNING. CONTAINERS LOST OVERBOARD IN 46-10N 012-30W. DANGER TO SHIPPING."),
        ("B", "30", "STORM WARNING. LOW 968 NEAR 52N 28W MOVING EAST 25 KNOTS. STORM FORCE 10 WITHIN 300 MILES."),
        ("E", "60", "HIGH SEAS FORECAST NORTH ATLANTIC NORTH OF 31N. WINDS 45 TO 60 KNOTS. SEAS TO 11 METRES.")]),
]
for _t in TX:
    _t["key"] = "NAVTEX%s%g" % (_t["b1"], _t["f"])
    _t["pkw"] = _t["kw"]
    _t["ptr"] = 0


class Navtex(Station):
    name = "NAVTEX RECEIVER"
    tab = "NAVTEX"
    hint = ("Select the transmitters (B1) that cover your area and the subjects (B2) you want - A, B, D and L cannot "
            "be rejected. Messages print as they are received; '*' = corrupted character.")
    power_key = "NAVTEX"
    pan, bg_pan = 0.0, -0.45

    def __init__(self, app):
        super().__init__(app)
        self.rng = np.random.default_rng(77)
        self.mem, self.seen = [], set()
        self.log = []
        self.lines, self.line = [], ""
        self.paper = 900
        self.cur_tx = None                    # (tx, message dict) being transmitted
        self.slot_i, self.slot_t = -1, 0.0
        self.queue = []
        self.rx = None                        # message being received: dict
        self.page, self.cursor, self.scroll = "LIST", 0, 0
        self.alarm, self.flags = False, {}
        self.sig, self.cer_now = 0.0, 0.0
        self.inject = []
        self._pc = {}
        tb1 = "TRANSMITTER IDENTITY (B1): lit = messages from this station are accepted. Select the stations " \
              "whose coverage you are in or entering, so the printer is not flooded with distant warnings."
        self.b1 = {}
        for i, ch in enumerate(LET):
            tx = next((t for t in TX if t["b1"] == ch), None)
            tip = tb1 + ("  %s = %s (%g kHz)." % (ch, tx["name"], tx["f"]) if tx else "  %s: no station in this area." % ch)
            self.b1[ch] = self.add(Button((516 + (i % 13) * 43, 414 + (i // 13) * 30, 40, 26), ch, tip, toggle=True,
                                          on=True, size=11, color="green"))
        self.b2 = {}
        for i, ch in enumerate(LET):
            m = B2_MEANING.get(ch, "RESERVED")
            tip = "SUBJECT (B2) %s: %s.%s" % (ch, m, "  Cannot be rejected." if ch in MUST else "")
            self.b2[ch] = self.add(Button((516 + (i % 13) * 43, 504 + (i // 13) * 30, 40, 26), ch, tip, toggle=True,
                                          on=True, size=11, color="amber"))
        self.k_up = self.add(Button((516, 340, 90, 32), "▲", "Move up the message list / scroll the text."))
        self.k_dn = self.add(Button((612, 340, 90, 32), "▼", "Move down / scroll."))
        self.k_read = self.add(Button((708, 340, 90, 32), "READ", "Open the selected message (or back to the list).", size=10))
        self.k_del = self.add(Button((804, 340, 90, 32), "DEL", "Delete the selected message from memory.", size=10))
        self.k_prn = self.add(Button((900, 340, 90, 32), "PRINT", "Print the selected message again.", size=10))
        self.k_page = self.add(Button((996, 340, 88, 32), "PAGE", "Cycle LIST / SETUP / LOG pages.", size=10))
        self.pwr = self.add(Toggle(540, 690, "POWER", True, "NAVTEX receiver power. Memory and settings are kept "
            "while it is off (battery back-up)."))
        self.freq = self.add(Selector(636, 694, 24, "FREQUENCY", ["518 INT", "490 NAT", "4209.5"], 0,
            "518 kHz: international service in English. 490 kHz: national service in the local language. "
            "4209.5 kHz: HF NAVTEX for longer range."))
        self.dim = self.add(Knob(730, 694, 19, "DIMMER", 0.2, 1.0, 1.0, "Display brightness."))
        self.d_alarm = self.add(Toggle(806, 690, "SAR\nALARM", True, "Audible alarm on reception of a D (SAR) "
            "message or a serial-00 urgent message."))
        self.p_on = self.add(Toggle(872, 690, "PRINTER", True, "Printer on / off (messages are still stored in memory)."))
        self.b_ack = self.add(Button((924, 664, 160, 40), "ALARM OFF", "Silence the SAR alarm, then read the message.",
                                     color="red", size=11))
        self.b_test = self.add(Button((924, 712, 78, 34), "SELF\nTEST", "Print a test pattern and check the receiver.", size=9))
        self.b_clr = self.add(Button((1006, 712, 78, 34), "MEM\nCLEAR", "Erase the message memory and the list of "
            "received IDs (everything will print again).", size=9))
        self.b_inj = self.add(Button((924, 754, 160, 34), "INSTR: SAR MSG", "INSTRUCTOR: PENHALE broadcasts an urgent "
            "SAR message (serial 00) on receipt.", size=9, color="red"))
        self.b_feed = self.add(Button((150, 742, 80, 34), "FEED", "Line feed.", size=10))
        self.b_tear = self.add(Button((236, 742, 80, 34), "TEAR", "Tear off the printed paper.", size=10))
        self.b_roll = self.add(Button((322, 742, 92, 34), "NEW ROLL", "Load a new paper roll.", size=10))

    # --------------------------------------------------------- reception
    @property
    def on(self):
        return self.pwr.on and self.powered

    def path(self, tx):
        """Predicted reception of a NAVTEX transmitter: dict(snr dB, d km).
        MF (518 / 490 kHz) is a ground-wave service of roughly 250-400 NM by
        day; at night sky wave carries it much further, with fading. HF NAVTEX
        uses the ionospheric model of the MF/HF station."""
        w = self.world
        c = self._pc.get(tx["key"])
        if c is not None and w.t - c[0] < 2.0:
            return c[1]
        if tx["f"] > 3000:
            p = dict(w.hf_rx(tx))
        else:
            from .world import gc_dist, gc_mid, cos_zenith
            dkm = gc_dist(w.lat, w.lon, tx["lat"], tx["lon"])
            d = max(5.0, dkm / 1.852)
            snr = 46 + 10 * math.log10(tx["kw"]) - 20 * math.log10(max(d, 10) / 100.0) - 0.075 * max(0.0, d - 100)
            mla, mlo = gc_mid(w.lat, w.lon, tx["lat"], tx["lon"])
            if cos_zenith(mla, mlo, w.utc_h, w.doy) < -0.1:
                snr = max(snr, 25 - 0.012 * d + 4 * math.sin(w.t * 0.21 + d))
            p = dict(snr=snr, d=dkm)
        self._pc[tx["key"]] = (w.t, p)
        return p

    def rx_quality(self, tx):
        if FREQS[self.freq.idx] != tx["f"]:
            return None
        return self.path(tx)

    def _print_char(self, ch):
        if not (self.p_on.on and self.paper > 0 and self.on):
            return
        if ch == "\n" or len(self.line) >= COLS:
            self.lines.append(self.line)
            self.line = ""
            self.paper -= 1
            del self.lines[:-200]
            if ch == "\n":
                return
        self.line += ch
        if self.app.station is self or self.app.monitor_all:
            ui.sfx("dot", 0.35 if self.app.station is self else 0.12, pan=-0.6 if self.app.station is self else self.bg_pan)

    def _print_text(self, s):
        for ch in s:
            self._print_char(ch)

    def _feed(self, n=1):
        for _ in range(n):
            self._print_char("\n")

    def _log(self, msg, col=None):
        self.log.append((self.world.utc_str()[:5], msg, col or C["lcdfg"]))
        del self.log[:-40]

    def _next_message(self):
        """Pick what is on the air: injected urgent messages first, then the slot owner's queue."""
        w = self.world
        if self.inject:
            return self.inject.pop(0)
        slot = int(w.t // SLOT)
        if slot != self.slot_i:
            self.slot_i = slot
            tx = TX[slot % len(TX)]
            n = 2 if len(tx["msgs"]) > 2 else len(tx["msgs"])
            self.queue = []
            for _ in range(n):
                m = tx["msgs"][tx["ptr"] % len(tx["msgs"])]
                tx["ptr"] += 1
                self.queue.append((tx, m))
        if self.queue and w.t % SLOT < SLOT - 4:
            return self.queue.pop(0)
        return None

    def update(self, dt):
        w, t = self.world, self.world.t
        if self.b_inj.pop():
            tx = TX[0]
            self.inject.append((tx, ("D", "00", "MAYDAY RELAY. LIFERAFT WITH 4 PERSONS REPORTED IN POSITION 49-41N "
                                                "005-38W. ALL VESSELS IN THE AREA PROCEED WITH CAUTION AND REPORT TO "
                                                "PENHALE COASTGUARD.")))
            self.flags["sar_injected"] = t
        # what is being broadcast now
        if self.cur_tx is None or t >= self.cur_tx["end"]:
            if self.cur_tx is not None:
                self._end_message()
            nm = self._next_message()
            if nm:
                tx, (b2, ser, body) = nm
                txt = "ZCZC %s%s%s\n%s %s\n%s\nNNNN\n" % (tx["b1"], b2, ser, w.utc_str()[:5].replace(":", ""),
                                                        "UTC", body)
                self.cur_tx = dict(tx=tx, b2=b2, ser=ser, body=body, text=txt, t0=t, end=t + len(txt) / RATE + 1.0, i=0,
                                   id="%s%s%s" % (tx["b1"], b2, ser))
                self._start_message()
            else:
                self.cur_tx = None
        # characters arriving
        c = self.cur_tx
        self.sig, self.cer_now = 0.0, 0.0
        if c is not None:
            p = self.rx_quality(c["tx"]) if self.on else None
            if p is not None:
                self.sig = max(0.0, min(1.0, (p["snr"] + 5) / 40.0))
                self.cer_now = max(0.0, min(0.6, 0.5 - (p["snr"] - 4) / 24.0))
            n = min(len(c["text"]), int((t - c["t0"]) * RATE))
            while c["i"] < n:
                ch = c["text"][c["i"]]
                c["i"] += 1
                r = self.rx
                if r is None:
                    continue
                if ch not in " \n" and self.rng.random() < self.cer_now:
                    r["err"] += 1
                    ch = "*"
                r["n"] += 1 if ch != "\n" else 0
                r["text"] += ch
                if r["print"]:
                    self._print_char(ch)
        # controls
        if self.k_page.pop():
            self.page = {"LIST": "SETUP", "SETUP": "LOG", "LOG": "LIST", "TEXT": "LIST"}[self.page]
        if self.k_read.pop():
            self.page = "TEXT" if self.page == "LIST" and self.mem else "LIST"
            self.scroll = 0
            if self.page == "TEXT":
                self.mem[self.cursor]["read"] = True
        if self.k_up.pop():
            if self.page == "TEXT":
                self.scroll = max(0, self.scroll - 1)
            else:
                self.cursor = max(0, self.cursor - 1)
        if self.k_dn.pop():
            if self.page == "TEXT":
                self.scroll += 1
            else:
                self.cursor = min(max(0, len(self.mem) - 1), self.cursor + 1)
        if self.k_del.pop() and self.mem:
            del self.mem[self.cursor]
            self.cursor = max(0, min(self.cursor, len(self.mem) - 1))
            self.page = "LIST"
        if self.k_prn.pop() and self.mem:
            m = self.mem[self.cursor]
            self._feed()
            self._print_text("REPRINT " + m["id"] + "\n" + m["text"])
        if self.b_feed.pop():
            self._feed(3)
            ui.sfx("feed", 0.7)
        if self.b_tear.pop():
            self.lines, self.line = [], ""
            ui.sfx("paper", 0.9)
        if self.b_roll.pop():
            self.paper = 900
            ui.sfx("feed", 0.8)
            self.flags["new_roll"] = t
        if self.b_test.pop():
            if self.on:
                self._feed()
                self._print_text("SELF TEST  518/490/4209.5 OK\n" + "".join(LET) + "\n0123456789 ?!/-.,()\n"
                                 "MEMORY %d MSG  PAPER %d LINES\n" % (len(self.mem), self.paper))
                ui.sfx("beep2", 0.7)
                self.flags["self_test"] = t
        if self.b_clr.pop():
            self.mem, self.seen, self.cursor = [], set(), 0
            self._log("MEMORY CLEARED", C["amber"])
        if self.b_ack.pop():
            if self.alarm:
                self.flags["alarm_ack"] = t
            self.alarm = False
        # B2 rejection rules
        for ch in MUST:
            b = self.b2[ch]
            if not b.on:
                b.on = True
                ui.sfx("error", 0.6)
                self.flags["tried_reject"] = t
                self._log("%s CANNOT BE REJECTED (%s)" % (ch, B2_MEANING[ch][:24]), C["amber"])
        self.alert = self.alarm

    def _start_message(self):
        c = self.cur_tx
        if not self.on:
            self.rx = None
            return
        p = self.rx_quality(c["tx"])
        if p is None or p["snr"] < -2:
            self.rx = None
            return
        if self.rng.random() < max(0.0, min(0.6, 0.5 - (p["snr"] - 4) / 24.0)) * 0.5:
            self._log("ZCZC HEADER CORRUPT - MESSAGE LOST", C["amber"])
            self.rx = None
            return
        mid = c["id"]
        status, pr = "OK", True
        if not self.b1[c["tx"]["b1"]].on:
            status, pr = "B1 %s NOT SELECTED" % c["tx"]["b1"], False
        elif not self.b2[c["b2"]].on:
            status, pr = "B2 %s REJECTED" % c["b2"], False
        elif mid in self.seen and c["ser"] != "00":
            status, pr = "ALREADY RECEIVED", False
        self.rx = dict(id=mid, tx=c["tx"], b2=c["b2"], ser=c["ser"], text="", n=0, err=0, print=pr, status=status,
                       snr=p["snr"])
        if pr:
            self._feed()
        self._log("%s %s  %s  SNR %d" % (mid, c["tx"]["name"][:12], status, p["snr"]), C["lcdfg"] if pr else C["dim"])

    def _end_message(self):
        r = self.rx
        self.rx = None
        if r is None or not r["print"]:
            return
        cer = r["err"] / float(max(1, r["n"]))
        w = self.world
        if cer > 0.33:
            self._print_text("\n*** CER %d%% - NOT STORED ***\n" % (cer * 100))
            self._log("%s REJECTED  CER %d%%" % (r["id"], cer * 100), C["red"])
            return
        st = "STORED" if cer < 0.04 else "ERRORS"
        if cer < 0.04:
            self.seen.add(r["id"])
        self.mem.insert(0, dict(id=r["id"], b1=r["tx"]["b1"], b2=r["b2"], ser=r["ser"], text=r["text"],
                                utc=w.utc_str()[:5], cer=cer, read=False, name=r["tx"]["name"]))
        del self.mem[60:]
        self.cursor = 0
        self.flags["rx:" + r["id"]] = w.t
        self.flags["rx_count"] = self.flags.get("rx_count", 0) + 1
        self._log("%s %s  CER %d%%" % (r["id"], st, cer * 100), C["green"] if st == "STORED" else C["amber"])
        if (r["b2"] == "D" or r["ser"] == "00") and self.d_alarm.on:
            self.alarm = True
            self.flags["sar_rx"] = w.t
        ui.sfx("feed", 0.4, pan=self.bg_pan)

    def bg_audio(self, syn, n):
        if self.alarm and self.on:
            return syn.beep("ntxal", n, 2900.0, 2.5) * 0.25
        return None

    # ----------------------------------------------------------------- draw
    def tip_at(self, pos):
        t = super().tip_at(pos)
        if t:
            return t
        if pygame.Rect(36, 80, 438, 640).collidepoint(pos):
            return "PRINTER: newest line just above the slot. '*' marks a character received in error."
        if pygame.Rect(1126, 488, 448, 230).collidepoint(pos):
            return "COVERAGE: each circle is about the daytime ground-wave range of a transmitter. At night 518 kHz carries further but with more interference."
        return ""

    def draw(self, s):
        w, t = self.world, self.world.t
        ui.panel(s, (20, 54, 470, 806), "PRINTER")
        ui.panel(s, (500, 54, 600, 530), "NAVTEX CONTROL UNIT  518 / 490 / 4209.5 kHz")
        ui.panel(s, (500, 592, 600, 268), "SETTINGS AND ALARM")
        ui.panel(s, (1110, 54, 480, 400), "RECEPTION")
        ui.panel(s, (1110, 462, 480, 398), "NAVTEX STATIONS IN THE AREA")
        self._draw_printer(s)
        self._draw_lcd(s)
        text(s, "TRANSMITTER (B1)  -  select the stations covering your area", (516, 398), 10, C["dim"], bold=True)
        text(s, "SUBJECT (B2)  -  A B D L cannot be rejected", (516, 488), 10, C["dim"], bold=True)
        ui.text_block(s, "A NAV WARN  B MET WARN  C ICE  D SAR/PIRACY  E MET FCST  F PILOT/VTS  G AIS  H LORAN  "
                         "J SATNAV  K NAVAIDS  L NAV ADDITIONAL  T TEST  V-Y SPECIAL  Z QRU",
                      (516, 800, 570, 50), 10, C["dim"], lh=13)
        ui.led(s, (530, 618), "green", self.on, "POWER", 5, 9)
        ui.led(s, (620, 618), "amber", self.on and self.rx is not None, "RX MSG", 5, 9)
        ui.led(s, (720, 618), "red", self.alarm and int(t * 3) % 2 == 0, "SAR ALARM", 5, 9)
        ui.led(s, (830, 618), "amber", self.paper < 150, "PAPER LOW", 5, 9)
        self._draw_rx(s)
        self._draw_map(s)
        super().draw(s)

    def _draw_printer(self, s):
        r = pygame.Rect(44, 84, 422, 616)
        pygame.draw.rect(s, (8, 8, 9), r.inflate(10, 10), border_radius=6)
        s.blit(fx.paper(r.w, r.h), r)
        lh = 15
        lines = self.lines + [self.line]
        y = r.bottom - 12 - lh
        clip = s.get_clip()
        s.set_clip(r)
        for ln in reversed(lines):
            if y < r.y - lh:
                break
            text(s, ln, (r.x + 14, y), 12, (46, 44, 52), bold=True)
            y -= lh
        s.set_clip(clip)
        pygame.draw.rect(s, (20, 20, 22), (r.x - 6, r.bottom - 6, r.w + 12, 16), border_radius=3)
        pygame.draw.line(s, (90, 90, 96), (r.x, r.bottom + 1), (r.right, r.bottom + 1), 2)
        frac = self.paper / 900.0
        text(s, "PAPER", (52, 716), 9, C["dim"], bold=True)
        ui.bar(s, (96, 716, 160, 10), frac, "green" if frac > 0.17 else "red", 16)
        text(s, "%d lines" % self.paper, (264, 714), 9, C["dim"], bold=True)
        if self.paper <= 0:
            text(s, "PAPER OUT", (r.centerx, r.centery), 20, C["red"], bold=True, align="m")
        ui.led(s, (60, 760), "green", self.p_on.on and self.on and self.paper > 0, "PRINT", 5, 9)

    def _draw_lcd(self, s):
        w, t = self.world, self.world.t
        l = ui.lcd(s, (516, 80, 568, 250), (14, 20, 12), (60, 80, 40))
        k = self.dim.val
        fg = tuple(int(c * k) for c in (190, 230, 120))
        dim = tuple(int(c * k) for c in (90, 120, 70))
        if not self.on:
            text(s, "OFF" if not self.pwr.on else "NO POWER", l.center, 20, dim, bold=True, align="m")
            return
        text(s, "NAVTEX  %s kHz   %s   MEM %d" % (self.freq.value.split()[0], self.page, len(self.mem)),
             (l.x + 8, l.y + 6), 12, fg, bold=True)
        pygame.draw.line(s, (50, 70, 40), (l.x + 6, l.y + 24), (l.right - 6, l.y + 24), 1)
        y = l.y + 30
        if self.page == "LIST":
            if not self.mem:
                text(s, "NO MESSAGES", (l.x + 8, y + 4), 13, dim)
            top = max(0, self.cursor - 9)
            for i, m in enumerate(self.mem[top:top + 11]):
                j = top + i
                cur = j == self.cursor
                col = (255, 120, 90) if m["b2"] == "D" else (fg if not m["read"] else dim)
                text(s, "%s%s %s %-14s %s %s" % (">" if cur else " ", "*" if not m["read"] else " ", m["id"], m["name"][:14],
                                                m["utc"], "ERR" if m["cer"] >= 0.04 else ""),
                     (l.x + 8, y + i * 19), 12, col, bold=cur)
        elif self.page == "TEXT" and self.mem:
            m = self.mem[min(self.cursor, len(self.mem) - 1)]
            rows = ui.wrap(m["text"].replace("\n", " "), 12, l.w - 20)
            self.scroll = min(self.scroll, max(0, len(rows) - 9))
            text(s, "%s  %s  %s  CER %d%%" % (m["id"], m["name"], B2_MEANING.get(m["b2"], "")[:22], m["cer"] * 100),
                 (l.x + 8, y), 11, (255, 200, 120), bold=True)
            for i, ln in enumerate(rows[self.scroll:self.scroll + 10]):
                text(s, ln, (l.x + 8, y + 20 + i * 18), 12, fg)
        elif self.page == "SETUP":
            b1 = "".join(ch for ch in LET if self.b1[ch].on)
            b2 = "".join(ch for ch in LET if self.b2[ch].on)
            rows = ["FREQUENCY  %s kHz" % self.freq.value, "B1 STATIONS  %s" % (b1 or "NONE"),
                    "B2 SUBJECTS %s" % b2, "SAR ALARM  %s   PRINTER %s" % ("ON" if self.d_alarm.on else "OFF",
                                                                         "ON" if self.p_on.on else "OFF"),
                    "IDS RECEIVED %d (not printed again)" % len(self.seen),
                    "CER LIMITS: <4% stored, >33% rejected"]
            for i, r in enumerate(rows):
                text(s, r, (l.x + 8, y + i * 24), 12, fg)
        else:
            for i, (tm, msg, col) in enumerate(self.log[-11:]):
                text(s, "%s %s" % (tm, msg[:52]), (l.x + 8, y + i * 19), 11, tuple(int(c * k) for c in col))

    def _draw_rx(self, s):
        w, t = self.world, self.world.t
        text(s, "SIGNAL", (1126, 82), 10, C["dim"], bold=True)
        ui.bar(s, (1190, 82, 220, 12), self.sig, "green", 22)
        ui.meter(s, (1420, 76, 156, 92), min(1.0, self.cer_now / 0.5), "CER %d %%" % (self.cer_now * 100),
                 [(0, "0"), (0.08, "4"), (0.66, "33"), (1, "50")], red_from=0.66)
        c = self.cur_tx
        l = ui.lcd(s, (1126, 104, 286, 64))
        if c:
            text(s, "ON AIR: %s %s" % (c["tx"]["b1"], c["tx"]["name"][:16]), (l.x + 8, l.y + 6), 11, C["lcdfg"], bold=True)
            text(s, "%g kHz  ZCZC %s" % (c["tx"]["f"], c["id"]), (l.x + 8, l.y + 24), 11, C["lcdfg"])
            text(s, "%s" % ("RECEIVING" if self.rx else ("NOT TUNED" if FREQS[self.freq.idx] != c["tx"]["f"] else "IGNORED / NOT HEARD")),
                 (l.x + 8, l.y + 42), 11, C["amber"], bold=True)
        else:
            text(s, "NO TRANSMISSION", (l.x + 8, l.y + 22), 12, C["dim"])
        l = ui.lcd(s, (1126, 180, 448, 262))
        text(s, "RECEPTION LOG", (l.x + 8, l.y + 6), 11, C["dim"], bold=True)
        for i, (tm, msg, col) in enumerate(self.log[-12:]):
            text(s, "%s %s" % (tm, msg[:52]), (l.x + 8, l.y + 26 + i * 19), 11, col)

    def _draw_map(self, s):
        w = self.world
        r = ui.crt(s, (1126, 488, 448, 230), (3, 9, 12), (14, 40, 56), gain=90)
        span = 900.0                                  # NM across the map
        k = r.w / span

        def xy(la, lo):
            dy = (la - w.lat) * 60.0
            dx = (lo - w.lon) * 60.0 * math.cos(math.radians(w.lat))
            return r.centerx + dx * k, r.centery - dy * k

        clip = s.get_clip()
        s.set_clip(r)
        for g in range(-12, 13, 2):
            gx, _ = xy(w.lat, math.floor(w.lon) + g)
            _, gy = xy(math.floor(w.lat) + g, w.lon)
            pygame.draw.line(s, (16, 34, 44), (gx, r.y), (gx, r.bottom), 1)
            pygame.draw.line(s, (16, 34, 44), (r.x, gy), (r.right, gy), 1)
        for tx in TX:
            x, y = xy(tx["lat"], tx["lon"])
            sel = self.b1[tx["b1"]].on
            tuned = FREQS[self.freq.idx] == tx["f"]
            col = C["green"] if (sel and tuned) else ((120, 140, 80) if sel else (90, 90, 90))
            rad = (250 if tx["f"] < 1000 else 500) * k
            pygame.draw.circle(s, col, (x, y), max(2, int(rad)), 1)
            pygame.draw.rect(s, col, (x - 3, y - 3, 6, 6))
            text(s, "%s %s" % (tx["b1"], tx["name"][:10]), (x + 6, y - 6), 9, col, bold=True)
            if self.cur_tx and self.cur_tx["tx"] is tx and int(w.t * 3) % 2:
                pygame.draw.circle(s, C["amber"], (x, y), 9, 2)
        pygame.draw.polygon(s, C["white"], [(r.centerx, r.centery - 6), (r.centerx + 5, r.centery + 5), (r.centerx - 5, r.centery + 5)])
        s.set_clip(clip)
        text(s, "%d NM across" % span, (r.right - 6, r.bottom - 14), 9, C["dim"], align="r")
        l = ui.lcd(s, (1126, 726, 448, 122))
        text(s, "B1 STATION            kHz    NM   SNR", (l.x + 8, l.y + 4), 10, C["dim"], bold=True)
        for i, tx in enumerate(TX):
            p = self.path(tx)
            col = C["lcdfg"] if p["snr"] > 10 else (C["amber"] if p["snr"] > 0 else C["dim"])
            text(s, "%s  %-18s %6g %5d %4d" % (tx["b1"], tx["name"][:18], tx["f"], p["d"] / 1.852, p["snr"]),
                 (l.x + 8 + (i // 4) * 0, l.y + 18 + i * 12.5), 10, col)
