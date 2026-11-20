#!/usr/bin/env bash
# Đóng gói bundle .mcpb (Claude Desktop) từ binary đã build trong dist/release/.
#   mcpb/pack.sh <version> <thư mục archive> <thư mục ra>
# Tạo: ttm-jira-darwin.mcpb (Apple Silicon; Mac Intel chưa hỗ trợ), ttm-jira-linux-x64.mcpb, ttm-jira-win32-x64.mcpb
set -euo pipefail
version="${1:?version}"; src="${2:?thư mục archive}"; out="${3:?thư mục ra}"
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$out"; out="$(cd "$out" && pwd)"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
CLI="@anthropic-ai/mcpb@2.1.2"

stage() { # stage <tên> <platform> <tên binary> <đường dẫn binary>
  local name="$1" platform="$2" bin="$3" file="$4" dir="$work/$1"
  mkdir -p "$dir/server"
  cp "$file" "$dir/server/$bin"; chmod +x "$dir/server/$bin"
  python3 "$here/make_manifest.py" "$platform" "$bin" "$version" > "$dir/manifest.json"
  npx --yes "$CLI" pack "$dir" "$out/ttm-jira-$name.mcpb" < /dev/null
  shasum -a 256 "$out/ttm-jira-$name.mcpb" | awk '{print $1}' > "$out/ttm-jira-$name.mcpb.sha256" 2>/dev/null || sha256sum "$out/ttm-jira-$name.mcpb" | awk '{print $1}' > "$out/ttm-jira-$name.mcpb.sha256"
  echo "packed $out/ttm-jira-$name.mcpb"
}

extract() { # extract <target> -> in ra đường dẫn binary
  local target="$1" dir="$work/x-$1"; mkdir -p "$dir"
  tar -xzf "$src/ttm-jira-$target.tar.gz" -C "$dir"
  echo "$dir/ttm-jira"
}

arm="$(extract darwin-arm64)"
stage darwin darwin ttm-jira "$arm"
stage linux-x64 linux ttm-jira "$(extract linux-x64)"
mkdir -p "$work/win"; unzip -o -q "$src/ttm-jira-windows-x64.zip" -d "$work/win"
stage win32-x64 win32 ttm-jira.exe "$work/win/ttm-jira.exe"
