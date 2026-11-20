"""
ttm-jira: MCP server cho Jira Server / Data Center.

Bổ sung những việc mà các MCP Jira thông thường không làm được:
  - Mã issue/dự án bắt đầu bằng số (vd 10000-2538)
  - Tạo/sửa issue với trường tùy chỉnh bất kỳ (Severity, Bug Type, Epic, Sprint...), tự dò tên trường
  - Smart Checklist (plugin Railsware), nếu Jira có cài
  - Chuyển trạng thái tự tìm đường (Open -> In Progress -> Closed)
  - Chuyển sub-task/sub-bug thành issue thường
  - Báo cáo gọn: chuyển trạng thái theo ngày, bug còn tồn, hoạt động theo người

Chạy (stdio, cài local):
  uvx ttm-jira

Biến môi trường:
  JIRA_URL                 vd https://jira.example.com
  JIRA_PERSONAL_TOKEN      Personal Access Token của chính bạn
  JIRA_SSL_VERIFY          true/false (mặc định true)
  JIRA_DEFAULT_PROJECTS    vd 10000,10001 (dùng cho báo cáo, mặc định khi tìm kiếm)
  JIRA_TZ_OFFSET           múi giờ (giờ, mặc định 7)
  JIRA_MODULE_RULES        (tùy chọn) JSON {"Tên nhóm": "regex trên summary/labels"} cho báo cáo bug theo chức năng
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

# ---------------------------------------------------------------- Jira client

JIRA_URL = os.environ.get("JIRA_URL", "").rstrip("/")
TOKEN = os.environ.get("JIRA_PERSONAL_TOKEN", "")
SSL_VERIFY = os.environ.get("JIRA_SSL_VERIFY", "true").lower() not in ("0", "false", "no")
DEFAULT_PROJECTS = [p.strip() for p in os.environ.get("JIRA_DEFAULT_PROJECTS", "").split(",") if p.strip()]
TZ = dt.timezone(dt.timedelta(hours=int(os.environ.get("JIRA_TZ_OFFSET", "7"))))

_ctx = ssl.create_default_context()
if not SSL_VERIFY:
    _ctx.check_hostname = False
    _ctx.verify_mode = ssl.CERT_NONE


class JiraError(ToolError):
    pass


def _req(method: str, path: str, body: Any = None, params: dict | None = None,
         form: dict | list | None = None, raw: bool = False, timeout: int = 60):
    if not JIRA_URL or not TOKEN:
        raise JiraError("Thiếu JIRA_URL hoặc JIRA_PERSONAL_TOKEN trong biến môi trường.")
    url = JIRA_URL + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    headers = {"Authorization": f"Bearer {TOKEN}", "X-Atlassian-Token": "no-check",
               "Accept": "application/json"}
    data = None
    if form is not None:
        data = urllib.parse.urlencode([tuple(x) for x in form] if isinstance(form, list) else form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, context=_ctx, timeout=timeout) as r:
            txt = r.read().decode("utf-8", "replace")
            if raw:
                return txt
            return json.loads(txt) if txt.strip() else {}
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")[:800]
        try:
            j = json.loads(msg)
            parts = (j.get("errorMessages") or []) + [f"{k}: {v}" for k, v in (j.get("errors") or {}).items()]
            if parts:
                msg = "; ".join(parts)
        except Exception:
            pass
        raise JiraError(f"HTTP {e.code} {method} {path}: {msg}") from None
    except urllib.error.URLError as e:
        raise JiraError(f"Không kết nối được Jira ({e.reason}).") from None


def _search(jql: str, fields: str | list = "summary,status", limit: int = 50, start: int = 0,
            expand: str | None = None) -> tuple[int, list]:
    out, total = [], 0
    f = fields if isinstance(fields, str) else ",".join(fields)
    while len(out) < limit:
        page = min(100, limit - len(out))
        p = {"jql": jql, "startAt": start + len(out), "maxResults": page, "fields": f}
        if expand:
            p["expand"] = expand
        r = _req("GET", "/rest/api/2/search", params=p)
        total = r.get("total", 0)
        out.extend(r.get("issues", []))
        if not r.get("issues") or start + len(out) >= total:
            break
    return total, out


_FIELD_CACHE: dict[str, str] = {}


def _field_ids() -> dict[str, str]:
    """name(lower) -> id"""
    if not _FIELD_CACHE:
        for f in _req("GET", "/rest/api/2/field"):
            _FIELD_CACHE[f["name"].lower()] = f["id"]
            _FIELD_CACHE[f["id"].lower()] = f["id"]
    return _FIELD_CACHE


def _resolve_fields(fields: dict) -> dict:
    """Cho phép dùng tên trường ('Severity', 'Epic Link', 'Sprint') thay vì customfield_xxx.
    Giá trị chuỗi cho trường dạng option/priority/user được bọc tự động."""
    ids = _field_ids()
    res = {}
    for k, v in fields.items():
        fid = ids.get(k.lower(), k)
        if fid in ("priority", "issuetype", "resolution") and isinstance(v, str):
            v = {"name": v}
        elif fid in ("assignee", "reporter") and isinstance(v, str):
            v = {"name": v}
        elif fid in ("components", "fixVersions", "versions") and isinstance(v, list):
            v = [{"name": x} if isinstance(x, str) else x for x in v]
        res[fid] = v
    return res


def _opt_wrap(fid: str, v: Any, meta: dict | None) -> Any:
    if meta and isinstance(v, str):
        sch = (meta.get(fid) or {}).get("schema", {})
        if sch.get("type") == "option":
            return {"value": v}
        if sch.get("type") == "array" and sch.get("items") == "option":
            return [{"value": v}]
    return v


def _fmt_issue_row(i: dict) -> dict:
    f = i.get("fields", {})
    row = {"key": i["key"]}
    for name in ("summary", "duedate", "created", "updated", "labels"):
        if name in f:
            row[name] = f[name]
    for name in ("status", "issuetype", "priority", "resolution"):
        if f.get(name):
            row[name] = f[name].get("name")
    for name in ("assignee", "reporter"):
        if name in f:
            row[name] = (f[name] or {}).get("name")
    if f.get("parent"):
        row["parent"] = f["parent"]["key"]
    for k, v in f.items():
        if k.startswith("customfield_") and v not in (None, [], ""):
            if isinstance(v, dict):
                v = v.get("value") or v.get("name") or v
            elif isinstance(v, list) and v and isinstance(v[0], str) and "Sprint@" in v[0]:
                v = [(re.search(r"name=([^,]+),", s) or [None, s])[1] for s in v]
            row[k] = v
    return row


def _link_str(l: dict) -> str:
    if l.get("outwardIssue"):
        return f'{l["type"]["outward"]} {l["outwardIssue"]["key"]}'
    return f'{l["type"]["inward"]} {l["inwardIssue"]["key"]}'


def _ok(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False, indent=1, default=str)


# ---------------------------------------------------------------- MCP server

mcp = MCPServer(
    name="ttm-jira",
    instructions=(
        "Công cụ Jira Server/Data Center (mã dự án dạng số như 10000). "
        "Dùng cho: đọc/sửa/chuyển trạng thái/comment/liên kết issue mã số, tạo Bug có trường bắt buộc, "
        "Smart Checklist, chuyển sub-task thành issue, báo cáo. Liên kết: from_key [động từ outward] to_key, "
        "ví dụ link_type='Relates' (contains), from=cha, to=con."
    ),
)


@mcp.tool()
def jira_get_issue(issue_key: str, fields: str = "summary,status,issuetype,priority,assignee,reporter,labels,duedate,description,parent,issuelinks,subtasks",
                   include_comments: bool = False, comment_limit: int = 10) -> str:
    """Đọc một issue (mã dạng số được). fields: danh sách trường cách nhau dấu phẩy, '*all' để lấy tất cả."""
    f = fields + (",comment" if include_comments else "")
    i = _req("GET", f"/rest/api/2/issue/{issue_key}", params={"fields": f})
    row = _fmt_issue_row(i)
    fl = i["fields"]
    if "description" in fl:
        row["description"] = fl.get("description")
    if fl.get("issuelinks") is not None:
        row["links"] = [_link_str(l) for l in fl["issuelinks"]]
    if fl.get("subtasks"):
        row["subtasks"] = [f'{s["key"]} [{s["fields"]["status"]["name"]}] {s["fields"]["summary"]}' for s in fl["subtasks"]]
    if include_comments and fl.get("comment"):
        row["comments"] = [{"author": c["author"]["name"], "created": c["created"], "body": c["body"]}
                           for c in fl["comment"]["comments"][-comment_limit:]]
    row["url"] = f"{JIRA_URL}/browse/{i['key']}"
    return _ok(**row)


@mcp.tool()
def jira_search(jql: str, fields: str = "summary,status,issuetype,priority,assignee", limit: int = 50, start_at: int = 0) -> str:
    """Tìm issue theo JQL, trả về danh sách gọn. Mã dự án dạng số phải đặt trong ngoặc kép, vd project = "10000"."""
    total, issues = _search(jql, fields, limit, start_at)
    return _ok(total=total, returned=len(issues), issues=[_fmt_issue_row(i) for i in issues])


@mcp.tool()
def jira_find_field(keyword: str) -> str:
    """Tìm id trường (vd 'severity' -> customfield_11102) và kiểu dữ liệu."""
    res = [{"id": f["id"], "name": f["name"], "type": (f.get("schema") or {}).get("type")}
           for f in _req("GET", "/rest/api/2/field") if keyword.lower() in f["name"].lower() or keyword.lower() in f["id"].lower()]
    return _ok(fields=res[:30])


@mcp.tool()
def jira_create_issue(project_key: str, issue_type: str, summary: str, description: str = "",
                      assignee: str = "", fields_json: str = "{}", links_json: str = "[]",
                      checklist_markdown: str = "") -> str:
    """Tạo issue (kể cả Bug có trường bắt buộc). description theo cú pháp Jira wiki.
    fields_json: {"Severity":"Major","Bug Type":"Normal Function","priority":"High","labels":["release-1"],
                  "Epic Link":"10001-5750","Sprint":1264,"duedate":"2026-10-30","Start Date":"2026-10-27"}
    links_json: [{"type":"Relates","from":"10000-2544","to":"NEW"}] ('NEW' = issue vừa tạo)
    checklist_markdown: '- việc 1\\n- việc 2' (Smart Checklist)."""
    extra = _resolve_fields(json.loads(fields_json or "{}"))
    meta = {}
    try:
        cm = _req("GET", f"/rest/api/2/issue/createmeta/{project_key}/issuetypes")
        it = next((t for t in cm.get("values", []) if t["name"].lower() == issue_type.lower()), None)
        if it:
            fm = _req("GET", f"/rest/api/2/issue/createmeta/{project_key}/issuetypes/{it['id']}", params={"maxResults": 200})
            meta = {v["fieldId"]: v for v in fm.get("values", [])}
    except JiraError:
        pass
    later = {}
    fields = {"project": {"key": project_key}, "issuetype": {"name": issue_type}, "summary": summary}
    if description:
        fields["description"] = description
    if assignee:
        fields["assignee"] = {"name": assignee}
    for k, v in extra.items():
        v = _opt_wrap(k, v, meta)
        if meta and k not in meta and k not in ("project", "issuetype", "summary"):
            later[k] = v  # không có trên màn tạo -> cập nhật sau
        else:
            fields[k] = v
    r = _req("POST", "/rest/api/2/issue", body={"fields": fields})
    key = r["key"]
    notes = []
    for k, v in later.items():
        try:
            _req("PUT", f"/rest/api/2/issue/{key}", body={"fields": {k: v}})
        except JiraError as e:
            notes.append(f"Không đặt được {k}: {e}")
    for l in json.loads(links_json or "[]"):
        a = key if l["from"] == "NEW" else l["from"]
        b = key if l["to"] == "NEW" else l["to"]
        try:
            _link(l["type"], a, b)
        except JiraError as e:
            notes.append(f"Không tạo được liên kết {l}: {e}")
    if checklist_markdown:
        try:
            _checklist_set(key, checklist_markdown, True)
        except JiraError as e:
            notes.append(f"Không ghi được checklist: {e}")
    return _ok(key=key, url=f"{JIRA_URL}/browse/{key}", notes=notes)


@mcp.tool()
def jira_update_issue(issue_key: str, fields_json: str = "{}", add_labels: str = "", remove_labels: str = "") -> str:
    """Sửa issue. fields_json dùng tên trường hoặc id: {"summary":"...","description":"...","priority":"High",
    "Severity":"Major","Epic Link":"10000-2480","Sprint":1264,"duedate":"2026-10-30"}.
    add_labels/remove_labels: danh sách nhãn cách nhau dấu phẩy."""
    fields = _resolve_fields(json.loads(fields_json or "{}"))
    meta = {}
    try:
        meta = _req("GET", f"/rest/api/2/issue/{issue_key}/editmeta").get("fields", {})
    except JiraError:
        pass
    fields = {k: _opt_wrap(k, v, meta) for k, v in fields.items()}
    body: dict = {}
    sprint = fields.pop(_field_ids().get("sprint", "x"), None)
    if fields:
        body["fields"] = fields
    upd = []
    upd += [{"add": l.strip()} for l in add_labels.split(",") if l.strip()]
    upd += [{"remove": l.strip()} for l in remove_labels.split(",") if l.strip()]
    if upd:
        body["update"] = {"labels": upd}
    if body:
        _req("PUT", f"/rest/api/2/issue/{issue_key}", body=body)
    if sprint is not None:
        _req("POST", f"/rest/agile/1.0/sprint/{int(sprint)}/issue", body={"issues": [issue_key]})
    return _ok(key=issue_key, updated=list((body.get("fields") or {}).keys()) + (["labels"] if upd else []) + (["sprint"] if sprint is not None else []))


@mcp.tool()
def jira_comment(issue_key: str, body: str) -> str:
    """Thêm comment (cú pháp Jira wiki)."""
    r = _req("POST", f"/rest/api/2/issue/{issue_key}/comment", body={"body": body})
    return _ok(key=issue_key, comment_id=r.get("id"))


@mcp.tool()
def jira_assign(issue_key: str, username: str) -> str:
    """Giao issue cho người dùng (username Jira, vd nguyenvana). Chuỗi rỗng = bỏ giao."""
    _req("PUT", f"/rest/api/2/issue/{issue_key}/assignee", body={"name": username or None})
    return _ok(key=issue_key, assignee=username or None)


@mcp.tool()
def jira_get_transitions(issue_key: str) -> str:
    """Liệt kê các bước chuyển trạng thái đang có."""
    t = _req("GET", f"/rest/api/2/issue/{issue_key}/transitions")["transitions"]
    return _ok(key=issue_key, transitions=[{"id": x["id"], "name": x["name"], "to": x["to"]["name"]} for x in t])


@mcp.tool()
def jira_transition(issue_key: str, to_status: str, comment: str = "", resolution: str = "",
                    via_statuses: str = "In Progress", max_hops: int = 3) -> str:
    """Chuyển issue tới trạng thái đích (vd Closed, Rejected, Ready For Testing). Nếu không có bước trực tiếp,
    tự đi qua trạng thái trung gian trong via_statuses (cách nhau dấu phẩy). comment được thêm sau khi chuyển."""
    path = []
    vias = [s.strip().lower() for s in via_statuses.split(",") if s.strip()]
    for _ in range(max_hops):
        cur = _req("GET", f"/rest/api/2/issue/{issue_key}", params={"fields": "status"})["fields"]["status"]["name"]
        if cur.lower() == to_status.lower():
            break
        ts = _req("GET", f"/rest/api/2/issue/{issue_key}/transitions", params={"expand": "transitions.fields"})["transitions"]
        t = next((x for x in ts if x["to"]["name"].lower() == to_status.lower()), None) or \
            next((x for x in ts if x["to"]["name"].lower() in vias and x["to"]["name"].lower() != cur.lower()), None)
        if not t:
            raise JiraError(f"Từ '{cur}' không có đường tới '{to_status}'. Có: " + ", ".join(x["to"]["name"] for x in ts))
        body = {"transition": {"id": t["id"]}}
        if resolution and "resolution" in (t.get("fields") or {}):
            body["fields"] = {"resolution": {"name": resolution}}
        _req("POST", f"/rest/api/2/issue/{issue_key}/transitions", body=body)
        path.append(f"{cur} -> {t['to']['name']}")
    if comment:
        _req("POST", f"/rest/api/2/issue/{issue_key}/comment", body={"body": comment})
    st = _req("GET", f"/rest/api/2/issue/{issue_key}", params={"fields": "status,resolution"})["fields"]
    return _ok(key=issue_key, path=path, status=st["status"]["name"], resolution=(st.get("resolution") or {}).get("name"))


def _link(link_type: str, from_key: str, to_key: str):
    _req("POST", "/rest/api/2/issueLink", body={"type": {"name": link_type},
                                                "inwardIssue": {"key": from_key}, "outwardIssue": {"key": to_key}})


@mcp.tool()
def jira_link(link_type: str, from_key: str, to_key: str) -> str:
    """Tạo liên kết: from_key [động từ outward] to_key.
    Ví dụ: ('Relates', cha, con) => cha contains con; ('Blocks', A, B) => A blocks B;
    ('Duplicate', A, B) => A duplicates B; ('Relates', A, B); ('Cloners', A, B) => A clones B."""
    _link(link_type, from_key, to_key)
    t = next((x for x in _req("GET", "/rest/api/2/issueLinkType")["issueLinkTypes"] if x["name"] == link_type), {})
    return _ok(created=f"{from_key} {t.get('outward', link_type)} {to_key}")


@mcp.tool()
def jira_delete_link(from_key: str, to_key: str, link_type: str = "") -> str:
    """Xoá liên kết giữa hai issue (chỉ xoá liên kết, không xoá issue)."""
    links = _req("GET", f"/rest/api/2/issue/{from_key}", params={"fields": "issuelinks"})["fields"]["issuelinks"]
    gone = []
    for l in links:
        other = (l.get("outwardIssue") or l.get("inwardIssue"))["key"]
        if other == to_key and (not link_type or l["type"]["name"] == link_type):
            _req("DELETE", f"/rest/api/2/issueLink/{l['id']}")
            gone.append(_link_str(l))
    return _ok(deleted=gone)


@mcp.tool()
def jira_link_types() -> str:
    """Liệt kê các kiểu liên kết (name, outward, inward)."""
    return _ok(types=[{"name": t["name"], "outward": t["outward"], "inward": t["inward"]}
                      for t in _req("GET", "/rest/api/2/issueLinkType")["issueLinkTypes"]])


@mcp.tool()
def jira_add_to_sprint(sprint_id: int, issue_keys: str) -> str:
    """Đưa issue vào sprint. issue_keys cách nhau dấu phẩy."""
    keys = [k.strip() for k in issue_keys.split(",") if k.strip()]
    for n in range(0, len(keys), 50):
        _req("POST", f"/rest/agile/1.0/sprint/{sprint_id}/issue", body={"issues": keys[n:n + 50]})
    return _ok(sprint_id=sprint_id, added=keys)


@mcp.tool()
def jira_sprints(board_id: int, state: str = "active,future") -> str:
    """Liệt kê sprint của board (state: active, future, closed)."""
    r = _req("GET", f"/rest/agile/1.0/board/{board_id}/sprint", params={"state": state})
    return _ok(sprints=[{"id": s["id"], "name": s["name"], "state": s["state"], "start": s.get("startDate"), "end": s.get("endDate")} for s in r.get("values", [])])


# ---- Smart Checklist (Railsware) ------------------------------------------

def _checklist(issue_key: str) -> dict:
    r = _req("GET", "/rest/railsware/1.0/checklist", params={"issueKey": issue_key})
    cl = (r.get("checklists") or [])
    if not cl:
        raise JiraError("Issue chưa có Smart Checklist (plugin chưa bật cho issue type này?).")
    return cl[0]


def _checklist_set(issue_key: str, markdown: str, replace: bool):
    cid = _checklist(issue_key)["checklistId"]
    _req("PUT", f"/rest/railsware/1.0/checklist/{cid}/item", body={"isReplace": replace, "stringValue": markdown})


@mcp.tool()
def jira_checklist_get(issue_key: str) -> str:
    """Đọc Smart Checklist: danh sách mục và trạng thái."""
    c = _checklist(issue_key)
    return _ok(key=issue_key, items=[{"status": (i.get("status") or {}).get("name"), "text": i.get("label")} for i in c.get("items", [])])


@mcp.tool()
def jira_checklist_set(issue_key: str, markdown: str, replace: bool = True) -> str:
    """Ghi Smart Checklist. Mỗi dòng một mục: '- việc' (TO DO), '~ việc' (IN PROGRESS), '+ việc' (DONE),
    '- [SKIPPED] việc'. replace=False để thêm vào cuối."""
    _checklist_set(issue_key, markdown, replace)
    return jira_checklist_get(issue_key)


# ---- Chuyển sub-task thành issue -----------------------------------------

def _forms(page: str) -> list[dict]:
    forms = []
    for m in re.finditer(r"<form\b([^>]*)>(.*?)</form>", page, re.S | re.I):
        attrs, inner = m.group(1), m.group(2)
        action = (re.search(r'action="([^"]*)"', attrs) or [None, ""])[1]
        data: list = []
        for im in re.finditer(r"<input\b([^>]*)>", inner, re.I):
            a = im.group(1)
            name = (re.search(r'name="([^"]*)"', a) or [None, None])[1]
            if not name:
                continue
            typ = ((re.search(r'type="([^"]*)"', a) or [None, "text"])[1]).lower()
            if typ in ("submit", "button"):
                continue
            if typ in ("checkbox", "radio") and "checked" not in a:
                continue
            data.append([name, html.unescape((re.search(r'value="([^"]*)"', a) or [None, ""])[1])])
        for sm in re.finditer(r'<select\b[^>]*name="([^"]*)"[^>]*>(.*?)</select>', inner, re.S | re.I):
            opts = re.findall(r'<option\b([^>]*)>', sm.group(2), re.I)
            sel = next((o for o in opts if "selected" in o), opts[0] if opts else "")
            data.append([sm.group(1), html.unescape((re.search(r'value="([^"]*)"', sel) or [None, ""])[1])])
        forms.append({"action": html.unescape(action), "data": data, "html": inner})
    return forms


@mcp.tool()
def jira_convert_subtask(issue_key: str, issue_type: str = "Bug", field_values_json: str = "{}") -> str:
    """Chuyển sub-task/sub-bug thành issue thường (giữ mã, lịch sử, comment) qua màn chuyển đổi của Jira.
    field_values_json: giá trị cho trường bắt buộc của loại mới, theo id option, vd {"customfield_11102":"11023"}.
    Nếu bỏ trống Severity, tool tự chọn theo priority (Highest/High->Major, Medium->Medium, Low->Low)."""
    i = _req("GET", f"/rest/api/2/issue/{issue_key}", params={"fields": "issuetype,priority"})
    if not i["fields"]["issuetype"].get("subtask"):
        return _ok(key=issue_key, note="Không phải sub-task, bỏ qua.")
    types = {t["name"].lower(): t["id"] for t in _req("GET", "/rest/api/2/issuetype")}
    tid = types.get(issue_type.lower())
    if not tid:
        raise JiraError(f"Không có issue type {issue_type}")
    vals = json.loads(field_values_json or "{}")
    page = _req("GET", "/secure/ConvertSubTask.jspa", params={"id": i["id"]}, raw=True)
    f = next((x for x in _forms(page) if "ConvertSubTaskSetIssueType" in x["action"]), None)
    if not f:
        raise JiraError("Không mở được màn chuyển đổi (token có thể không dùng được cho màn web). Làm thủ công: More > Convert to Issue.")
    data = [[k, tid if k == "issuetype" else v] for k, v in f["data"]]
    for _ in range(5):
        page = _req("POST", "/secure/" + f["action"].split("/")[-1], form=data, raw=True)
        err = re.findall(r'class="[^"]*(?:error|aui-message-error)[^"]*"[^>]*>(.*?)<', page, re.S)
        err = [html.unescape(re.sub(r"\s+", " ", e)).strip() for e in err if e.strip()]
        if err:
            raise JiraError("Màn chuyển đổi báo lỗi: " + " | ".join(err[:3]))
        f = next((x for x in _forms(page) if "ConvertSubTask" in x["action"]), None)
        if not f:
            break
        data = []
        for k, v in f["data"]:
            if k in vals:
                v = vals[k]
            elif k == "customfield_11102" and not v:
                pr = (i["fields"].get("priority") or {}).get("name", "Medium")
                opts = dict((html.unescape(t).strip().lower(), val) for val, t in
                            re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)<', f["html"]))
                want = {"highest": "major", "high": "major", "medium": "medium", "low": "low", "lowest": "low"}.get(pr.lower(), "medium")
                v = opts.get(want, v)
            data.append([k, v])
    a = _req("GET", f"/rest/api/2/issue/{issue_key}", params={"fields": "issuetype,status,parent"})["fields"]
    if a["issuetype"].get("subtask"):
        raise JiraError("Chưa chuyển được (vẫn là sub-task).")
    return _ok(key=issue_key, issuetype=a["issuetype"]["name"], status=a["status"]["name"])


# ---- Báo cáo --------------------------------------------------------------

def _proj_clause(projects: str) -> str:
    ps = [p.strip() for p in (projects or ",".join(DEFAULT_PROJECTS)).split(",") if p.strip()]
    if not ps:
        raise JiraError("Cần projects (vd 10000,10001) hoặc JIRA_DEFAULT_PROJECTS.")
    return "project in (" + ",".join(f'"{p}"' for p in ps) + ")"


def _parse_dt(s: str) -> dt.datetime:
    return dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(
        tzinfo=dt.timezone(dt.timedelta(hours=int(s[23:26]), minutes=int(s[26:28]))) if len(s) >= 28 else TZ)


def _day_range(date_from: str, date_to: str) -> tuple[dt.datetime, dt.datetime]:
    a = dt.datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=TZ)
    b = dt.datetime.strptime(date_to or date_from, "%Y-%m-%d").replace(tzinfo=TZ) + dt.timedelta(days=1)
    return a, b


@mcp.tool()
def report_status_changes(date_from: str, date_to: str = "", projects: str = "", extra_jql: str = "",
                          detail_statuses: str = "Reopened,Reopen") -> str:
    """Thống kê chuyển trạng thái trong khoảng ngày (YYYY-MM-DD, giờ VN): đếm theo dự án/from->to/người,
    và liệt kê chi tiết các lần chuyển sang detail_statuses (vd Reopened) kèm người sửa trước đó."""
    a, b = _day_range(date_from, date_to)
    jql = f'{_proj_clause(projects)} AND status changed DURING ("{a:%Y/%m/%d}", "{(b - dt.timedelta(days=1)):%Y/%m/%d} 23:59")'
    if extra_jql:
        jql += f" AND ({extra_jql})"
    _, issues = _search(jql, "summary,status,assignee,priority,issuetype", 2000, expand="changelog")
    agg, by_user, detail = Counter(), defaultdict(Counter), []
    want = {s.strip().lower() for s in detail_statuses.split(",") if s.strip()}
    for i in issues:
        last_fixer = None
        for h in i.get("changelog", {}).get("histories", []):
            t = _parse_dt(h["created"])
            for it in h["items"]:
                if it["field"] != "status":
                    continue
                if re.search(r"resolved|review|ready for testing|testing", it["toString"] or "", re.I) and \
                        not re.search(r"testing", it["fromString"] or "", re.I):
                    last_fixer = h["author"]["name"]
                if not (a <= t < b):
                    continue
                k = f'{i["key"].split("-")[0]}: {it["fromString"]} -> {it["toString"]}'
                agg[k] += 1
                by_user[h["author"]["name"]][f'{it["fromString"]} -> {it["toString"]}'] += 1
                if (it["toString"] or "").lower() in want:
                    detail.append({"key": i["key"], "summary": i["fields"]["summary"], "at": t.astimezone(TZ).strftime("%d/%m %H:%M"),
                                   "by": h["author"]["name"], "from": it["fromString"], "fixer": last_fixer,
                                   "now": i["fields"]["status"]["name"], "assignee": (i["fields"]["assignee"] or {}).get("name"),
                                   "priority": (i["fields"].get("priority") or {}).get("name")})
    return _ok(range=f"{a:%d/%m/%Y} - {(b - dt.timedelta(days=1)):%d/%m/%Y}", issues=len(issues),
               transitions=dict(agg.most_common()), by_user={u: dict(c) for u, c in by_user.items()}, detail=detail)


# Nhóm chức năng cho báo cáo bug: cấu hình qua JIRA_MODULE_RULES (JSON), mặc định không phân nhóm.
_MODULES = [(k, v) for k, v in json.loads(os.environ.get("JIRA_MODULE_RULES", "{}") or "{}").items()]


def _module(summary: str, labels: list) -> str:
    u = (summary or "").upper() + " " + " ".join(labels or []).upper()
    for name, rx in _MODULES:
        if re.search(rx, u):
            return name
    return "Khác"


@mcp.tool()
def report_open_bugs(projects: str = "", scope: str = "all", sprint_id: int = 0, extra_jql: str = "",
                     list_priorities: str = "Highest") -> str:
    """Bug còn tồn, nhóm theo chức năng x độ ưu tiên x trạng thái x người.
    scope: 'all' | 'sprint' (bug trong sprint_id hoặc openSprints() + bug liên kết tới issue trong sprint).
    list_priorities: liệt kê chi tiết các bug thuộc các mức này."""
    base = f'{_proj_clause(projects)} AND issuetype in (Bug, "Sub-Bug") AND statusCategory != Done'
    if extra_jql:
        base += f" AND ({extra_jql})"
    flds = "summary,status,priority,assignee,labels,issuelinks"
    if scope == "sprint":
        sp = f"sprint = {sprint_id}" if sprint_id else "sprint in openSprints()"
        _, in_sp = _search(f"{_proj_clause(projects)} AND {sp}", flds, 3000)
        keys = {i["key"] for i in in_sp}
        linked = {(l.get("outwardIssue") or l.get("inwardIssue"))["key"] for i in in_sp for l in i["fields"].get("issuelinks", [])} - keys
        _, bugs = _search(f"{base} AND {sp}", flds, 3000)
        for n in range(0, len(linked), 80):
            chunk = sorted(linked)[n:n + 80]
            _, more = _search(f'{base} AND key in ({",".join(chunk)})', flds, 200)
            bugs += more
    else:
        _, bugs = _search(base, flds, 5000)
    want = {p.strip().lower() for p in list_priorities.split(",") if p.strip()}
    by_mod = defaultdict(Counter)
    st, pr, asg, detail = Counter(), Counter(), Counter(), []
    for b in bugs:
        f = b["fields"]
        p = (f.get("priority") or {}).get("name", "-")
        m = _module(f["summary"], f.get("labels"))
        by_mod[m][p] += 1
        by_mod[m]["Tổng"] += 1
        st[f["status"]["name"]] += 1
        pr[p] += 1
        asg[(f.get("assignee") or {}).get("name", "-")] += 1
        if p.lower() in want:
            detail.append({"key": b["key"], "priority": p, "status": f["status"]["name"], "module": m,
                           "assignee": (f.get("assignee") or {}).get("name"), "summary": f["summary"]})
    return _ok(total=len(bugs), by_priority=dict(pr), by_status=dict(st), by_assignee=dict(asg.most_common()),
               by_module={k: dict(v) for k, v in sorted(by_mod.items(), key=lambda x: -x[1]["Tổng"])}, detail=detail)


@mcp.tool()
def report_user_activity(username: str, date_from: str, date_to: str, projects: str = "") -> str:
    """Hoạt động của một người theo ngày (tạo issue, chuyển trạng thái, sửa trường, comment) – dùng để log work."""
    a, b = _day_range(date_from, date_to)
    jql = (f'{_proj_clause(projects)} AND (issuekey in updatedBy("{username}", "{a:%Y-%m-%d}", "{b:%Y-%m-%d}") '
           f'OR (reporter = "{username}" AND created >= "{a:%Y-%m-%d}" AND created < "{b:%Y-%m-%d}"))')
    _, issues = _search(jql, "summary,issuetype,created,reporter,comment", 3000, expand="changelog")
    days: dict = defaultdict(lambda: defaultdict(set))
    summ = {}
    for i in issues:
        f = i["fields"]
        k = i["key"]
        summ[k] = f["summary"]
        if (f.get("reporter") or {}).get("name") == username:
            t = _parse_dt(f["created"])
            if a <= t < b:
                days[t.astimezone(TZ).strftime("%Y-%m-%d")][k].add("tạo " + f["issuetype"]["name"])
        for h in i.get("changelog", {}).get("histories", []):
            if h["author"]["name"] != username:
                continue
            t = _parse_dt(h["created"])
            if a <= t < b:
                for it in h["items"]:
                    days[t.astimezone(TZ).strftime("%Y-%m-%d")][k].add("-> " + it["toString"] if it["field"] == "status" else it["field"])
        for c in (f.get("comment") or {}).get("comments", []):
            if c["author"]["name"] == username:
                t = _parse_dt(c["created"])
                if a <= t < b:
                    days[t.astimezone(TZ).strftime("%Y-%m-%d")][k].add("comment")
    out = {}
    for d in sorted(days):
        rows = days[d]
        cnt = Counter(x for s in rows.values() for x in s)
        out[d] = {"issues": len(rows), "actions": dict(cnt.most_common(15)),
                  "created": [f"{k} {summ[k]}" for k, s in rows.items() if any(x.startswith("tạo") for x in s)],
                  "touched": [f"{k} [{', '.join(sorted(s))[:80]}] {summ[k][:90]}" for k, s in list(rows.items())[:60]]}
    return _ok(user=username, days=out)


# ---------------------------------------------------------------- main

def main():
    mcp.run("stdio")


if __name__ == "__main__":
    main()
