# piRecorder

Rejestrator audio na Raspberry Pi z UMC1820, LCD 20×4, przyciskami,
enkoderami i diodami. Punkt wejścia: `recorder_main.py`.

## Konfiguracja

`config.py` zawiera wspólne ścieżki, urządzenia ALSA, GPIO (BCM) oraz LCD.
Domyślny folder nagrań to `~/recordings`; katalog projektu jest wykrywany
na podstawie położenia plików, niezależnie od katalogu roboczego.
Parametry formatu nagrywania pozostają stałe: 10 kanałów, 48 kHz, S32_LE.

Opcjonalne ustawienia tylko dla tego RPi:

```bash
cp config_local.example.py config_local.py
nano config_local.py
```

Odkomentuj wybrane ustawienia. `config_local.py` jest ignorowany przez Git;
nie importuj w nim `config`. Względne ścieżki są liczone od katalogu projektu.
Plik jest kodem Pythona — używaj tylko zaufanej zawartości. Błędy w lokalnej
konfiguracji zatrzymują start, zamiast po cichu przywracać ustawienia domyślne.
Hasła i tokeny nie należą do konfiguracji publicznej; `.env` jest ignorowany,
ale aplikacja obecnie nie ładuje go automatycznie.

Domyślne E2: CLK=16, DT=12, SW=26. Program testowy używa tych samych pinów
co panel. Nie uruchamiaj obu programów jednocześnie. Starsze `recorder.py`
i `recorder_lcd.py` są alternatywnymi programami, a nie modułami usługi.

## Usługa na istniejącym RPi

Wymagane: działające `.venv` z gpiozero, RPLCD i odpowiednim backendem GPIO,
I2C, dostęp do GPIO/audio oraz zainstalowane `alsa-utils` i `mpv`.
Instalator nie instaluje zależności ani nie zmienia konfiguracji sprzętu.

```bash
bash scripts/install-service.sh
# Po zakończeniu nagrywania i odsłuchu:
sudo systemctl restart recorder.service
systemctl status recorder.service --no-pager
```

Uruchamiaj instalator bez sudo. Używa aktualnego użytkownika i katalogu projektu;
ścieżka instalacji musi być bez spacji i znaków specjalnych. Plik
`systemd/recorder.service` jest szablonem — nie kopiuj go bezpośrednio do `/etc`.
Instalator ustawia autostart oraz dowiązanie `~/.local/bin/xd`, ale nie restartuje
pracującego programu. W razie zmiany szablonu uruchom instalator ponownie.
Dotychczasowa usługa na `/home/jk/recorder` nadal działa bez reinstalacji.

## Ręczna aktualizacja

Po zakończeniu nagrywania i odsłuchu wpisz `xd` (lub `~/.local/bin/xd`).
Skrypt wymaga czystej gałęzi `main`, pobiera `origin/main`, pyta przed zmianą,
aktualizuje przez fast-forward i restartuje `recorder.service`.
Nie ma timera ani aktualizacji w tle. Skrypt nie wykrywa nagrywania, nie instaluje
zależności, nie wdraża szablonu usługi i nie wycofuje automatycznie błędnej wersji.
Nie naciskaj REC podczas aktualizacji. Klucz SSH z hasłem może wymagać jego podania.
