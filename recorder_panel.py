#!/usr/bin/env python3
"""piRecorder: LCD 20x4, REC/STOP, dwa enkodery, trzy LED.

REC=17 STOP=27; E1 CLK/DT/SW=5/6/13; E2=16/12/26 (BCM).
LED R/G/Y=22/23/24; PCF8574 0x27 na I2C1. 
E1 wybiera WAV, klik odtwarza/zatrzymuje. E2 reguluje glosnosc
odsluchu, klik wybiera WSZYSTKIE lub pare kanalow (przy zatrzymaniu).
Odtwarzanie przez mpv; przed odsluchem zatrzymaj Spotify/moOde.
Nie steruje Spotify, nie zmienia gainu wejsc UMC1820.
"""
from contextlib import ExitStack
from datetime import datetime
from functools import partial
from pathlib import Path
from queue import Queue, Empty
from time import monotonic
import fcntl
import json
import shutil
import signal
import socket
import subprocess
import struct
import tempfile
import wave

import config

from gpiozero import Button, LED, RotaryEncoder
from RPLCD.i2c import CharLCD

FOLDER = config.RECORDINGS_DIR
CAPTURE = config.CAPTURE_DEVICE
OUTPUT = config.PLAYBACK_DEVICE


def valid_recording(path):
    """Sprawdz zakonczony naglowek i dane PCM, takze WAV extensible.

    Nie wczytuje wielogigabajtowego nagrania do pamieci.
    To kontrola struktury pliku, nie jakosci sygnalu audio.
    """
    try:
        size = path.stat().st_size
        with path.open('rb') as stream:
            header = stream.read(12)
            if len(header) != 12 or header[:4] != b'RIFF' or header[8:] != b'WAVE':
                return False
            end = struct.unpack('<I', header[4:8])[0] + 8
            if end != size:
                return False
            block = None
            data_size = 0
            while stream.tell() + 8 <= end:
                kind, length = struct.unpack('<4sI', stream.read(8))
                start = stream.tell()
                if start + length > end:
                    return False
                if kind == b'fmt ':
                    fmt = stream.read(min(length, 40))
                    if len(fmt) < 16:
                        return False
                    tag, channels, rate, byte_rate, block, bits = struct.unpack('<HHIIHH', fmt[:16])
                    if (channels, rate, bits, block, byte_rate) != (10, 48000, 32, 40, 1920000):
                        return False
                    if tag == 65534:
                        pcm_guid = bytes.fromhex('0100000000001000800000aa00389b71')
                        if len(fmt) < 40 or fmt[24:40] != pcm_guid:
                            return False
                    elif tag != 1:
                        return False
                elif kind == b'data':
                    data_size += length
                stream.seek(start + length + (length % 2))
            return block is not None and data_size > 0 and data_size % block == 0
    except (OSError, ValueError, struct.error):
        return False


def playback_filter(channels, pair):
    if pair == -1:
        left = list(range(0, channels, 2))
        right = list(range(1, channels, 2)) or left
        gain = 1 / max(len(left), len(right))
        lmix = '+'.join(f'{gain:g}*c{i}' for i in left)
        rmix = '+'.join(f'{gain:g}*c{i}' for i in right)
        return f'lavfi=[pan=stereo|c0={lmix}|c1={rmix}]'
    left = pair * 2
    right = min(left + 1, channels - 1)
    return f'lavfi=[pan=stereo|c0=c{left}|c1=c{right}]'


class Recorder:
    def __init__(self, stack):
        self.events = Queue()
        self.rec = self.player = None
        self.started = 0
        self.elapsed = 0
        self.files = []
        self.selected = None
        self.active = None
        self.volume = 50
        self.pair = -1  # -1: wszystkie kanaly, 0..4: pary 1-2..9-10.
        self.status = 'GOTOWY'
        self.notice = ''
        self.notice_until = 0
        self.previous = [None] * 4
        self.last_scan = 0
        self.temp = stack.enter_context(tempfile.TemporaryDirectory(prefix='pirecorder-'))
        self.ipc_path = str(Path(self.temp) / 'mpv.sock')
        self.volume_pending = False
        self.leds = {name: stack.enter_context(LED(pin, initial_value=False))
                     for name, pin in config.LED_PINS.items()}
        self.lcd = CharLCD(**config.LCD_OPTIONS)
        stack.callback(self.lcd.close, clear=False)
        self.lcd.clear()
        self.buttons = []
        for action, pin in [('rec', config.REC_PIN), ('stop', config.STOP_PIN),
                            ('play', config.E1_PINS[2]), ('pair', config.E2_PINS[2])]:
            b = stack.enter_context(Button(pin, pull_up=True, bounce_time=0.1))
            b.when_pressed = partial(self.enqueue, action, 0)
            self.buttons.append(b)
        self.encoders = []
        for action, clk, dt, direction in [('select', *config.E1_PINS[:2], config.E1_DIRECTION),
                                           ('volume', *config.E2_PINS[:2], config.E2_DIRECTION)]:
            enc = stack.enter_context(RotaryEncoder(clk, dt, max_steps=0))
            enc.when_rotated_clockwise = partial(self.enqueue, action, direction)
            enc.when_rotated_counter_clockwise = partial(self.enqueue, action, -direction)
            self.encoders.append(enc)
        self.scan()

    def enqueue(self, action, value):
        self.events.put((action, value))

    def mode_label(self):
        return 'WSZYSTKIE' if self.pair == -1 else f'{self.pair*2+1}-{self.pair*2+2}'

    def message(self, text):
        print(text, flush=True)
        self.notice, self.notice_until = text, monotonic() + 2.5

    def scan(self):
        self.files = sorted(FOLDER.glob('*.wav'))
        if self.selected not in self.files:
            self.selected = self.files[-1] if self.files else None
        self.last_scan = monotonic()

    def ipc(self, command):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.1)
                sock.connect(self.ipc_path)
                sock.sendall((json.dumps({'command': command}) + '\n').encode())
            return True
        except OSError:
            return False

    def stop_playback(self):
        if self.player is None:
            return
        p, self.player = self.player, None
        if p.poll() is None:
            p.terminate()
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        self.volume_pending = False
        self.status = 'GOTOWY'

    def start_recording(self):
        if self.rec is not None:
            self.message('Juz nagrywam')
            return
        self.stop_playback()
        if shutil.disk_usage(FOLDER).free < 100 * 1024 * 1024:
            self.message('Za malo miejsca!')
            return
        self.active = FOLDER / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.wav')
        try:
            self.rec = subprocess.Popen(['arecord', '-D', CAPTURE, '-t', 'wav',
                '-f', 'S32_LE', '-r', '48000', '-c', '10', str(self.active)],
                stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            self.status = 'BLAD REC'
            self.message(str(exc))
            return
        self.started = monotonic()
        self.elapsed = 0
        self.status = 'REC'
        self.selected = self.active
        print('REC:', self.active, flush=True)

    def stop_recording(self):
        if self.rec is None:
            return
        p, self.rec = self.rec, None
        self.elapsed = int(monotonic() - self.started)
        self.status = 'ZAPIS'
        try:
            self.render()
        except Exception as exc:
            print('LCD podczas zapisu:', exc, flush=True)
        running = p.poll() is None
        forced = False
        stop_sent = False
        if running:
            try:
                p.send_signal(signal.SIGINT)
                stop_sent = True
            except ProcessLookupError:
                pass
        try:
            code = p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            p.kill()
            code = p.wait()
            forced = True
        # arecord moze zwrocic 1 po naszym SIGINT. Akceptujemy to tylko
        # po zadanym STOP i kontroli zamknietego, niepustego pliku WAV.
        valid = valid_recording(self.active)
        saved = stop_sent and code in (0, 1) and not forced and valid
        self.status = 'ZAPISANO' if saved else 'BLAD ZAPISU'
        self.scan()
        print(f'{self.status}: {self.active} (kod={code}, kill={forced}, WAV_OK={valid})', flush=True)

    def play(self):
        if self.rec is not None:
            self.message('Najpierw STOP REC')
            return
        if self.player is not None:
            self.stop_playback()
            return
        self.scan()
        if self.selected is None:
            self.message('Brak nagran WAV')
            return
        # Python 3.11 nie czyta niektorych WAV extensible: wtedy pozwol mpv
        # zdekodowac plik i przyjmij liczbe kanalow naszego rejestratora.
        channels = 10
        try:
            with wave.open(str(self.selected), 'rb') as wav:
                channels = wav.getnchannels()
        except (wave.Error, EOFError):
            pass
        except OSError as exc:
            self.message(str(exc))
            return
        if self.pair >= 0 and self.pair * 2 >= channels:
            self.pair = -1
        Path(self.ipc_path).unlink(missing_ok=True)
        try:
            self.player = subprocess.Popen(['mpv', '--no-config', '--no-video',
                '--ao=alsa', '--audio-device=' + OUTPUT, '--volume-max=100',
                f'--volume={self.volume}', '--input-ipc-server=' + self.ipc_path,
                '--af=' + playback_filter(channels, self.pair),
                '--', str(self.selected)], stdin=subprocess.DEVNULL,
                start_new_session=True)
        except OSError as exc:
            self.status = 'BLAD PLAY'
            self.message(str(exc))
            return
        self.active = self.selected
        self.started = monotonic()
        self.status = 'PLAY'
        print(f'PLAY: {self.active}, odsluch {self.mode_label()}', flush=True)

    def handle(self, action, value):
        if action == 'rec':
            self.start_recording()
        elif action == 'stop':
            if self.rec is not None:
                self.stop_recording()
            else:
                self.stop_playback()
                self.scan()
        elif action == 'play':
            self.play()
        elif action == 'select':
            if self.rec is not None:
                return
            self.scan()
            if self.files:
                index = self.files.index(self.selected)
                self.selected = self.files[(index + value) % len(self.files)]
                self.message('Wybor: ' + self.selected.name)
        elif action == 'volume':
            self.volume = max(0, min(100, self.volume + value * 2))
            self.volume_pending = self.player is not None
            self.message(f'Odsluch: {self.volume}%')
        elif action == 'pair':
            if self.rec is not None or self.player is not None:
                self.message('Para: najpierw STOP')
            else:
                self.pair = ((self.pair + 2) % 6) - 1
                self.message('Odsluch: ' + self.mode_label())

    def render(self):
        recording = self.rec is not None
        playing = self.player is not None
        seconds = int(monotonic() - self.started) if recording or playing else self.elapsed
        hours, rem = divmod(seconds, 3600)
        minutes, sec = divmod(rem, 60)
        # Podczas PLAY pokazuj faktycznie odtwarzany plik, nie kolejny wybor.
        path = self.active if recording or playing else self.selected
        name = path.name if path else 'Brak nagran'
        name = name.encode('ascii', 'replace').decode()
        # Przewijanie dlugich nazw, jedna linia o szerokosci 20 znakow.
        if len(name) > 20:
            scroll = name + '   '
            offset = int(monotonic() / 0.4) % len(scroll)
            name = (scroll + scroll)[offset:offset+20]
        index = self.files.index(self.selected) + 1 if self.selected in self.files else 0
        info = f'Plik {index}/{len(self.files)}'
        if monotonic() < self.notice_until:
            info = self.notice
        lines = [f'{self.status} {hours:02}:{minutes:02}:{sec:02}',
                 name, f'VOL {self.volume}% {self.mode_label()}', info]
        for row, text in enumerate(lines):
            text = text.encode('ascii', 'replace').decode()[:20].ljust(20)
            if text != self.previous[row]:
                self.lcd.cursor_pos = (row, 0)
                self.lcd.write_string(text)
                self.previous[row] = text
        error = self.status.startswith('BLAD')
        self.leds['R'].value = recording or (error and int(monotonic()*4) % 2 == 0)
        self.leds['Y'].value = playing
        self.leds['G'].value = not recording and not playing and not error

    def run(self):
        print('Gotowy. REC/STOP, E1: plik/play, E2: glosnosc/para. Ctrl+C: koniec.', flush=True)
        try:
            while True:
                if self.rec is not None and self.rec.poll() is not None:
                    print('arecord zakonczyl sie niespodziewanie:', self.rec.returncode, flush=True)
                    self.elapsed = int(monotonic() - self.started)
                    self.rec = None
                    self.status = 'BLAD REC'
                    self.scan()
                if self.player is not None and self.player.poll() is not None:
                    code = self.player.returncode
                    self.player = None
                    self.status = 'GOTOWY' if code == 0 else 'BLAD PLAY'
                    print('mpv zakonczony, kod:', code, flush=True)
                    if code:
                        self.message('Sprawdz terminal/USB')
                if self.volume_pending and self.player is not None:
                    if self.ipc(['set_property', 'volume', self.volume]):
                        self.volume_pending = False
                if monotonic() - self.last_scan > 5 and self.rec is None:
                    self.scan()
                self.render()
                try:
                    action, value = self.events.get(timeout=0.1)
                    self.handle(action, value)
                except Empty:
                    pass
        except KeyboardInterrupt:
            print('Zamykanie i zapis nagrania...', flush=True)
        finally:
            # Takze blad LCD nie moze zostawic dzialajacego arecord.
            try:
                self.stop_recording()
            finally:
                self.stop_playback()
                self.status = 'WYLACZONY'
                self.render()


def main():
    FOLDER.mkdir(parents=True, exist_ok=True)
    for tool in ('arecord', 'mpv'):
        if shutil.which(tool) is None:
            raise SystemExit('Brak ' + tool + '. Zainstaluj: sudo apt install alsa-utils mpv')
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    with ExitStack() as stack:
        config.LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        lock = stack.enter_context(config.LOCK_FILE.open('w'))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Inna instancja recorder_panel.py juz dziala.')
        Recorder(stack).run()


if __name__ == '__main__':
    main()
