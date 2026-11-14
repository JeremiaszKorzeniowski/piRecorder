#!/usr/bin/env bash
set -euo pipefail

main() {

script_path="$(readlink -f -- "${BASH_SOURCE[0]}")"
project_dir="$(dirname -- "$(dirname -- "$script_path")")"

if [[ "$(basename -- "$0")" == "xdver" ]]; then
    exec bash "$project_dir/scripts/version.sh" "$@"
fi

cd "$project_dir"

if [[ "$(git branch --show-current)" != "main" ]]; then
    echo "Aktualizacja wymaga galezi main."
    exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
    echo "Masz lokalne zmiany. Zapisz je w Git przed aktualizacją."
    exit 1
fi

echo "Pobieram informacje z GitHuba..."
git fetch origin

if [[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]]; then
    echo "Masz już aktualną wersję."
    exit 0
fi

git merge-base --is-ancestor HEAD origin/main || {
    echo "Historia lokalna różni się od origin/main. Potrzebne ręczne sprawdzenie."
    exit 1
}

read -r -p "Zakończ nagrywanie i odsłuch. Aktualizować teraz? [t/N] " answer
[[ "$answer" == "t" || "$answer" == "T" ]] || exit 0

git merge --ff-only origin/main
sudo systemctl restart recorder.service
systemctl status recorder.service --no-pager

}
main "$@"
