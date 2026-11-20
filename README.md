# ttm-jira

MCP server cho **Jira Server / Data Center**. Chạy trên máy bạn bằng **Personal Access Token của chính bạn**. Không có dịch vụ http, không lưu token ở nơi khác.

Gồm các việc mà MCP Jira thông thường chưa làm được: mã issue dạng số, trường tùy chỉnh bất kỳ (tên thay cho `customfield_xxx`), Smart Checklist, chuyển trạng thái tự tìm đường, chuyển sub-task thành issue, báo cáo theo ngày/người/chức năng.

## Cài nhanh (khuyến nghị, không cần Python)

Cài binary đã dựng sẵn cho macOS Apple Silicon, Linux (x64 và arm64) và Windows x64. Mac Intel tạm chưa có bản dựng sẵn.

**macOS / Linux**
```bash
curl -fsSL https://raw.githubusercontent.com/toantranmei/ttm-jira/main/install.sh | sh
```

**Windows (PowerShell)**
```powershell
irm https://raw.githubusercontent.com/toantranmei/ttm-jira/main/install.ps1 | iex
```

Script tải file từ GitHub Releases, kiểm tra checksum, rồi cài vào `~/.local/bin` (macOS/Linux) hoặc `%LOCALAPPDATA%\ttm\bin` (Windows).

Sau khi cài, đăng ký với Claude Code (thay giá trị trong `<>`):

```bash
claude mcp add ttm-jira \
  -e JIRA_URL=https://jira.example.com \
  -e JIRA_PERSONAL_TOKEN=<token-của-bạn> \
  -- "$HOME/.local/bin/ttm-jira"
```

Trên Windows, đường dẫn là `%LOCALAPPDATA%\ttm\bin\ttm-jira.exe`.

Token lấy tại Jira: **Profile → Personal Access Tokens**.

## Claude Desktop (không dùng terminal)

Tải file `ttm-jira-*.mcpb` mới nhất ở trang [Releases](https://github.com/toantranmei/ttm-jira/releases), nhấp đúp để cài, rồi điền **Địa chỉ Jira** và **Personal Access Token** trong giao diện.

## Cài bằng Python (tùy chọn)

Nếu bạn đã có [`uv`](https://docs.astral.sh/uv/):

```bash
claude mcp add ttm-jira -e JIRA_URL=… -e JIRA_PERSONAL_TOKEN=… -- uvx ttm-jira
```

Gói PyPI sẽ có sau khi phát hành lần đầu.

## Biến môi trường

| Biến | Bắt buộc | Mặc định | Mô tả |
|---|---|---|---|
| `JIRA_URL` | có | — | Địa chỉ Jira, ví dụ `https://jira.example.com` |
| `JIRA_PERSONAL_TOKEN` | có | — | Personal Access Token của bạn |
| `JIRA_SSL_VERIFY` | không | `true` | Đặt `false` chỉ khi Jira dùng chứng chỉ tự ký nội bộ |
| `JIRA_DEFAULT_PROJECTS` | không | — | Mã dự án mặc định, ví dụ `10000,10001` |
| `JIRA_TZ_OFFSET` | không | `7` | Múi giờ (giờ) cho báo cáo theo ngày |
| `JIRA_MODULE_RULES` | không | — | JSON `{"Tên nhóm": "regex"}` để phân nhóm bug trong `report_open_bugs` |

Ví dụ `JIRA_MODULE_RULES`:

```json
{"Đăng nhập": "LOGIN|ĐĂNG NHẬP", "Thanh toán": "PAY|THANH TOÁN"}
```

## Công cụ (20 tool)

- **Issue:** `jira_get_issue`, `jira_search`, `jira_find_field`, `jira_create_issue`, `jira_update_issue`, `jira_comment`, `jira_assign`, `jira_convert_subtask`
- **Trạng thái và liên kết:** `jira_get_transitions`, `jira_transition`, `jira_link`, `jira_delete_link`, `jira_link_types`
- **Sprint:** `jira_sprints`, `jira_add_to_sprint`
- **Smart Checklist:** `jira_checklist_get`, `jira_checklist_set`
- **Báo cáo:** `report_status_changes`, `report_open_bugs`, `report_user_activity`

## Bảo mật

- Token nằm trong cấu hình của client trên máy bạn. Không đưa token vào repo, log hay ảnh chụp màn hình.
- Server chỉ gọi tới `JIRA_URL` bạn cấu hình. Không mở cổng mạng.

## Phát triển

```bash
git clone https://github.com/toantranmei/ttm-jira && cd ttm-jira
uv run --with-editable . ttm-jira            # chạy stdio
packaging/build.sh ttm-jira darwin-arm64     # dựng binary + archive trong dist/release/
```

Phát hành: đẩy tag `v*` để GitHub Actions dựng binary cho 4 nền tảng, đóng gói `.mcpb` và tạo Release.

## Giấy phép

MIT. Xem [LICENSE](LICENSE).
