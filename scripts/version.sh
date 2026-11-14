#!/usr/bin/env bash
set -euo pipefail

script_path="$(readlink -f -- "${BASH_SOURCE[0]}")"
project_dir="$(dirname -- "$(dirname -- "$script_path")")"
version_file="$project_dir/VERSION"

if [[ ! -r "$version_file" ]]; then
    echo "Nie można odczytać pliku VERSION: $version_file" >&2
    exit 1
fi

version="$(tr -d '[:space:]' < "$version_file")"
if [[ -z "$version" ]]; then
    echo "Plik VERSION jest pusty." >&2
    exit 1
fi

echo "piRecorder $version"

if git -C "$project_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    commit="$(git -C "$project_dir" rev-parse --short=8 HEAD)"
    commit_date="$(git -C "$project_dir" show -s --format=%ci HEAD)"
    branch="$(git -C "$project_dir" branch --show-current)"
    [[ -n "$branch" ]] || branch="(detached HEAD)"

    if [[ -n "$(git -C "$project_dir" status --porcelain)" ]]; then
        worktree_status="lokalne zmiany"
    else
        worktree_status="czysto"
    fi

    remote_status="brak danych o origin/main"
    if git -C "$project_dir" rev-parse --verify origin/main >/dev/null 2>&1; then
        read -r behind ahead < <(
            git -C "$project_dir" rev-list --left-right --count origin/main...HEAD
        )
        if (( behind == 0 && ahead == 0 )); then
            remote_status="zgodna z origin/main"
        elif (( behind > 0 && ahead == 0 )); then
            remote_status="$behind commit(ów) za origin/main"
        elif (( behind == 0 && ahead > 0 )); then
            remote_status="$ahead commit(ów) przed origin/main"
        else
            remote_status="rozbieżna: za=$behind, przed=$ahead"
        fi
    fi

    echo "Commit:  $commit ($commit_date)"
    echo "Gałąź:   $branch"
    echo "Repo:     $worktree_status; $remote_status"
else
    echo "Git:      brak repozytorium"
fi

if command -v systemctl >/dev/null 2>&1; then
    service_status="$(systemctl is-active recorder.service 2>/dev/null || true)"
    [[ -n "$service_status" ]] || service_status="nieznany"
    echo "Usługa:   $service_status"
fi

echo "Uwaga: xdver nie łączy się z GitHubem; komenda xd sprawdza aktualizacje."
