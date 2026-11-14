#!/usr/bin/env python3
"""Test panelu piRecorder. Nie nagrywa i nie steruje Spotify.

Numery BCM: REC=17, STOP=27; E1=5/6/13; E2=16/12/26;
LED R/G/Y=22/23/24; LCD PCF8574 0x27, I2C 1, 20x4.
Uruchamiaj bez drugiego programu korzystajacego z tych GPIO/LCD.
"""
from contextlib import ExitStack
from queue import Queue, Empty
from time import monotonic, sleep
import signal

import config

from gpiozero import Button, LED, RotaryEncoder
from RPLCD.i2c import CharLCD


def main():
    events = Queue()
    lcd = None
    previous = [None] * 4

    def display(lines):
        for row, text in enumerate(lines):
            text = str(text)[:20].ljust(20)
            if text != previous[row]:
                lcd.cursor_pos = (row, 0)
                lcd.write_string(text)
                previous[row] = text

    def button_handler(name):
        def handler():
            events.put(('button', name, 0, 0))
        return handler

    def rotation_handler(number, direction, encoder):
        def handler():
            events.put(('rotation', number, direction, encoder.steps))
        return handler

    def terminate(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    with ExitStack() as stack:
        try:
            leds = {}
            for name, pin in config.LED_PINS.items():
                leds[name] = stack.enter_context(LED(pin, initial_value=False))
            lcd = CharLCD(**config.LCD_OPTIONS)
            lcd.clear()

            # Test kazdej diody osobno; widoczna nazwa pozwala sprawdzic przewody.
            for color, label in [('R', 'CZERWONA'), ('G', 'ZIELONA'), ('Y', 'ZOLTA')]:
                display(['TEST PANELU', 'Test LED: ' + label, '', 'Ctrl+C: koniec'])
                print('Test LED:', label, flush=True)
                leds[color].on()
                sleep(0.6)
                leds[color].off()

            buttons = []
            for name, pin in [('REC', config.REC_PIN), ('STOP', config.STOP_PIN),
                              ('E1 KLIK', config.E1_PINS[2]), ('E2 KLIK', config.E2_PINS[2])]:
                button = stack.enter_context(Button(pin, pull_up=True, bounce_time=0.08))
                buttons.append(button)
                button.when_pressed = button_handler(name)

            encoders = []
            for number, clk, dt in [(1, *config.E1_PINS[:2]), (2, *config.E2_PINS[:2])]:
                encoder = stack.enter_context(RotaryEncoder(clk, dt, max_steps=0))
                encoders.append(encoder)
                encoder.when_rotated_clockwise = rotation_handler(number, 1, encoder)
                encoder.when_rotated_counter_clockwise = rotation_handler(number, -1, encoder)

            positions = {1: 0, 2: 0}
            count = 0
            last = 'Nacisnij / obroc'
            off_at = {color: 0.0 for color in leds}
            print('Gotowy: naciskaj REC, STOP, oba enkodery i obracaj nimi. Ctrl+C konczy.', flush=True)
            while True:
                try:
                    kind, name, direction, steps = events.get(timeout=0.03)
                    count += 1
                    if kind == 'rotation':
                        positions[name] = steps
                        last = f'E{name}: ' + ('PRAWO' if direction > 0 else 'LEWO')
                        colors = ('G',) if direction > 0 else ('Y',)
                    else:
                        last = name + ' WCISNIETY' if name in ('REC', 'STOP') else name
                        colors = {'REC': ('R',), 'STOP': ('Y',),
                                  'E1 KLIK': ('R', 'G'), 'E2 KLIK': ('G', 'Y')}[name]
                    print(f'{count}: {last} | E1={positions[1]} E2={positions[2]}', flush=True)
                    for color in colors:
                        leds[color].on()
                        off_at[color] = monotonic() + 0.25
                except Empty:
                    pass
                now = monotonic()
                for color, led in leds.items():
                    if off_at[color] and now >= off_at[color]:
                        led.off()
                        off_at[color] = 0.0
                display(['TEST PANELU', last,
                         f'E1:{positions[1]:+d} E2:{positions[2]:+d}',
                         f'Zdarzen: {count}'])
        except KeyboardInterrupt:
            print('\nTest zakonczony.', flush=True)
        finally:
            if lcd is not None:
                try:
                    display(['TEST ZAKONCZONY', '', '', ''])
                finally:
                    lcd.close(clear=False)
            # ExitStack zamyka wejscia i gasi diody rowniez po bledzie.


if __name__ == '__main__':
    main()
