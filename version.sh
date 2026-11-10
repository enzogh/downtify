#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

usage() {
  echo "Usage: $0 <new-version>"
  echo "       $0 --current"
  echo
  echo "Examples:"
  echo "  $0 2.6.0"
  echo "  $0 --current"
  exit 1
}

# helpers

current_version() {
  grep -m1 "__version__" "$REPO_ROOT/downtify/__init__.py" \
    | sed "s/__version__ = '//;s/'//"
}

validate_semver() {
  if ! echo "$1" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "Error: '$1' is not a valid semver version (expected X.Y.Z)." >&2
    exit 1
  fi
}

# argument parsing

[[ $# -eq 1 ]] || usage

if [[ "$1" == "--current" ]]; then
  echo "$(current_version)"
  exit 0
fi

NEW_VERSION="$1"
validate_semver "$NEW_VERSION"

OLD_VERSION="$(current_version)"

if [[ "$OLD_VERSION" == "$NEW_VERSION" ]]; then
  echo "Already at version $NEW_VERSION — nothing to do."
  exit 0
fi

echo "Bumping $OLD_VERSION → $NEW_VERSION"

# In-place edit that works with both GNU sed (Linux) and BSD sed (macOS),
# whose `-i` flags disagree: write a copy, then put it back.
edit_in_place() {
  local file="${@: -1}"
  sed "${@:1:$#-1}" "$file" > "$file.tmp" && cat "$file.tmp" > "$file"
  rm -f "$file.tmp"
}

# downtify/__init__.py

edit_in_place -e "s/__version__ = '${OLD_VERSION}'/__version__ = '${NEW_VERSION}'/" \
  "$REPO_ROOT/downtify/__init__.py"
echo "  updated downtify/__init__.py"

# pyproject.toml

edit_in_place -e "s/^version = \"${OLD_VERSION}\"/version = \"${NEW_VERSION}\"/" \
  "$REPO_ROOT/pyproject.toml"
echo "  updated pyproject.toml"

# frontend/package.json

edit_in_place -e "s/\"version\": \"${OLD_VERSION}\"/\"version\": \"${NEW_VERSION}\"/" \
  "$REPO_ROOT/frontend/package.json"
echo "  updated frontend/package.json"

# Makefile

edit_in_place -e "s/DOWNTIFY_VERSION := ${OLD_VERSION}/DOWNTIFY_VERSION := ${NEW_VERSION}/" \
  "$REPO_ROOT/Makefile"
echo "  updated Makefile"

# Dockerfile

edit_in_place \
  -e "s/LABEL version=\"${OLD_VERSION}\"/LABEL version=\"${NEW_VERSION}\"/" \
  -e "s/org.opencontainers.image.version=\"${OLD_VERSION}\"/org.opencontainers.image.version=\"${NEW_VERSION}\"/" \
  "$REPO_ROOT/Dockerfile"
echo "  updated Dockerfile"

# verify

echo
echo "Verification:"
grep "__version__"                    "$REPO_ROOT/downtify/__init__.py"
grep "^version"                       "$REPO_ROOT/pyproject.toml"
grep '"version"'                      "$REPO_ROOT/frontend/package.json" | head -1
grep 'LABEL version'                  "$REPO_ROOT/Dockerfile"
