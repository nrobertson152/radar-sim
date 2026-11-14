"""The shared simulated world: own ship, radar contacts, coastline, weather,
radio stations and traffic, HF ionospheric propagation, satellites.

Local radar/VHF geometry uses a flat x/y grid in nautical miles (x east,
y north). HF and satellite geometry uses real latitude/longitude.
"""
import math
import time
import numpy as np
import pygame

RE = 6371.0
CPS = 15.0                       # characters per second of "speech" in captions


# ------------------------------------------------------------------ geodesy
def gc_dist(lat1, lon1, lat2, lon2):
    """Great-circle distance in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * RE * math.asin(min(1, math.sqrt(a)))


def gc_bearing(lat1, lon1, lat2, lon2):
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360


def gc_dest(lat, lon, brg, ang_deg):
    """Point at angular distance ang_deg along bearing brg."""
    p, b, d = math.radians(lat), math.radians(brg), math.radians(ang_deg)
    p2 = math.asin(max(-1, min(1, math.sin(p) * math.cos(d) + math.cos(p) * math.sin(d) * math.cos(b))))
    l2 = math.radians(lon) + math.atan2(math.sin(b) * math.sin(d) * math.cos(p),
                                        math.cos(d) - math.sin(p) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def gc_mid(lat1, lon1, lat2, lon2):
    d = gc_dist(lat1, lon1, lat2, lon2) / RE
    return gc_dest(lat1, lon1, gc_bearing(lat1, lon1, lat2, lon2), math.degrees(d) / 2)


def cos_zenith(lat, lon, utc_h, doy):
    """Cosine of the solar zenith angle (1 = sun overhead, <0 = night)."""
    dec = math.radians(-23.44 * math.cos(2 * math.pi * (doy + 10) / 365.0))
    ha = math.radians((utc_h - 12.0) * 15.0 + lon)
    p = math.radians(lat)
    return math.sin(p) * math.sin(dec) + math.cos(p) * math.cos(dec) * math.cos(ha)


def geo_look(lat, lon, sat_lon):
    """Azimuth, elevation (deg) and slant range (km) to a geostationary satellite."""
    az = gc_bearing(lat, lon, 0.0, sat_lon)
    cg = math.cos(math.radians(lat)) * math.cos(math.radians(sat_lon - lon))
    rs = 42164.0
    slant = math.sqrt(RE * RE + rs * rs - 2 * RE * rs * cg)
    el = math.degrees(math.atan2(cg - RE / rs, math.sqrt(max(1e-9, 1 - cg * cg))))
    return az, el, slant


def fmt_lat(lat):
    d = abs(lat)
    return "%02d°%05.2f'%s" % (int(d), (d % 1) * 60, "N" if lat >= 0 else "S")


def fmt_lon(lon):
    d = abs(lon)
    return "%03d°%05.2f'%s" % (int(d), (d % 1) * 60, "E" if lon >= 0 else "W")


def wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


# ---------------------------------------------------------------- VHF plan
def vhf_channel(ch):
    """(ship TX MHz, ship RX MHz, duplex?) for an international marine channel."""
    f = 156.050 + 0.05 * (ch - 1) if ch <= 28 else 156.025 + 0.05 * (ch - 60)
    duplex = (1 <= ch <= 7) or (18 <= ch <= 28) or (60 <= ch <= 66) or (78 <= ch <= 86)
    return round(f, 3), round(f + (4.6 if duplex else 0.0), 3), duplex


VHF_CHANNELS = list(range(1, 29)) + list(range(60, 89))
VHF_USE = {
    16: "DISTRESS, SAFETY AND CALLING", 70: "DSC ONLY - NO VOICE", 13: "BRIDGE-TO-BRIDGE SAFETY",
    6: "SHIP-SHIP / SAR CO-ORDINATION", 8: "SHIP-SHIP", 72: "SHIP-SHIP", 77: "SHIP-SHIP",
    67: "COASTGUARD SAFETY BROADCASTS", 12: "PORT OPERATIONS", 14: "PORT OPERATIONS",
    10: "SHIP-SHIP / POLLUTION", 9: "SHIP-SHIP / PILOTS", 15: "ON-BOARD (1 W)", 17: "ON-BOARD (1 W)",
    75: "GUARD BAND (1 W)", 76: "GUARD BAND (1 W)", 87: "AIS 1 (161.975)", 88: "AIS 2 (162.025)",
}

HF_DSC = [2187.5, 4207.5, 6312.0, 8414.5, 12577.0, 16804.5]
HF_RT = [2182.0, 4125.0, 6215.0, 8291.0, 12290.0, 16420.0]
# ITU duplex R/T channel plan: band digit -> (ship TX base, coast TX base) kHz, 3 kHz steps
ITU_BANDS = {4: (4065.0, 4357.0), 6: (6200.0, 6501.0), 8: (8195.0, 8719.0),
             12: (12230.0, 13077.0), 16: (16360.0, 17242.0), 22: (22000.0, 22696.0)}


def itu_channel(n):
    """ITU channel number (e.g. 816) -> (ship TX kHz, coast TX kHz) or None."""
    band, k = divmod(n, 100)
    if band in ITU_BANDS and 1 <= k <= 60:
        s, c = ITU_BANDS[band]
        return s + 3 * (k - 1), c + 3 * (k - 1)
    return None


RADAR_BLOCKS = ["psu", "trig", "mod", "mag", "dup", "ant", "trl", "mix", "lo", "ifa", "det", "vid",
                "afc", "stc", "dsp"]
SSB_BLOCKS = ["mic", "afa", "bal", "cosc", "sbf", "synth", "txm", "drv", "pa", "atu", "rxm", "ifl",
              "pdet", "afo", "spk"]


class Src:
    """A radio source on the local grid."""

    def __init__(self, name, x, y, h, pw=25.0, mmsi=0):
        self.name, self.x, self.y, self.h, self.pw, self.mmsi = name, x, y, h, pw, mmsi


class Contact(Src):
    def __init__(self, name, kind, x, y, cog=0, sog=0, rcs=100, h=10, length=20,
                 mmsi=0, cs="", racon="", box=None, active=True, ais=None):
        super().__init__(name, x, y, h, 25.0, mmsi)
        self.kind, self.cog, self.sog, self.rcs, self.length = kind, cog, sog, rcs, length
        self.cs, self.racon, self.active = cs, racon, active
        self.box = box or (-26, 26, -22, 4.2)
        self.ais = (mmsi > 0 and kind in ("ship", "boat", "aircraft")) if ais is None else ais
        self.ais_class = "A" if kind == "ship" else ("SAR" if kind == "aircraft" else "B")
        self.home = self.on_scene = False


COMPASS16 = ["NORTH", "NORTH NORTH EAST", "NORTH EAST", "EAST NORTH EAST", "EAST", "EAST SOUTH EAST",
             "SOUTH EAST", "SOUTH SOUTH EAST", "SOUTH", "SOUTH SOUTH WEST", "SOUTH WEST", "WEST SOUTH WEST",
             "WEST", "WEST NORTH WEST", "NORTH WEST", "NORTH NORTH WEST"]


def compass_word(deg):
    return COMPASS16[int(((deg % 360) + 11.25) // 22.5) % 16]


def side_word(rel):
    """Relative bearing -> 'STARBOARD BOW' etc."""
    rel %= 360
    if rel < 10 or rel > 350:
        return "BOW, RIGHT AHEAD"
    for lim, w in ((67.5, "STARBOARD BOW"), (112.5, "STARBOARD BEAM"), (170, "STARBOARD QUARTER"),
                   (190, "STERN"), (247.5, "PORT QUARTER"), (292.5, "PORT BEAM"), (350, "PORT BOW")):
        if rel < lim:
            return w
    return "PORT BOW"


class Msg:
    speech = None                      # set by the app: radarsim.speech.Speech

    def __init__(self, f, mode, src, text, t0, kind="voice", dsc=None):
        self.f, self.mode, self.src, self.text, self.t0, self.kind, self.dsc = f, mode, src, text, t0, kind, dsc
        self.dur = max(1.5, len(text) / CPS) if kind == "voice" else 1.2
        self.prog = {}
        self._clip = None
        self.clip()

    def clip(self):
        """The spoken audio for this message once it has been synthesised."""
        if self._clip is None and self.kind == "voice" and Msg.speech is not None and Msg.speech.ok:
            c = Msg.speech.get(self.text, self.src.name)
            if c is not None:
                self._clip = c
                self.dur = max(self.dur if self.prog else 0.0, len(c) / 22050.0 + 0.25)
        return self._clip

    def chars(self, t):
        """How many characters of the text have been spoken by time t."""
        return max(0, min(len(self.text), int((t - self.t0) / max(0.1, self.dur - 0.25) * len(self.text))))

    def active(self, t):
        return self.t0 <= t <= self.t0 + self.dur


MAINLAND = [(-40, 9), (-30, 8), (-24, 10), (-18, 7.5), (-14, 8.5), (-10, 6.5), (-7, 7.2), (-5, 9.5),
            (-3, 10.5), (-1, 9), (1, 6.2), (3, 5.8), (4, 7), (6, 8), (9, 7), (12, 9), (16, 8),
            (19, 5.5), (22, 6), (24, 9), (30, 11), (40, 10), (40, 40), (-40, 40)]
ISLANDS = [
    [(6.6, -4.6), (7.2, -3.8), (8.3, -3.6), (9.4, -4.2), (9.8, -5.2), (9.1, -6.1), (7.9, -6.4), (6.9, -5.7)],
    [(-4.15, 2.1), (-3.95, 2.35), (-3.8, 2.1)],
    [(-12.4, -3.1), (-12.0, -2.6), (-11.5, -2.9), (-11.7, -3.5), (-12.2, -3.5)],
    [(1.15, 6.25), (1.55, 4.9), (1.67, 4.93), (1.3, 6.25)],
]

INMARSAT = [("AOR-W", -54.0), ("AOR-E", -15.5), ("IOR", 64.0), ("POR", 178.0)]
LEOSAR = [  # name, inclination, RAAN, phase, period (s)
    ("LEOSAR-1", 98.7, 20.0, 90.0, 6120.0), ("LEOSAR-2", 98.7, 80.0, 250.0, 6096.0),
    ("LEOSAR-3", 98.9, 140.0, 350.0, 6150.0), ("LEOSAR-4", 83.0, 200.0, 170.0, 6300.0),
    ("LEOSAR-5", 98.7, 300.0, 300.0, 6084.0),
]

NAVTEX_TEXT = (
    "ZCZC EA42 PENHALE RADIO NAVIGATIONAL WARNING 142 FAIRWAY BUOY 49-54N 005-27W RACON "
    "MIKE REPORTED UNRELIABLE NNNN   ZCZC EB07 GALE WARNING SOUTHWEST GALE FORCE 8 EXPECTED "
    "SOON IN SEA AREAS LUNDY FASTNET AND PLYMOUTH NNNN   ZCZC ED11 SAR INFORMATION RED FLARES "
    "REPORTED 12 MILES SOUTH OF PENHALE HEAD VESSELS IN AREA KEEP SHARP LOOKOUT REPORT TO "
    "PENHALE COASTGUARD NNNN   ZCZC EE23 WEATHER FORECAST WIND SOUTHWEST 5 TO 7 INCREASING 8 "
    "SEA ROUGH RAIN VISIBILITY MODERATE OCCASIONALLY POOR NNNN   ")

HF_STATIONS = []


def _hf(name, lat, lon, f, mode, pkw, kind, text="", duty=None):
    HF_STATIONS.append(dict(name=name, lat=lat, lon=lon, f=f, mode=mode, pkw=pkw, kind=kind,
                            text=text, duty=duty, key="%s%g" % (name, f), _ph=(len(name) * 13 + int(f)) % 50))


_T_NS = ("ALL SHIPS ALL SHIPS THIS IS NORTHSEA RADIO NORTHSEA RADIO. TRAFFIC LIST FOLLOWS. "
         "I HAVE TRAFFIC FOR LAXR7 NORDIC STAR, D5KL9 ATLANTIC PEARL, 9HA2261. VESSELS WITH "
         "TRAFFIC CALL NORTHSEA RADIO ON YOUR PAIRED SHIP FREQUENCY. LISTENING. ")
_T_AE = ("THIS IS AEGEAN RADIO AEGEAN RADIO. WEATHER BULLETIN FOR SHIPPING. CENTRAL "
         "MEDITERRANEAN NORTHWEST 6 LOCALLY 7. IONIAN SEA NORTH 5. VISIBILITY GOOD. ")
_T_AT = ("ATLANTIC WEATHER BROADCAST. HIGH SEAS FORECAST NORTH ATLANTIC NORTH OF 31 NORTH. "
         "STORM WARNING. LOW 968 MILLIBARS NEAR 52 NORTH 28 WEST MOVING EAST 25 KNOTS. "
         "WINDS 45 TO 60 KNOTS SEAS TO 11 METRES WITHIN 300 MILES SOUTH SEMICIRCLE. ")
for _f in (4417.0, 8764.0, 13137.0, 17302.0):
    _hf("NORTHSEA RADIO", 55.5, 8.4, _f, "USB", 5.0, "voice", _T_NS)
for _f in (8779.0, 13164.0):
    _hf("AEGEAN RADIO", 37.6, 23.9, _f, "USB", 5.0, "voice", _T_AE)
for _f in (6501.0, 13089.0, 17314.0):
    _hf("ATLANTIC WX", 36.7, -76.0, _f, "USB", 10.0, "voice", _T_AT)
for _f in (2500.0, 5000.0, 10000.0, 15000.0, 20000.0):
    _hf("WWV TIME SIGNAL", 40.68, -105.04, _f, "AM", 10.0, "wwv", "TIME SIGNAL - SECONDS TICKS ")
for _f in (4610.0, 8040.0, 11086.5):
    _hf("NORTHWOOD FAX", 51.6, -0.4, _f, "USB", 10.0, "fax", "[WEATHER FAX - SURFACE ANALYSIS CHART] ")
_hf("PENHALE NAVTEX", 50.2, -5.1, 518.0, "FSK", 1.0, "navtex", NAVTEX_TEXT)
_hf("PENHALE COASTGUARD MF", 50.15, -5.05, 2182.0, "USB", 0.4, "voice",
    "ALL STATIONS THIS IS PENHALE COASTGUARD. GALE WARNING AND NAVIGATIONAL WARNINGS FOLLOW "
    "ON 1880 KILOHERTZ. OUT. ", duty=(150, 22))
_hf("COAST DSC MF", 50.15, -5.05, 2187.5, "FSK", 0.4, "dsc", "", duty=(95, 7))
_hf("COAST DSC HF", 55.8, 12.4, 8414.5, "FSK", 5.0, "dsc", "", duty=(70, 7))
_hf("COAST DSC HF", 55.8, 12.4, 12577.0, "FSK", 5.0, "dsc", "", duty=(110, 7))
_hf("FV TREVOSE", 49.2, -6.8, 4146.0, "USB", 0.15, "voice",
    "MORVORAN MORVORAN THIS IS TREVOSE ON 4146. FISHING IS POOR HERE, WE ARE HAULING AND "
    "STEAMING NORTH. HOW DO YOU READ. OVER. ", duty=(80, 30))
_hf("G3XYZ (AMATEUR CW)", 52.5, -1.5, 7030.0, "CW", 0.1, "cw", "CQ CQ CQ DE G3XYZ G3XYZ K ")
_hf("VK2ABC (AMATEUR CW)", -33.9, 151.2, 14060.0, "CW", 0.4, "cw", "CQ DX CQ DX DE VK2ABC VK2ABC K ")
_hf("COAST CW BEACON", 43.4, -8.4, 8421.0, "CW", 1.0, "cw", "VVV VVV DE EAR EAR QSX 8 MHZ K ")
for _f, _la, _lo in ((5975.0, 34.6, 33.0), (6195.0, -7.9, -14.4), (9410.0, 34.6, 33.0),
                     (11955.0, 1.4, 103.7), (15400.0, -7.9, -14.4), (17830.0, -7.9, -14.4)):
    _hf("SHORTWAVE BROADCAST", _la, _lo, _f, "AM", 250.0, "bc", "[INTERNATIONAL BROADCAST - MUSIC] ")

VHF_SCRIPT = [
    [(16, "CG", "ALL STATIONS, ALL STATIONS, ALL STATIONS. THIS IS PENHALE COASTGUARD, PENHALE "
      "COASTGUARD. FOR THE MARITIME SAFETY INFORMATION BROADCAST LISTEN CHANNEL 67. OUT."),
     (67, "CG", "ALL STATIONS, THIS IS PENHALE COASTGUARD. INSHORE WATERS FORECAST. WIND SOUTHWEST "
      "5 TO 7, OCCASIONALLY GALE 8 LATER. SEA STATE MODERATE OR ROUGH. RAIN AT TIMES. VISIBILITY "
      "GOOD, OCCASIONALLY POOR. NAVIGATIONAL WARNING: FAIRWAY BUOY RACON MIKE UNRELIABLE. OUT.")],
    [(16, "NORDIC STAR", "FISHING VESSEL MORVORAN, MORVORAN, THIS IS NORDIC STAR, NORDIC STAR, "
      "CHANNEL 16. OVER."),
     (16, "FV MORVORAN", "NORDIC STAR, THIS IS MORVORAN. CHANNEL ZERO SIX. OVER."),
     (6, "NORDIC STAR", "MORVORAN, NORDIC STAR. I AM OVERTAKING YOU ON YOUR PORT SIDE. PLEASE "
      "MAINTAIN YOUR COURSE AND SPEED. OVER."),
     (6, "FV MORVORAN", "NORDIC STAR, MORVORAN. ROGER, MAINTAINING COURSE AND SPEED. OUT.")],
    [(12, "PENHALE FERRY", "PENHALE HARBOUR, PENHALE FERRY. DEPARTING THE LINKSPAN, OUTBOUND FOR "
      "THE ISLAND. OVER."),
     (12, "HARBOUR", "PENHALE FERRY, PENHALE HARBOUR. ROGER. ONE INBOUND TANKER AT THE FAIRWAY "
      "BUOY. OUT.")],
    [(16, "SY KITTIWAKE", "PENHALE COASTGUARD, THIS IS YACHT KITTIWAKE, KITTIWAKE. RADIO CHECK "
      "CHANNEL 16. OVER."),
     (16, "CG", "KITTIWAKE, PENHALE COASTGUARD. YOU ARE LOUD AND CLEAR. OUT.")],
    [(13, "ATLANTIC PEARL", "VESSEL ON MY PORT BOW, THIS IS TANKER ATLANTIC PEARL ON CHANNEL 13. "
      "I INTEND TO PASS RED TO RED. OVER.")],
    [(16, "CG", "SECURITE, SECURITE, SECURITE. ALL STATIONS, THIS IS PENHALE COASTGUARD. "
      "NAVIGATIONAL WARNING. UNLIT PARTLY SUBMERGED CONTAINER REPORTED IN POSITION 49 DEGREES 46 "
      "MINUTES NORTH, 005 DEGREES 36 MINUTES WEST. WIDE BERTH REQUESTED. OUT.")],
    [(282.8, "OPS", "RESCUE 193, SEAHAWK OPS. RADIO CHECK ON 282 DECIMAL 8. OVER."),
     (282.8, "RESCUE 193", "SEAHAWK OPS, RESCUE 193. READING YOU FIVE. AIRBORNE ON TRAINING "
      "SORTIE, 1500 FEET. OUT.")],
    [(457.525, "DECK", "BRIDGE, DECK. FORWARD MOORING STATION SECURED, ANCHORS CLEARED AWAY. OVER.")],
    [(123.1, "RESCUE 193", "PENHALE COASTGUARD, RESCUE 193 ON 123 DECIMAL 1. COMMENCING SEARCH "
      "PATTERN, TWO HOURS ENDURANCE. OVER.")],
    [("DSC", "CG", dict(cat="INDIVIDUAL", ch=67, text=(
        "MV TRAINER, THIS IS PENHALE COASTGUARD ON CHANNEL 67. WE HAVE A REPORT OF A SMALL BOAT "
        "WITH ENGINE FAILURE ABOUT 4 MILES SOUTH OF YOU. PLEASE KEEP A SHARP LOOKOUT AND REPORT "
        "ANY SIGHTING ON THIS CHANNEL. OVER.")))],
    [(16, "CG", "SECURITE, SECURITE, SECURITE. ALL STATIONS, THIS IS PENHALE COASTGUARD. "
      "FOR A GALE WARNING AND NAVIGATIONAL WARNINGS LISTEN CHANNEL 67. OUT."),
     (67, "CG", "ALL STATIONS, THIS IS PENHALE COASTGUARD. GALE WARNING. SOUTHWEST GALE FORCE 8 "
      "EXPECTED SOON IN SEA AREAS LUNDY, FASTNET AND PLYMOUTH. OUT.")],
]


class World:
    LAND_RES, LAND_HALF = 0.05, 40.0

    def __init__(self):
        now = time.gmtime()
        self.t = 0.0                               # sim seconds since start
        self.utc_h = now.tm_hour + now.tm_min / 60 + now.tm_sec / 3600
        self.doy = now.tm_yday
        self.ssn = 90.0                            # smoothed sunspot number
        self.lat0, self.lon0 = 49.8333, -5.5       # geographic anchor of the local grid
        self.x, self.y, self.hdg, self.spd = 0.0, 0.0, 75.0, 10.0
        self.h_ant = 18.0
        self.name, self.cs, self.mmsi = "MV TRAINER", "GTRN", 232456789
        self.sea, self.wind = 2, 235.0
        self.rain = []                             # [x, y, radius nm, mm/h, vx, vy]
        self.interference = False
        self.epirb_on = False
        self.rng = np.random.default_rng(3)
        self._make_land()
        C = Contact
        self.contacts = [
            C("NORDIC STAR", "ship", 7.5, 2.4, 255, 14, 30000, 28, 190, 257123000, "LAXR7"),
            C("ATLANTIC PEARL", "ship", -11, -7, 70, 11, 60000, 35, 260, 636015432, "D5KL9"),
            C("PENHALE FERRY", "ship", 2.6, 4.6, 150, 19, 8000, 20, 110, 232004321, "MPFY",
              box=(-1, 8, -3, 4.9)),
            C("FV MORVORAN", "boat", 3.2, -2.6, 300, 4, 40, 5, 18, 235087650, "MVRN"),
            C("SY KITTIWAKE", "boat", -1.8, 1.4, 110, 5, 4, 3, 11, 235911222, "MKTW", ais=False),
            C("FAIRWAY BUOY", "racon", 2.2, 3.6, rcs=15, h=5, length=3, racon="--"),
            C("S CARDINAL BUOY", "buoy", -4.0, 1.6, rcs=8, h=4, length=2),
            C("ISLAND BUOY", "buoy", 6.0, -5.3, rcs=8, h=4, length=2),
            C("SART", "sart", -5.5, -4.5, rcs=0.5, h=1, length=1, active=False),
            C("RESCUE 193", "aircraft", 9, 14, 200, 110, 20, 450, 17, 111232511, active=False,
              box=(-30, 30, -25, 30)),
        ]
        self.by_name = {c.name: c for c in self.contacts}
        self.srcs = dict(self.by_name)
        self.srcs["CG"] = Src("PENHALE COASTGUARD", 2.0, 7.2, 140, 25, 2320777)
        self.srcs["HARBOUR"] = Src("PENHALE HARBOUR", 1.0, 6.7, 25, 25, 2320778)
        self.srcs["OPS"] = Src("SEAHAWK OPS", 6.0, 12.0, 40, 30)
        self.srcs["ATIS"] = Src("PENHALE INFORMATION", 6.0, 12.0, 30, 20)
        self.srcs["DECK"] = Src("DECK PARTY", 0, 0, 10, 2)
        self.by_name["RESCUE 193"].pw = 20
        self.msgs = []
        self._seq, self._seq_i, self._next = 0, 0, 6.0
        self.radio_chatter = True
        self._hf_cache = {}
        # equipment health, altered by the fault-finding bench
        self.rh = {k: True for k in RADAR_BLOCKS}
        self.hh = {k: True for k in SSB_BLOCKS}
        self.pob = 12
        # AIS: last report heard from each transponder (keyed by MMSI)
        self.ais, self._ais_next = {}, {}
        self.ais_device = None                    # AIS-SART / MOB / EPIRB-AIS placed by the instructor
        # collision watch: ships that call you on CH16 when you are standing into danger
        self._cw_next, self._b2b, self.b2b_call = 0.0, {}, None
        self.events = {}                          # one-off world events (helicopter on scene ...)

    # -------------------------------------------------------------- terrain
    def _make_land(self):
        n = int(2 * self.LAND_HALF / self.LAND_RES)
        surf = pygame.Surface((n, n))
        surf.fill((0, 0, 0))

        def px(p):
            return ((p[0] + self.LAND_HALF) / self.LAND_RES, (self.LAND_HALF - p[1]) / self.LAND_RES)

        for poly in [MAINLAND] + ISLANDS:
            pygame.draw.polygon(surf, (255, 255, 255), [px(p) for p in poly])
        self.land = pygame.surfarray.array3d(surf)[:, :, 0] > 0
        self.land_n = n

    def land_at(self, xs, ys):
        ix = ((xs + self.LAND_HALF) / self.LAND_RES).astype(np.int32)
        iy = ((self.LAND_HALF - ys) / self.LAND_RES).astype(np.int32)
        ok = (ix >= 0) & (ix < self.land_n) & (iy >= 0) & (iy < self.land_n)
        out = np.zeros(xs.shape, dtype=bool)
        out[ok] = self.land[ix[ok], iy[ok]]
        return out

    # ------------------------------------------------------------- position
    @property
    def lat(self):
        return self.lat0 + self.y / 60.0

    @property
    def lon(self):
        return self.lon0 + self.x / (60.0 * math.cos(math.radians(self.lat0)))

    def set_position(self, lat, lon):
        """Relocate the ship on the globe (the local radar picture comes along)."""
        self.lat0 = max(-80, min(80, lat)) - self.y / 60.0
        self.lon0 = lon - self.x / (60.0 * math.cos(math.radians(self.lat0)))
        self._hf_cache.clear()

    def latlon_of(self, x, y):
        return self.lat0 + y / 60.0, self.lon0 + x / (60.0 * math.cos(math.radians(self.lat0)))

    def rb(self, c):
        """Range (nm) and true bearing (deg) from own ship to a source."""
        dx, dy = c.x - self.x, c.y - self.y
        return math.hypot(dx, dy), math.degrees(math.atan2(dx, dy)) % 360

    def utc_str(self):
        h = self.utc_h % 24
        return "%02d:%02d:%02d" % (int(h), int(h * 60) % 60, int(h * 3600) % 60)

    # --------------------------------------------------------------- update
    def update(self, dt):
        self.t += dt
        self.utc_h = (self.utc_h + dt / 3600.0) % 24
        a = math.radians(self.hdg)
        self.x += self.spd * math.sin(a) * dt / 3600
        self.y += self.spd * math.cos(a) * dt / 3600
        for c in self.contacts:
            if c.home and c.active:
                self._home(c)
            if not c.active or not c.sog:
                continue
            a = math.radians(c.cog)
            c.x += c.sog * math.sin(a) * dt / 3600
            c.y += c.sog * math.cos(a) * dt / 3600
            if c.home:
                continue
            x0, x1, y0, y1 = c.box
            if not (x0 <= c.x <= x1 and y0 <= c.y <= y1):
                c.cog = (c.cog + 180) % 360
                c.x, c.y = max(x0, min(x1, c.x)), max(y0, min(y1, c.y))
            if c.kind == "boat":
                c.cog = (c.cog + self.rng.normal(0, 3) * dt) % 360
        for r in self.rain:
            r[0] += r[4] * dt / 3600
            r[1] += r[5] * dt / 3600
        self.msgs = [m for m in self.msgs if m.t0 + m.dur + 2 > self.t]
        if self.radio_chatter and self.t >= self._next:
            seq = VHF_SCRIPT[self._seq % len(VHF_SCRIPT)]
            ch, who, txt = seq[self._seq_i]
            src = self.srcs[who]
            if ch == "DSC":
                m = self.say(70, src, "", kind="dsc", dsc=dict(txt, to=self.mmsi))
            else:
                m = self.say(ch, src, txt)
            self._next = m.t0 + m.dur + 2.5
            self._seq_i += 1
            if self._seq_i >= len(seq):
                self._seq_i, self._seq = 0, self._seq + 1
                self._next += float(self.rng.uniform(9, 20))
        self._ais_update()
        if self.t >= self._cw_next:
            self._cw_next = self.t + 1.0
            self._collision_watch()

    # ---------------------------------------------------------------- AIS
    def _ais_update(self):
        live = set()
        for c in self.contacts:
            if not (c.ais and c.active):
                continue
            live.add(c.mmsi)
            if self.t >= self._ais_next.get(c.mmsi, 0.0):
                self.ais[c.mmsi] = dict(name=c.name, mmsi=c.mmsi, cs=c.cs, x=c.x, y=c.y, cog=c.cog, sog=c.sog,
                                        t=self.t, cls=c.ais_class, c=c, length=c.length)
                iv = 30.0 if c.ais_class == "B" else (10.0 if c.ais_class == "SAR" else
                                                       (10.0 if c.sog < 14 else (6.0 if c.sog < 23 else 2.0)))
                self._ais_next[c.mmsi] = self.t + iv * float(self.rng.uniform(0.85, 1.15))
        d = self.ais_device
        if d and d.get("on"):
            live.add(d["mmsi"])
            if self.t >= self._ais_next.get(d["mmsi"], 0.0):
                self.ais[d["mmsi"]] = dict(name=d["label"], mmsi=d["mmsi"], cs="", x=d["x"], y=d["y"], cog=0.0,
                                           sog=0.0, t=self.t, cls=d["kind"], c=None, length=0)
                self._ais_next[d["mmsi"]] = self.t + 8.0           # SAR devices burst once a minute (shortened)
        for k in list(self.ais):
            if k not in live:
                del self.ais[k]

    def rain_here(self):
        """Rain rate (mm/h) falling on own ship."""
        best = 0.0
        for cx, cy, rad, rate, _, _ in self.rain:
            d2 = ((self.x - cx) ** 2 + (self.y - cy) ** 2) / (rad * rad)
            best = max(best, rate * max(0.0, 1 - d2))
        return best

    def cpa(self, c, own_hdg=None, own_spd=None):
        """(CPA nm, TCPA min, range nm, true bearing) of a contact."""
        hd = self.hdg if own_hdg is None else own_hdg
        sp = self.spd if own_spd is None else own_spd
        a, b = math.radians(c.cog), math.radians(hd)
        vx, vy = c.sog * math.sin(a) - sp * math.sin(b), c.sog * math.cos(a) - sp * math.cos(b)
        dx, dy = c.x - self.x, c.y - self.y
        v2 = vx * vx + vy * vy
        tc = -(dx * vx + dy * vy) / v2 if v2 > 1e-6 else 0.0
        rng = math.hypot(dx, dy)
        cp = math.hypot(dx + vx * tc, dy + vy * tc) if tc > 0 else rng
        return cp, tc * 60.0, rng, math.degrees(math.atan2(dx, dy)) % 360

    def _collision_watch(self):
        """A ship standing into close quarters with you calls you on CH16."""
        if not self.radio_chatter:
            return
        for c in self.contacts:
            if c.kind != "ship" or not c.active:
                continue
            cp, tc, rng, brg = self.cpa(c)
            if cp < 0.5 and 0 < tc < 15 and rng < 8 and self.t - self._b2b.get(c.name, -1e9) > 480:
                self._b2b[c.name] = self.t
                rel = ((brg + 180) - c.cog) % 360            # where we are, seen from her bridge
                txt = ("VESSEL ON MY %s, HEADING %s AT %d KNOTS, THIS IS %s, %s, ON CHANNEL 16. "
                       "WE ARE CLOSING, RANGE %d MILES. WHAT ARE YOUR INTENTIONS? OVER."
                       % (side_word(rel), compass_word(self.hdg), round(self.spd), c.name, c.name, max(1, round(rng))))
                self.say(16, c, txt, 2.0)
                self.b2b_call = dict(src=c, t=self.t, hdg0=self.hdg, answered=False)
                return

    def _home(self, c):
        """SAR unit tasked to own ship: fly to it, then hold station overhead."""
        dx, dy = self.x - c.x, self.y - c.y
        d = math.hypot(dx, dy)
        if d > 0.12:
            c.cog = math.degrees(math.atan2(dx, dy)) % 360
            c.sog = 110.0 if d > 1.5 else max(self.spd + 6.0, 110.0 * d / 1.5)
        else:
            c.cog, c.sog = self.hdg, self.spd
            if not c.on_scene:
                c.on_scene = True
                self.events["on_scene:" + c.name] = self.t
                self.say(16, c, "%s, THIS IS %s. ON SCENE, OVERHEAD YOUR STERN. KEEP YOUR COURSE INTO THE WIND, "
                         "SPEED 5 KNOTS. PREPARE TO RECEIVE THE WINCHMAN ON YOUR PORT QUARTER. OVER." % (self.name, c.name), 1.5)

    def task_sar(self, c, rng=16.0, brg=35.0):
        """Send a SAR unit to own ship from range/bearing."""
        a = math.radians(brg)
        c.x, c.y = self.x + rng * math.sin(a), self.y + rng * math.cos(a)
        c.active, c.home, c.on_scene = True, True, False
        c.sog = 110.0

    def say(self, ch, src, text, delay=0.0, kind="voice", dsc=None):
        """Queue a transmission. ch < 100 is a marine VHF channel, else MHz."""
        if ch < 100:
            f, mode = vhf_channel(int(ch))[0], "FM"
        else:
            f, mode = ch, ("FM" if 137 < ch < 175 or ch > 400 else "AM")
        m = Msg(f, mode, src, text, self.t + delay, kind, dsc)
        self.msgs.append(m)
        return m

    # ---------------------------------------------------- VHF/UHF link model
    def los_link(self, src, f_mhz, pw=None):
        """Line-of-sight link budget from a source to own ship antenna."""
        d = max(0.02, math.hypot(src.x - self.x, src.y - self.y))
        hor = 2.22 * (math.sqrt(self.h_ant) + math.sqrt(max(0.5, src.h)))
        fspl = 32.45 + 20 * math.log10(f_mhz) + 20 * math.log10(d * 1.852)
        over = max(0.0, d - hor)
        pt = 10 * math.log10((pw or src.pw) * 1000.0)
        pr = pt + 6 - fspl - 2.2 * over - 0.05 * over * over
        return dict(d=d, horizon=hor, fspl=fspl, pt=pt, pr=pr, over=over)

    # ------------------------------------------------------ HF propagation
    def hf_path(self, lat2, lon2, f_khz, p_kw, utc_h=None):
        """Simplified HF sky-wave + ground-wave prediction.

        foF2 follows the sun at the path midpoint; MUF = foF2 x obliquity
        factor; D-layer absorption follows cos(zenith)^0.75 / f^2. Good
        enough to teach 'low bands at night, high bands by day'.
        """
        utc_h = self.utc_h if utc_h is None else utc_h
        f = f_khz / 1000.0
        d = max(5.0, gc_dist(self.lat, self.lon, lat2, lon2))
        mlat, mlon = gc_mid(self.lat, self.lon, lat2, lon2)
        cz = cos_zenith(mlat, mlon, utc_h, self.doy)
        day = max(0.0, cz)
        fof2 = (2.9 + 7.4 * math.sqrt(day)) * (0.7 + self.ssn / 250.0)
        hops = max(1, math.ceil(d / 3500.0))
        dh = d / hops
        m = min(3.4, math.sqrt(1 + (dh / 600.0) ** 2))
        muf = fof2 * m
        path = math.sqrt(d * d + (600.0 * hops) ** 2)
        fspl = 32.45 + 20 * math.log10(f) + 20 * math.log10(path)
        sec = min(5.5, math.sqrt(1 + (dh / 200.0) ** 2))
        absorb = hops * 677.2 * sec * day ** 0.75 * (1 + 0.0037 * self.ssn) / ((f + 1.4) ** 1.98 + 10.2)
        over = 14.0 * max(0.0, f - muf)
        pt = 10 * math.log10(p_kw * 1e6)
        sky = pt + 2 - fspl - absorb - over - 6 - 3 * (hops - 1)
        dg = d
        gw = pt + 2 - (32.45 + 20 * math.log10(f) + 20 * math.log10(dg)) - 0.004 * dg * f ** 1.5 \
            - max(0.0, dg - 400) * 0.03
        pr = 10 * math.log10(10 ** (sky / 10) + 10 ** (gw / 10))
        noise = -90 - 26 * math.log10(max(0.3, f) / 2.0) + (7 if (day <= 0 and f < 7) else 0)
        return dict(d=d, brg=gc_bearing(self.lat, self.lon, lat2, lon2), fof2=fof2, muf=muf,
                    absorb=absorb, sky=sky, gw=gw, pr=pr, noise=noise, snr=pr - noise,
                    hops=hops, mode="GROUND" if gw > sky else "SKY %dF2" % hops, day=day)

    def hf_noise(self, f_khz):
        """External (atmospheric + man-made) noise in a 2.7 kHz bandwidth, dBm."""
        f = max(0.3, f_khz / 1000.0)
        night = cos_zenith(self.lat, self.lon, self.utc_h, self.doy) <= 0
        return -90 - 26 * math.log10(f / 2.0) + (7 if (night and f < 7) else 0)

    def hf_rx(self, st):
        """Cached received level for a fixed HF station."""
        k = st["key"]
        c = self._hf_cache.get(k)
        if c is None or self.t - c[0] > 2.0:
            c = (self.t, self.hf_path(st["lat"], st["lon"], st["f"], st["pkw"]))
            self._hf_cache[k] = c
        return c[1]

    def hf_on(self, st):
        if not st["duty"]:
            return True
        per, on = st["duty"]
        return ((self.t + st.get("_ph", 0)) % per) < max(on, st.get("_on", 0))

    # ------------------------------------------------------------ LEO sats
    def leo_pos(self, sat, t):
        """Sub-satellite latitude/longitude at sim time t (circular orbit)."""
        _, inc, raan, u0, per = sat
        u = math.radians(u0) + 2 * math.pi * t / per
        i, om = math.radians(inc), math.radians(raan)
        x = math.cos(om) * math.cos(u) - math.sin(om) * math.sin(u) * math.cos(i)
        y = math.sin(om) * math.cos(u) + math.cos(om) * math.sin(u) * math.cos(i)
        z = math.sin(u) * math.sin(i)
        lon = math.degrees(math.atan2(y, x)) - math.degrees(7.2921e-5 * t)
        return math.degrees(math.asin(z)), (lon + 540) % 360 - 180


def s_units(dbm):
    """S-meter reading: S9 = -73 dBm, 6 dB per S-unit."""
    return max(0.0, min(15.0, 9 + (dbm + 73) / 6.0))


def s_text(dbm):
    s = 9 + (dbm + 73) / 6.0
    if s >= 9:
        return "S9+%d" % (round((dbm + 73) / 10) * 10) if dbm > -68 else "S9"
    return "S%d" % max(0, int(s))
