from gpiozero import Button
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty
from time import monotonic
import subprocess
import signal

folder = Path.home() / 'recordings'
folder.mkdir(parents=True, exist_ok=True)
events = Queue()
process = None
filename = None
started = None
elapsed = 0
status = 'GOTOWY'
lcd = None
previous_lines = [None] * 4

try:
    from RPLCD.i2c import CharLCD
    lcd = CharLCD(i2c_expander='PCF8574', address=0x27,
                  port=1, cols=20, rows=4, backlight_enabled=True)
    lcd.clear()
except Exception as exc:
    print(f'LCD niedostepny: {exc}. Nagrywanie pozostaje dostepne.', flush=True)


def refresh():
    global lcd
    if lcd is None:
        return
    seconds = int(monotonic() - started) if started is not None else elapsed
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    # The full filename occupies two rows, without shortening its unique suffix.
    name = filename.name if filename else 'REC: start STOP: zapis'
    lines = [f'{status} {hours:02}:{minutes:02}:{seconds:02}',
             '10kan 48kHz S32_LE', name[:20], name[20:40]]
    try:
        for row, line in enumerate(lines):
            line = line[:20].ljust(20)
            if line != previous_lines[row]:
                lcd.cursor_pos = (row, 0)
                lcd.write_string(line)
                previous_lines[row] = line
    except Exception as exc:
        print(f'Blad LCD: {exc}. Wylaczam obsluge LCD do restartu.', flush=True)
        lcd = None


def finish():
    global process, started, elapsed, status
    if process is None:
        return
    was_running = process.poll() is None
    if started is not None:
        elapsed = int(monotonic() - started)
    started = None
    status = 'ZAPIS'
    refresh()
    forced = False
    if was_running:
        try:
            process.send_signal(signal.SIGINT)
        except ProcessLookupError:
            pass
    try:
        code = process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        code = process.wait()
        forced = True
    # Do not label failed or unexpectedly terminated captures as saved.
    status = 'ZAPISANO' if was_running and code == 0 and not forced else 'BLAD'
    print(f'Koniec nagrania: {filename} (kod: {code}, stan: {status})', flush=True)
    process = None
    refresh()


rec = Button(17, pull_up=True, bounce_time=0.1)
stop = Button(27, pull_up=True, bounce_time=0.1)
rec.when_pressed = lambda: events.put('rec')
stop.when_pressed = lambda: events.put('stop')
print('Gotowy. REC: nagrywanie, STOP: zapis. Wyjscie: Ctrl+C.', flush=True)

try:
    refresh()
    while True:
        if process is not None and process.poll() is not None:
            print(f'arecord zakonczyl prace, kod: {process.returncode}', flush=True)
            elapsed = int(monotonic() - started) if started is not None else elapsed
            started = None
            process = None
            status = 'BLAD'
        refresh()
        try:
            action = events.get(timeout=0.2)
        except Empty:
            continue
        if action == 'rec':
            if process is not None:
                print('Juz nagrywam.', flush=True)
                continue
            filename = folder / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.wav')
            try:
                process = subprocess.Popen([
                    'arecord', '-D', 'hw:CARD=UMC1820,DEV=0',
                    '-t', 'wav', '-f', 'S32_LE', '-r', '48000', '-c', '10',
                    str(filename)
                ], start_new_session=True)
            except OSError as exc:
                status = 'BLAD'
                print(f'Nie mozna uruchomic arecord: {exc}', flush=True)
                continue
            started = monotonic()
            elapsed = 0
            status = 'REC'
            print(f'Uruchamiam nagrywanie: {filename}', flush=True)
        elif action == 'stop':
            if process is None:
                print('Nagrywanie jest zatrzymane.', flush=True)
            else:
                finish()
except KeyboardInterrupt:
    print('Zamykanie...', flush=True)
finally:
    rec.close()
    stop.close()
    finish()
    status = 'WYLACZONY'
    refresh()
    if lcd is not None:
        try:
            lcd.close(clear=False)
        except Exception:
            pass
