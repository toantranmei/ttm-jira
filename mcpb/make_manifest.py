"""Sinh manifest.json cho một nền tảng: python3 make_manifest.py <platform> <bin> <version>."""
import json, sys

PARAMS = {'display': 'Jira (ttm-jira)', 'desc': 'MCP server cho Jira Server / Data Center: tạo/sửa issue, trường tùy chỉnh, chuyển trạng thái, báo cáo', 'long': 'Chạy trên máy bạn bằng Personal Access Token của chính bạn. Không gửi token tới bên thứ ba.', 'user_config': {'jira_url': {'type': 'string', 'title': 'Địa chỉ Jira', 'description': 'Ví dụ https://jira.example.com', 'required': True}, 'jira_token': {'type': 'string', 'title': 'Personal Access Token', 'description': 'Token tạo trong Jira: Profile → Personal Access Tokens', 'sensitive': True, 'required': True}, 'jira_default_projects': {'type': 'string', 'title': 'Mã dự án mặc định (tùy chọn)', 'description': 'Ví dụ 10000,10001', 'required': False}}, 'env': {'JIRA_URL': '${user_config.jira_url}', 'JIRA_PERSONAL_TOKEN': '${user_config.jira_token}', 'JIRA_DEFAULT_PROJECTS': '${user_config.jira_default_projects}'}}

platform, bin_name, version = sys.argv[1], sys.argv[2], sys.argv[3]
cmd = "${__dirname}/server/" + bin_name
m = {
  "manifest_version": "0.3",
  "name": "ttm-jira",
  "display_name": PARAMS["display"],
  "version": version,
  "description": PARAMS["desc"],
  "long_description": PARAMS["long"],
  "author": {"name": "Toan Tran", "url": "https://github.com/toantranmei"},
  "repository": {"type": "git", "url": "https://github.com/toantranmei/ttm-jira"},
  "homepage": "https://github.com/toantranmei/ttm-jira",
  "support": "https://github.com/toantranmei/ttm-jira/issues",
  "license": "MIT",
  "server": {
    "type": "binary",
    "entry_point": "server/" + bin_name,
    "mcp_config": {"command": cmd, "args": [], "env": PARAMS["env"]},
  },
  "user_config": PARAMS["user_config"],
  "compatibility": {"platforms": [platform]},
}
print(json.dumps(m, ensure_ascii=False, indent=2))
