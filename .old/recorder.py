import config

from gpiozero import Button
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty
import subprocess
import signal

folder = config.RECORDINGS_DIR
folder.mkdir(parents=True, exist_ok=True)
events = Queue()
process = None
filename = None

rec = Button(config.REC_PIN, pull_up=True, bounce_time=0.1)
stop = Button(config.STOP_PIN, pull_up=True, bounce_time=0.1)

rec.when_pressed = lambda: events.put("rec")
stop.when_pressed = lambda: events.put("stop")

def finish():
    global process
    if process is None:
        return
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
    code = process.wait()
    print(f"Koniec nagrania: {filename} (kod: {code})", flush=True)
    process = None

print("Gotowy. REC: nagrywanie, STOP: zapis. Wyjście: Ctrl+C.", flush=True)

try:
    while True:
        if process is not None and process.poll() is not None:
            print(f"arecord zakończył pracę, kod: {process.returncode}", flush=True)
            process = None

        try:
            action = events.get(timeout=0.2)
        except Empty:
            continue

        if action == "rec":
            if process is not None:
                print("Już nagrywam.", flush=True)
                continue

            filename = folder / (
                datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".wav"
            )
            process = subprocess.Popen([
                "arecord",
                "-D", config.CAPTURE_DEVICE,
                "-t", "wav",
                "-f", "S32_LE",
                "-r", "48000",
                "-c", "10",
                str(filename)
            ], start_new_session=True)
            print(f"Uruchamiam nagrywanie: {filename}", flush=True)

        elif action == "stop":
            if process is None:
                print("Nagrywanie jest zatrzymane.", flush=True)
            else:
                finish()

except KeyboardInterrupt:
    print("\nZamykanie...", flush=True)
finally:
    rec.close()
    stop.close()
    finish()
