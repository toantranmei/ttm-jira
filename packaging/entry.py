"""Điểm vào cho PyInstaller: binary chạy MCP server qua stdio."""

import sys

# stdio MCP phải dùng UTF-8. Trên Windows, pipe mặc định dùng code page cục bộ (cp1252) và làm hỏng tiếng Việt.
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

from ttm_jira.server import main

if __name__ == "__main__":
    main()
