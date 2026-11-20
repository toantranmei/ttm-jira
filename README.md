# ttm-jira

MCP server cho **Jira Server / Data Center**. Chạy trên máy bạn (stdio), dùng **Personal Access Token của chính bạn**. Không có dịch vụ http, không lưu token ở nơi khác.

Gồm các việc mà MCP Jira thông thường chưa làm được:

- Mã issue/dự án bắt đầu bằng số (ví dụ `10000-2538`).
- Tạo/sửa issue với trường tùy chỉnh bất kỳ (Severity, Bug Type, Epic, Sprint…). Tên trường dùng được thay cho `customfield_xxx`.
- Smart Checklist (plugin Railsware), nếu Jira bạn có cài.
- Chuyển trạng thái tự tìm đường (ví dụ Open → In Progress → Closed).
- Chuyển sub-task/sub-bug thành issue thường.
- Báo cáo gọn: chuyển trạng thái theo ngày, bug còn tồn, hoạt động theo người.

## Cài đặt

Yêu cầu: Python 3.10+ và [`uv`](https://docs.astral.sh/uv/).

### Claude Code

```bash
claude mcp add ttm-jira \
  -e JIRA_URL=https://jira.example.com \
  -e JIRA_PERSONAL_TOKEN=<token-của-bạn> \
  -- uvx ttm-jira
```

### Claude Desktop

Thêm vào `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ttm-jira": {
      "command": "uvx",
      "args": ["ttm-jira"],
      "env": {
        "JIRA_URL": "https://jira.example.com",
        "JIRA_PERSONAL_TOKEN": "<token-của-bạn>"
      }
    }
  }
}
```

### Cursor / VS Code

Dùng cùng khối `command`/`args`/`env` như trên trong file cấu hình MCP của client.

## Biến môi trường

| Biến | Bắt buộc | Mặc định | Mô tả |
|---|---|---|---|
| `JIRA_URL` | có | — | Địa chỉ Jira, ví dụ `https://jira.example.com` |
| `JIRA_PERSONAL_TOKEN` | có | — | Personal Access Token của bạn (Jira → Profile → Personal Access Tokens) |
| `JIRA_SSL_VERIFY` | không | `true` | Đặt `false` chỉ khi Jira dùng chứng chỉ tự ký nội bộ |
| `JIRA_DEFAULT_PROJECTS` | không | — | Danh sách mã dự án mặc định, ví dụ `10000,10001` |
| `JIRA_TZ_OFFSET` | không | `7` | Múi giờ (giờ) dùng cho báo cáo theo ngày |
| `JIRA_MODULE_RULES` | không | — | JSON `{"Tên nhóm": "regex"}` để phân nhóm bug theo chức năng trong `report_open_bugs` |

Ví dụ `JIRA_MODULE_RULES`:

```json
{"Đăng nhập": "LOGIN|ĐĂNG NHẬP", "Thanh toán": "PAY|THANH TOÁN"}
```

## Công cụ (20 tool)

**Issue:** `jira_get_issue`, `jira_search`, `jira_find_field`, `jira_create_issue`, `jira_update_issue`, `jira_comment`, `jira_assign`, `jira_convert_subtask`

**Trạng thái và liên kết:** `jira_get_transitions`, `jira_transition`, `jira_link`, `jira_delete_link`, `jira_link_types`

**Sprint:** `jira_sprints`, `jira_add_to_sprint`

**Smart Checklist:** `jira_checklist_get`, `jira_checklist_set`

**Báo cáo:** `report_status_changes`, `report_open_bugs`, `report_user_activity`

## Ví dụ cấu hình báo cáo

Nhóm bug theo chức năng, và báo cáo cho một dự án:

```
JIRA_DEFAULT_PROJECTS=10000
JIRA_MODULE_RULES={"Đăng nhập": "LOGIN|ĐĂNG NHẬP"}
```

## Bảo mật

- Token nằm trong biến môi trường trên máy bạn. Không đưa token vào repo, log hay ảnh chụp màn hình.
- Server chỉ gọi tới `JIRA_URL` bạn cấu hình.
- Không có chế độ http, không mở cổng mạng.

## Phát triển

```bash
git clone https://github.com/toantranmei/ttm-jira
cd ttm-jira
uv run --with mcp==2.3.0 python -m py_compile src/ttm_jira/server.py
```

## Giấy phép

MIT. Xem [LICENSE](LICENSE).
