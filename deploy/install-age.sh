#!/bin/sh
set -eu

AGE_VERSION=1.3.1
AGE_LINUX_AMD64_SHA256=bdc69c09cbdd6cf8b1f333d372a1f58247b3a33146406333e30c0f26e8f51377
DESTINATION=${1:-/opt/vps-agent/tools/age/1.3.1}

fail() { echo "$1" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || fail "age installation must run as root"
[ "$(uname -s)" = Linux ] || fail "only the pinned Linux age asset is supported"
[ "$(uname -m)" = x86_64 ] || fail "only the pinned linux-amd64 age asset is supported"
case "$DESTINATION" in /*) ;; *) fail "age destination must be absolute" ;; esac
case "$DESTINATION" in /|/opt|/opt/vps-agent|/tmp|/var) fail "age destination is too broad" ;; esac
[ ! -L "$DESTINATION" ] || fail "age destination must not be a symlink"
command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required"
command -v tar >/dev/null 2>&1 || fail "tar is required"

parent=$(dirname "$DESTINATION")
mkdir -p "$parent"
chmod 755 "$parent"
temporary=$(mktemp -d "$parent/.age-install-XXXXXX")
trap 'case "$temporary" in "$parent"/.age-install-*) rm -rf -- "$temporary" ;; esac' EXIT HUP INT TERM
archive="$temporary/age.tar.gz"
curl -fL --proto '=https' --tlsv1.2 \
  "https://github.com/FiloSottile/age/releases/download/v${AGE_VERSION}/age-v${AGE_VERSION}-linux-amd64.tar.gz" \
  -o "$archive"
printf '%s  %s\n' "$AGE_LINUX_AMD64_SHA256" "$archive" | sha256sum -c - >/dev/null
mkdir "$temporary/extracted"
tar -xzf "$archive" -C "$temporary/extracted"
binary="$temporary/extracted/age/age"
keygen="$temporary/extracted/age/age-keygen"
[ -f "$binary" ] && [ ! -L "$binary" ] && [ -f "$keygen" ] && [ ! -L "$keygen" ] || fail "pinned age archive layout is invalid"
version=$($binary --version)
[ "$version" = "$AGE_VERSION" ] || [ "$version" = "v$AGE_VERSION" ] || [ "$version" = "age $AGE_VERSION" ] || fail "age version mismatch"
install -d -m 0755 "$temporary/final"
install -m 0755 "$binary" "$temporary/final/age"
install -m 0755 "$keygen" "$temporary/final/age-keygen"
binary_sha256=$(sha256sum "$temporary/final/age" | awk '{print $1}')
printf '{"archive_sha256":"%s","binary_sha256":"%s","version":"%s"}\n' \
  "$AGE_LINUX_AMD64_SHA256" "$binary_sha256" "$AGE_VERSION" \
  >"$temporary/final/age.verified.json"
chmod 0644 "$temporary/final/age.verified.json"
[ ! -e "$DESTINATION" ] || fail "refusing to replace an existing age installation"
mv "$temporary/final" "$DESTINATION"
trap - EXIT HUP INT TERM
rm -rf -- "$temporary"
printf '{"age_version":"%s","installed_path":"%s","success":true}\n' "$AGE_VERSION" "$DESTINATION/age"
