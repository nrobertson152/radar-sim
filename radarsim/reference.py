"""Quick-reference cards."""
import pygame
from . import ui
from .ui import C, text, Button, Station

PAGES = [
    ("GMDSS FREQUENCIES", [
        ("DISTRESS AND SAFETY", """BAND     DSC          R/T VOICE    TELEX (NBDP)
VHF      CH70 156.525 CH16 156.800 -
MF       2187.5 kHz   2182 kHz     2174.5 kHz
HF 4     4207.5       4125         4177.5
HF 6     6312         6215         6268
HF 8     8414.5       8291         8376.5
HF 12    12577        12290        12520
HF 16    16804.5      16420        16695"""),
        ("OTHER KEY FREQUENCIES", """CH13 156.650  bridge-to-bridge navigation safety
CH06 156.300  ship-ship, SAR co-ordination with aircraft
CH70          DSC only - voice is never permitted
NAVTEX        518 kHz (international, English)
              490 kHz (national language), 4209.5 kHz
EPIRB         406.0-406.1 MHz alert, 121.5 MHz homing
SART          9.2-9.5 GHz (X-band radar)
AIS           161.975 MHz (87B) and 162.025 MHz (88B)
AIR SAR       121.5 MHz emergency, 123.1 MHz on-scene
INMARSAT      ship TX 1626.5-1646.5, RX 1530-1545 MHz"""),
        ("SEA AREAS", """A1  within VHF DSC coast station range (20-30 NM)
A2  within MF DSC coast station range (about 150 NM)
A3  within geostationary satellite coverage (about 76 N - 76 S)
A4  everywhere else: the polar regions (HF or polar-orbit satcom)"""),
        ("ITU DUPLEX R/T CHANNELS (3 kHz spacing)", """BAND  FIRST CH  SHIP TX kHz  COAST TX kHz
4     401       4065         4357
6     601       6200         6501
8     801       8195         8719
12    1201      12230        13077
16    1601      16360        17242
22    2201      22000        22696
Channel n: add 3 kHz x (n - first). e.g. 816 = 8240 / 8764."""),
    ]),
    ("VOICE PROCEDURE", [
        ("PRIORITIES", """MAYDAY    distress: grave and imminent danger to ship or person,
          immediate assistance required
PAN PAN   urgency: very urgent message about the safety of a ship
          or person (medical, steering failure, man overboard found)
SECURITE  safety: important navigational or meteorological warning
Each signal is spoken THREE times."""),
        ("DISTRESS CALL AND MESSAGE", """MAYDAY, MAYDAY, MAYDAY
THIS IS <name> <name> <name>, CALL SIGN <cs>, MMSI <number>
MAYDAY <name>, CALL SIGN, MMSI
MY POSITION IS <lat/long, or bearing and distance from a mark>
<nature of distress>
<assistance required>
<persons on board, other information: abandoning, flares, EPIRB>
OVER"""),
        ("ACKNOWLEDGING / RELAY / CONTROL", """Acknowledge:  MAYDAY, <ship> x3, THIS IS <own> x3, RECEIVED MAYDAY
Relay:        MAYDAY RELAY x3, THIS IS <own> x3, FOLLOWING RECEIVED
              FROM <ship> ...  (when the casualty cannot transmit)
Impose silence:  SEELONCE MAYDAY   (station controlling traffic)
End of distress: SEELONCE FEENEE
False alert: switch off, then ALL STATIONS x3, THIS IS ... CANCEL MY
             DISTRESS ALERT OF <time> UTC. Tell the coastguard."""),
        ("PHONETIC ALPHABET", """A Alfa     H Hotel    O Oscar    V Victor
B Bravo    I India    P Papa     W Whiskey
C Charlie  J Juliett  Q Quebec   X X-ray
D Delta    K Kilo     R Romeo    Y Yankee
E Echo     L Lima     S Sierra   Z Zulu
F Foxtrot  M Mike     T Tango
G Golf     N November U Uniform
0 ZERO 1 WUN 2 TOO 3 TREE 4 FOW-ER 5 FIFE 6 SIX 7 SEV-EN 8 AIT 9 NIN-ER"""),
        ("PROWORDS", """OVER  reply expected        OUT   finished, no reply expected
ROGER received              SAY AGAIN  repeat
CORRECTION  error made      I SPELL    phonetic spelling follows
STATION CALLING  unknown caller        WAIT  stand by"""),
    ]),
    ("RADAR", [
        ("BANDS", """X-band  9410 MHz  3 cm   sharp beam (1.2 deg), good small-target
                         detection, sees SART and racon, heavy
                         sea and rain clutter
S-band  3050 MHz  10 cm  wider beam (1.9 deg), penetrates rain
                         and sea clutter, long range in weather"""),
        ("PULSE, PRF AND RANGE", """Range from echo delay:   R = c x t / 2      (12.36 us per NM)
Range discrimination:    c x pulse / 2      (150 m per us)
Minimum range:           about pulse length + TR recovery
Unambiguous range:       c / (2 x PRF)      (81 NM at 1000 Hz)
Bearing discrimination:  horizontal beamwidth
Radar horizon (NM):      2.21 x (sqrt(h_antenna) + sqrt(h_target)) m
Radar equation:          echo power falls as 1 / R^4
Short pulse = wide receiver bandwidth = more noise, less range."""),
        ("SETTING UP - ALWAYS IN THIS ORDER", """1 STAND-BY, wait for warm-up, then TX
2 BRILLIANCE to suit ambient light
3 Medium range scale (6-12 NM)
4 GAIN up until a light speckle shows
5 TUNE for maximum (or AFC), re-check after 10 minutes
6 SEA (STC): the minimum that breaks up the clutter
7 RAIN (FTC): only when needed, then back to zero
Re-check GAIN after any change of range or pulse length."""),
        ("FALSE AND SPECIAL ECHOES", """Side lobes     arc of echoes at the same range as a big close target
Indirect       ghost on the bearing of a mast or funnel
Multiple       repeats at 2x, 3x range from a ship close abeam
Second trace   target beyond the unambiguous range shown close in
Blind/shadow   sectors astern of masts - weave to check them
Interference   spiral dotted lines from another radar - use IR
SART           12 dots in a line, 0.64 NM apart, nearest = SART
Racon          Morse letter flashing radially beyond the beacon"""),
        ("ARPA", """CPA   closest point of approach    TCPA  time to CPA
Relative vector shows collision risk; true vector shows aspect.
Steady bearing + closing range = risk of collision.
A tracked target needs about 1 min for a first estimate and
3 min for full accuracy. Target swap and lost targets happen in
clutter - check the raw picture."""),
    ]),
    ("RADIO THEORY", [
        ("EMISSION CLASSES", """J3E  single sideband, suppressed carrier voice (MF/HF marine)
H3E  SSB full carrier (old 2182 kHz compatibility)
A3E  double sideband AM voice (air band, broadcast)
G3E  phase/frequency modulated voice (marine VHF FM)
F1B  frequency-shift keying: DSC, NAVTEX, telex (170 Hz shift)
A1A  on/off keyed Morse (CW)
G2B  DSC on VHF (1200 baud, 1300/2100 Hz subcarrier)"""),
        ("WHY SSB", """An AM signal puts half its power in the carrier and duplicates
the speech in two sidebands. SSB removes the carrier and one
sideband: one sixth of the power does the same job in half the
bandwidth (2.7 kHz). The price: the receiver must re-insert the
carrier within about 50 Hz, hence the clarifier."""),
        ("HF PROPAGATION", """Ground wave   follows the sea surface; best at MF (2 MHz: 150+ NM)
Sky wave      refracted by the F2 layer; range 500-10000+ km
MUF           highest frequency refracted for the path; above it
              the wave escapes into space
D layer       daytime absorber, strongest on LOW frequencies
Skip zone     too far for ground wave, too near for sky wave
RULE: high bands (12-22 MHz) by day, low bands (4-8) at night;
the longer the path, the higher the frequency. Use the highest
band that is below the MUF."""),
        ("VHF / UHF", """Line of sight only. Radio horizon (NM) = 2.22 x (sqrt h1 + sqrt h2)
Free-space loss (dB) = 32.45 + 20 log f(MHz) + 20 log d(km)
25 W to 1 W is only -14 dB: height matters far more than power.
FM capture effect: the stronger of two stations wins completely.
Squelch: open it, then close until the noise just disappears."""),
        ("USEFUL NUMBERS", """dBm = 10 log (P / 1 mW)     25 W = +44 dBm    1 W = +30 dBm
S9 = -73 dBm = 50 uV in 50 ohm, 6 dB per S-unit
SWR 1.5 reflects 4 %, SWR 2 reflects 11 %, SWR 3 reflects 25 %
wavelength (m) = 300 / f (MHz)     quarter-wave whip = 75 / f
PEP = peak envelope power; two-tone test: PEP = 2 x mean power"""),
    ]),
    ("SATELLITE SYSTEMS", [
        ("INMARSAT", """Geostationary, 35 786 km above the equator, L-band service links.
Classic ocean regions: AOR-W 54 W, AOR-E 15.5 W, IOR 64 E, POR 178 E
Coverage to about 76 degrees latitude (5 deg elevation).
Inmarsat-C   omni antenna, 600 bit/s store-and-forward data,
             distress alerting, EGC SafetyNET / FleetNET
Fleet / FB   stabilised dish, voice and IP data
One-way delay about 0.25 s: speak, then wait.
Elevation and azimuth depend on your position; the dish must
see the sky - masts and funnels cause blockage sectors."""),
        ("TWO-DIGIT SAFETY CODES", """32  medical advice           38  medical assistance
39  maritime assistance      41  meteorological reports
42  navigational hazards     43  ship position reports"""),
        ("COSPAS-SARSAT", """406 MHz beacons: EPIRB (ship), ELT (aircraft), PLB (person)
Burst: 5 W for 0.5 s every 50 s, digital message with a 15-hex ID
LEOSAR  polar orbit ~850 km: Doppler location, global, with waits
GEOSAR  geostationary: instant detection, position only if the
        beacon encodes GNSS, no polar coverage
MEOSAR  repeaters on GPS / Galileo / GLONASS: near-real-time
        independent location
Chain: beacon > satellite > LUT > MCC > RCC > SAR unit
121.5 MHz is for final homing only - satellites no longer listen."""),
        ("EPIRB AND SART CARE", """EPIRB: register it, test monthly with the TEST position only,
check battery expiry and hydrostatic release date, keep it in
its float-free bracket with the switch ARMED.
SART: test against your own X-band radar (rings on the PPI),
carry it to the survival craft, mount it at least 1 m high.
A false alert must be cancelled by telling an MRCC at once."""),
    ]),
]


class Reference(Station):
    name = "REFERENCE"
    hint = "Reference cards. Select a page on the left."

    def __init__(self, app):
        super().__init__(app)
        self.page = 0
        self.btns = [self.add(Button((36, 84 + i * 50, 208, 42), p[0], "", size=11)) for i, p in enumerate(PAGES)]

    def update(self, dt):
        for i, b in enumerate(self.btns):
            if b.pop():
                self.page = i
                ui.sfx("page")
            b.on = i == self.page

    def draw(self, s):
        ui.panel(s, (20, 54, 240, 806), "PAGES")
        ui.panel(s, (270, 54, 1320, 806), PAGES[self.page][0])
        ui.crt(s, (286, 80, 1288, 766), (4, 9, 7))
        x, y, col = 300, 92, 0
        for head, body in PAGES[self.page][1]:
            lines = body.split("\n")
            need = 26 + len(lines) * 17 + 16
            if y + need > 850 and col == 0:
                col, x, y = 1, 950, 92
            text(s, head, (x, y), 13, C["amber"], bold=True)
            pygame.draw.line(s, (40, 90, 60), (x, y + 19), (x + 600, y + 19), 1)
            y += 26
            for ln in lines:
                text(s, ln, (x, y), 12, C["lcdfg"])
                y += 17
            y += 16
        ui.text_block(s, "KEYS\nF1-F8  stations\nF10  mute\nF11  full screen\nSPACE  push-to-talk\nWheel / drag  knobs\nSHIFT  fine adjust\n \nThis is a training aid with simplified physics. Always follow "
                         "your flag state's rules and the equipment manuals at sea.", (36, 400, 210, 400), 11, C["dim"], mono=False, lh=17)
        super().draw(s)
