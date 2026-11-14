"""Shared settings. Optional config_local.py overrides defaults (never commit it)."""
from pathlib import Path
import importlib.util

PROJECT_DIR = Path(__file__).resolve().parent
RECORDINGS_DIR = Path.home() / "recordings"
LOCK_FILE = PROJECT_DIR / ".panel.lock"
CAPTURE_DEVICE = "hw:CARD=UMC1820,DEV=0"
PLAYBACK_DEVICE = "alsa/plughw:CARD=UMC1820,DEV=0"
REC_PIN = 17
STOP_PIN = 27
E1_PINS = (5, 6, 13)  # CLK, DT, SW; BCM numbering
E2_PINS = (16, 12, 26)
E1_DIRECTION = 1
E2_DIRECTION = 1
LED_PINS = {"R": 22, "G": 23, "Y": 24}
LCD_OPTIONS = dict(i2c_expander="PCF8574", address=0x27, port=1,
                   cols=20, rows=4, backlight_enabled=True)

# Load only this checkout's local configuration; propagate errors in that file.
_local_path = PROJECT_DIR / "config_local.py"
if _local_path.is_file():
    _spec = importlib.util.spec_from_file_location("_pirecorder_local", _local_path)
    _local = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_local)
    _allowed = {name for name in globals() if name.isupper()} - {"PROJECT_DIR"}
    for _name in vars(_local):
        if _name.isupper():
            if _name not in _allowed:
                raise ValueError(f"Unknown piRecorder setting: {_name}")
            globals()[_name] = getattr(_local, _name)

for _name in ("RECORDINGS_DIR", "LOCK_FILE"):
    _path = Path(globals()[_name]).expanduser()
    globals()[_name] = _path if _path.is_absolute() else PROJECT_DIR / _path
