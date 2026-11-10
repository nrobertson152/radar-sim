"""Application shell: window, station tabs, status bar, audio mixing."""
import os
import sys
import numpy as np
import pygame
from . import ui
from .ui import C, text, W, H
from .world import World, fmt_lat, fmt_lon
from .audio import Audio


class App:
    def __init__(self):
        pygame.mixer.pre_init(22050, -16, 1, 512)
        pygame.init()
        pygame.display.set_caption("RADAR-SIM  |  Radar, Radio and GMDSS Console Trainer")
        try:
            self.screen = pygame.display.set_mode((W, H), pygame.SCALED | pygame.RESIZABLE)
        except pygame.error:
            self.screen = pygame.display.set_mode((W, H))
        self.world = World()
        self.audio = Audio()
        from .radar import Radar
        from .vhf import VUHF
        from .hf import HF
        from .satcom import Satcom
        from .sarsat import Sarsat
        from .bench import Bench
        from .training import Training
        from .reference import Reference
        self.stations = []
        for cls in (Radar, VUHF, HF, Satcom, Sarsat, Bench, Training, Reference):
            st = cls(self)
            self.stations.append(st)
            setattr(self, cls.__name__.lower(), st)
        self.cur = 0
        self.clock = pygame.time.Clock()
        self.running = True
        self.fps = 60.0
        self.tabs = []
        tw = 132
        for i, st in enumerate(self.stations):
            self.tabs.append(pygame.Rect(232 + i * (tw + 4), 6, tw, 34))

    def goto(self, name):
        for i, st in enumerate(self.stations):
            if st.name == name or st.__class__.__name__.lower() == name.lower():
                self.cur = i

    @property
    def station(self):
        return self.stations[self.cur]

    # ---------------------------------------------------------------- loop
    def handle(self, ev):
        if ev.type == pygame.QUIT:
            self.running = False
            return
        if ev.type == pygame.MOUSEMOTION:
            ui.MOUSE[0], ui.MOUSE[1] = ev.pos
        if ev.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            ui.MOUSE[0], ui.MOUSE[1] = ev.pos
        if ev.type == pygame.KEYDOWN:
            if pygame.K_F1 <= ev.key <= pygame.K_F8:
                self.cur = ev.key - pygame.K_F1
                return
            if ev.key == pygame.K_F10:
                self.audio.mute = not self.audio.mute
                return
            if ev.key == pygame.K_F11:
                pygame.display.toggle_fullscreen()
                return
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and ev.pos[1] < ui.TOP:
            for i, r in enumerate(self.tabs):
                if r.collidepoint(ev.pos):
                    self.cur = i
            if pygame.Rect(W - 60, 8, 52, 30).collidepoint(ev.pos):
                self.audio.mute = not self.audio.mute
            return
        self.station.handle(ev)

    def step(self, dt):
        self.world.update(dt)
        for st in self.stations:
            st.update(dt)

    def gen_audio(self, syn, n):
        out = np.zeros(n)
        a = self.station.audio(syn, n)
        if a is not None:
            out += a
        for st in self.stations:
            f = getattr(st, "bg_audio", None)
            if f:
                b = f(syn, n)
                if b is not None:
                    out += b
        return out

    def draw(self):
        s = self.screen
        s.fill(C["bg"])
        self.station.draw(s)
        # top bar
        pygame.draw.rect(s, (22, 25, 30), (0, 0, W, ui.TOP - 2))
        pygame.draw.line(s, C["edge"], (0, ui.TOP - 2), (W, ui.TOP - 2), 1)
        text(s, "RADAR-SIM", (14, 6), 18, C["amber"], bold=True)
        text(s, "RADAR / RADIO / GMDSS TRAINER", (14, 27), 9, C["dim"], bold=True)
        blink = int(self.world.t * 3) % 2 == 0
        for i, (st, r) in enumerate(zip(self.stations, self.tabs)):
            act = i == self.cur
            col = (60, 66, 76) if act else (34, 38, 44)
            if st.alert and blink:
                col = (150, 30, 24)
            pygame.draw.rect(s, col, r, border_radius=5)
            pygame.draw.rect(s, C["amber"] if act else C["edge"], r, 1, border_radius=5)
            text(s, "F%d" % (i + 1), (r.x + 5, r.y + 3), 8, C["dim"], bold=True)
            text(s, st.name, r.center, 12, C["white"] if act else C["text"], bold=True, align="m")
        w = self.world
        x = self.tabs[-1].right + 14
        text(s, "UTC " + w.utc_str(), (x, 6), 13, C["green"], bold=True)
        text(s, fmt_lat(w.lat) + " " + fmt_lon(w.lon), (x, 24), 10, C["green"])
        r = pygame.Rect(W - 60, 8, 52, 30)
        pygame.draw.rect(s, (34, 38, 44), r, border_radius=5)
        mute = self.audio.mute or not self.audio.ok
        text(s, "MUTE" if mute else "SOUND", (r.centerx, r.y + 4), 9, C["red"] if mute else C["green"], bold=True, align="c")
        text(s, "F10", (r.centerx, r.y + 16), 9, C["dim"], bold=True, align="c")
        # status bar
        pygame.draw.rect(s, (22, 25, 30), (0, ui.BOT, W, H - ui.BOT))
        pygame.draw.line(s, C["edge"], (0, ui.BOT), (W, ui.BOT), 1)
        tip = self.station.tip_at(ui.MOUSE) if ui.TOP <= ui.MOUSE[1] < ui.BOT else ""
        ui.text_block(s, tip or self.station.hint, (12, ui.BOT + 3, 1040, 32), 11,
                      C["text"] if tip else C["dim"], lh=14, mono=False)
        tr = getattr(self, "training", None)
        if tr is not None:
            tr.draw_status(s, pygame.Rect(1070, ui.BOT + 1, W - 1070, H - ui.BOT - 1))
        pygame.display.flip()

    def run(self):
        while self.running:
            dt = min(0.1, self.clock.tick(60) / 1000.0)
            for ev in pygame.event.get():
                self.handle(ev)
            self.step(dt)
            self.audio.pump(self.gen_audio)
            self.draw()
        pygame.quit()


def selftest(outdir):
    """Headless smoke test: run every station and save a screenshot of each."""
    os.makedirs(outdir, exist_ok=True)
    app = App()
    for i in range(len(app.stations)):
        app.cur = i
        for _ in range(120):
            app.step(1 / 30.0)
            app.gen_audio(app.audio.syn, 2208)
            app.audio.syn.t += 2208
        app.draw()
        pygame.image.save(app.screen, os.path.join(outdir, "%d_%s.png" % (i + 1, app.station.name.lower().replace("/", "-").replace(" ", "_"))))
    print("selftest ok:", ", ".join(s.name for s in app.stations))


def main():
    if "--selftest" in sys.argv:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        i = sys.argv.index("--selftest")
        selftest(sys.argv[i + 1] if len(sys.argv) > i + 1 else "shots")
        return
    App().run()


if __name__ == "__main__":
    main()
