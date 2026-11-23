#!/usr/bin/env bash
# Cài ttm-jira (binary đã build sẵn) vào ~/.local/bin. Không cần Python hay uv.
#   curl -fsSL https://raw.githubusercontent.com/toantranmei/ttm-jira/main/install.sh | bash
# Biến tùy chọn: TTM_VERSION (mặc định bản mới nhất), TTM_INSTALL_DIR, TTM_BASE_URL (dùng để thử cục bộ).
# Script dùng cú pháp bash (pipefail); sh của Debian/Ubuntu (dash) không chạy được.
if [ -z "${BASH_VERSION:-}" ]; then
  echo "Cần chạy bằng bash: curl -fsSL https://raw.githubusercontent.com/toantranmei/ttm-jira/main/install.sh | bash" >&2
  exit 1
fi
set -euo pipefail

NAME="ttm-jira"
REPO="toantranmei/ttm-jira"
INSTALL_DIR="${TTM_INSTALL_DIR:-$HOME/.local/bin}"
if [ -n "${TTM_BASE_URL:-}" ]; then BASE="$TTM_BASE_URL"
elif [ -n "${TTM_VERSION:-}" ]; then BASE="https://github.com/$REPO/releases/download/$TTM_VERSION"
else BASE="https://github.com/$REPO/releases/latest/download"; fi

os="$(uname -s)"; arch="$(uname -m)"
case "$os" in
  Darwin) os_id="darwin" ;;
  Linux)  os_id="linux" ;;
  *) echo "Hệ điều hành chưa hỗ trợ: $os. Trên Windows dùng install.ps1." >&2; exit 1 ;;
esac
case "$arch" in
  arm64|aarch64) arch_id="arm64" ;;
  x86_64|amd64)  arch_id="x64" ;;
  *) echo "Kiến trúc chưa hỗ trợ: $arch" >&2; exit 1 ;;
esac

if [ "$os_id" = "darwin" ] && [ "$arch_id" = "x64" ]; then
  echo "Mac Intel chưa có bản dựng sẵn. Dùng Mac Apple Silicon, hoặc cài bằng Python: uvx $NAME (sau khi có gói PyPI)." >&2; exit 1
fi

target="$os_id-$arch_id"
archive="$NAME-$target.tar.gz"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

echo "Tải $archive ..."
curl -fsSL "$BASE/$archive" -o "$tmp/$archive"
curl -fsSL "$BASE/$archive.sha256" -o "$tmp/$archive.sha256"

expected="$(tr -d '[:space:]' < "$tmp/$archive.sha256")"
if command -v shasum >/dev/null; then actual="$(shasum -a 256 "$tmp/$archive" | awk '{print $1}')"
else actual="$(sha256sum "$tmp/$archive" | awk '{print $1}')"; fi
if [ "$expected" != "$actual" ]; then
  echo "Sai checksum. Dừng cài đặt." >&2; exit 1
fi

tar -xzf "$tmp/$archive" -C "$tmp"
mkdir -p "$INSTALL_DIR"
install -m 0755 "$tmp/$NAME" "$INSTALL_DIR/$NAME"

echo ""
echo "Đã cài: $INSTALL_DIR/$NAME"
case ":$PATH:" in *":$INSTALL_DIR:"*) ;; *) echo "Lưu ý: $INSTALL_DIR chưa có trong PATH. Thêm vào ~/.zshrc hoặc ~/.bashrc:  export PATH=\"$INSTALL_DIR:\$PATH\"";; esac
echo ""
echo "Cấu hình xong là dùng được. Không cần đăng nhập thêm."
echo ""
echo "Đăng ký với Claude Code (thay giá trị trong <>):"
cat <<'CMD'
claude mcp add ttm-jira \
  -e JIRA_URL=https://jira.example.com \
  -e JIRA_PERSONAL_TOKEN=<token-của-bạn> \
  -- "$HOME/.local/bin/ttm-jira"
CMD
echo ""
echo "Claude Desktop: tải bundle .mcpb ở trang Releases và mở file, rồi điền cấu hình trong giao diện."
