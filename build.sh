#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT
cp workflow/info.plist "$staging/"
[ -f workflow/icon.png ] && cp workflow/icon.png "$staging/"
cp -R src/kobolib "$staging/" && find "$staging" -name __pycache__ -type d -exec rm -rf {} +
mkdir -p dist
rm -f "dist/Kobo Library.alfredworkflow"
(cd "$staging" && zip -q -r "$OLDPWD/dist/Kobo Library.alfredworkflow" .)
echo "dist/Kobo Library.alfredworkflow"
