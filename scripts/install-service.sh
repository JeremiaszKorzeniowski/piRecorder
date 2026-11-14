#!/usr/bin/env bash
set -euo pipefail

if [[ "$EUID" == 0 ]]; then
    echo "Uruchom jako zwykly uzytkownik, bez sudo; skrypt sam poprosi o sudo."
    exit 1
fi
script_path="$(readlink -f -- "${BASH_SOURCE[0]}")"
project_dir="$(dirname -- "$(dirname -- "$script_path")")"
service_user="$(id -un)"
# Restrict substitution to characters safe in systemd directives and sed.
if [[ ! "$project_dir" =~ ^/[a-zA-Z0-9_./-]+$ || ! "$service_user" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "Instalator wymaga sciezki bez spacji i znakow specjalnych."
    exit 1
fi
if [[ ! -x "$project_dir/.venv/bin/python" ]]; then
    echo "Brak interpretera: $project_dir/.venv/bin/python"
    exit 1
fi
unit_file="$(mktemp)"
trap 'rm -f -- "$unit_file"' EXIT
sed -e "s|@USER@|$service_user|g" -e "s|@PROJECT_DIR@|$project_dir|g" \
    "$project_dir/systemd/recorder.service" > "$unit_file"
sudo install -m 644 "$unit_file" /etc/systemd/system/recorder.service
sudo systemctl daemon-reload
sudo systemctl enable recorder.service
mkdir -p "$HOME/.local/bin"
ln -sfn "$project_dir/scripts/update.sh" "$HOME/.local/bin/xd"
ln -sfn "$project_dir/scripts/update.sh" "$HOME/.local/bin/xdver"
echo "Usluga zainstalowana. Po zakonczeniu nagrywania: sudo systemctl restart recorder.service"
echo "Aktualizacja: $HOME/.local/bin/xd (dodaj ~/.local/bin do PATH, jesli potrzeba)."
echo "Wersja: $HOME/.local/bin/xdver"
