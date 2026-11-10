# RADAR-SIM

A 2D radar, radio and GMDSS console trainer written in Python (pygame + numpy).
Eight equipment positions share one simulated world, so what you do on one
panel shows up on the others: switch on the EPIRB and its 121.5 MHz homer
howls on the guard receiver; break the magnetron on the circuits bench and the
radar picture loses its echoes.

![Radar](docs/radar.png)

## Run it

```
pip install -r requirements.txt
python run.py
```

Python 3.9+. `pygame-ce` is recommended; classic `pygame` 2.x also works.
The window is 1600x900 and scales when resized (F11 = full screen).
All sound is synthesised live - there are no asset files.

| Key | Action |
| --- | --- |
| F1 - F8 | switch station |
| mouse drag / wheel | turn knobs (SHIFT = fine) |
| left / right click on a selector | step it up / down |
| SPACE | push-to-talk on the VHF and MF/HF stations |
| F10 / F11 | mute / full screen |

Hover any control: the status bar explains what it does on the real equipment.

## Stations

**F1 RADAR** - X/S-band marine radar. Every sweep is computed from the radar
equation: targets (R^-4, RCS, radar horizon), land with shadowing, sea clutter
(sea state, wind direction), rain clutter and rain attenuation, receiver noise,
side lobes, a blind sector astern, main bang and minimum range. The receiver
chain is modelled in order: tuning loss against a drifting magnetron (manual
TUNE or AFC), STC, gain/threshold, FTC, echo stretch, echo averaging,
interference rejection. Warm-up, three pulse lengths, nine range scales,
head-up / north-up, EBL, VRM, trails, an A-scan of the live video, ARPA
acquisition with CPA/TCPA alarm, SART (12 dots, arcs, rings) and racon.

**F2 VHF / UHF** - marine VHF radiotelephone with a Class-A DSC controller
(guarded distress button, nature of distress, individual / safety / urgency
calls, alert repetition and cancellation), dual watch, high/low power, a
procedure prompter that writes the MAYDAY for your ship, plus a 108-470 MHz
AM/FM transceiver with guard receiver for air band, UHF and on-board
channels. A live line-of-sight link budget shows why antenna height beats power.

**F3 MF / HF SSB** - synthesised SSB transceiver with keypad and ITU duplex
channel entry, clarifier, antenna tuner with SWR and PA fold-back, S / power /
SWR / current meter, a 24 kHz spectrum scope and waterfall, a six-frequency DSC
watch receiver with distress button, and an ionospheric propagation predictor
(MUF, D-layer absorption, ground wave, skip) that follows the sun. SSB really
is demodulated against the dial: tune 150 Hz off and the voice (and its
caption) turns to Donald Duck; pick the wrong sideband and it inverts.
Stations to find: coast stations, NAVTEX on 518 kHz, weather fax, time
signals, Morse, broadcasters.

**F4 INMARSAT** - point a stabilised dish at the right ocean-region satellite
(azimuth, elevation, mast blockage, auto-track), log in, send Inmarsat-C
store-and-forward messages and distress alerts, receive EGC SafetyNET, and
place voice calls with the two-digit safety codes. Click the map to move the
ship anywhere on Earth.

**F5 COSPAS-SARSAT** - 406 MHz EPIRB (off / armed / test / on, hydrostatic
release, GNSS on or off), radar SART, LEOSAR satellites on polar orbits with
footprints, GEOSAR and MEOSAR. Each received burst is plotted as a Doppler
measurement; the alert chain runs beacon - satellite - LUT - MCC - RCC - SAR
with a time-warp control.

**F6 CIRCUITS** - block diagrams of the radar transceiver and the SSB
transceiver with an oscilloscope (and spectrum analyser) probe on every stage,
a healthy reference trace, and a fault-finding game. Injected faults break the
real radar and HF stations, so you work from the operator's symptom to the
faulty stage.

**F7 TRAINING** - 16 guided drills that set up a scenario and check each step
live on the real controls, from "switch on, tune and set gain" to an
abandon-ship capstone that uses every station.

**F8 REFERENCE** - GMDSS frequencies, voice procedure, radar and radio theory,
satellite systems.

![MF/HF](docs/hf.png)
![Circuits](docs/circuits.png)
![COSPAS-SARSAT](docs/sarsat.png)

## Tests

```
python tests/test_drills.py     # plays every drill and every fault headless
python tests/test_input.py      # mouse / keyboard event paths
python run.py --selftest shots  # screenshot of every station
```

## Scope and accuracy

Frequencies, channel plans, procedures and equipment behaviour follow the
GMDSS as generally taught, but the physics is deliberately simplified
(for example a single-layer ionosphere and circular satellite orbits), the
coastline, ships and coast stations are fictional, and timings such as the
magnetron warm-up are shortened. It is a study aid, not a certified simulator
and not a substitute for the equipment manuals or an approved GOC/ROC course.

## Layout

```
radarsim/
  main.py       window, tabs, audio mixing        world.py     ships, coast, traffic, propagation, orbits
  ui.py         knobs, switches, meters, LCDs     audio.py     real-time sound synthesis
  radar.py      F1    vhf.py       F2             hf.py        F3
  satcom.py     F4    sarsat.py    F5             bench.py     F6
  training.py   F7    reference.py F8             worldmap.py, radiocore.py   shared helpers
```

Licensed under GPL-3.0 (see LICENSE).
