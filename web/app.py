"""DeepSearch Pro — 控制台（Claude 风格单栏布局）

设计原则：
- 平时只看到三样东西：你的提问、Agent 自己生成的任务清单、最终报告。
- 中间过程（模型逐字输出、每一次工具调用）默认折叠，只在顶部留一行
  「正在做什么」的实时状态。
- 任务清单不是前端写死的，是后端 plan_update 事件推上来的（Agent 调
  write_todos 的结果）。你可以改完再推回去覆盖 Agent 的计划。

启动：
    pip install streamlit requests websocket-client
    streamlit run web/app.py
后端：
    uvicorn app.main:create_app --factory --reload --port 8000
"""

from __future__ import annotations

import html
import inspect
import json
import queue
import threading
import time
import uuid

import requests
import streamlit as st
import websocket  # websocket-client

st.set_page_config(
    page_title="DeepSearch Pro",
    page_icon="🔎",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ---- Streamlit 版本兼容：新版 width="stretch"，旧版 use_container_width=True ----
_HAS_WIDTH = "width" in inspect.signature(st.button).parameters


def W() -> dict:
    return {"width": "stretch"} if _HAS_WIDTH else {"use_container_width": True}


_FRAGMENT = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)

# ---------------------------------------------------------------- 外观
st.markdown("""
<style>
:root{
  --bg:#FAF9F5; --card:#FFFFFF; --line:#E7E4DB;
  --ink:#1F1E1D; --muted:#7A776F; --accent:#C96442;
}
.stApp{ background:var(--bg); }
.block-container{ padding-top:2.2rem; padding-bottom:6rem; max-width:760px; }
#MainMenu, footer{ visibility:hidden; }

/* ★ 白底白字修复。
   Streamlit 默认跟随操作系统深/浅色：系统开深色模式时它把正文改成白色，
   而下面这些卡片背景是写死的白色 —— 于是白底白字。
   根治办法是 .streamlit/config.toml 里把 base 钉成 light（已配）；
   这里再兜一层，把容器背景和文字色都显式指定，防止某些组件漏掉主题变量。 */
.stApp, .stApp p, .stApp li, .stApp td, .stApp th,
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6,
.stApp label, .stApp .stMarkdown{ color:var(--ink); }
.stApp a{ color:var(--accent); }
.stApp code{ background:#F1EFE8; color:#8A3B22; }
/* st.container(border=True) 渲染出来的外框 */
[data-testid="stVerticalBlockBorderWrapper"]{
  background:var(--card); border-color:var(--line) !important; border-radius:14px;
}
[data-testid="stExpander"]{ background:var(--card); border-radius:12px; }
[data-testid="stExpander"] summary{ color:var(--ink); }

.ds-title{ font-size:1.45rem; font-weight:600; color:var(--ink); margin:0 0 .15rem 0; }
.ds-sub{ font-size:.8rem; color:var(--muted); margin-bottom:1.4rem; }

.ds-ask{
  background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:.85rem 1.05rem; margin:.2rem 0 1.1rem 0;
  font-size:1rem; color:var(--ink); line-height:1.6;
}
.ds-ask .lbl{ font-size:.72rem; color:var(--muted); letter-spacing:.04em; display:block; margin-bottom:.3rem; }

.ds-card{
  background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:.9rem 1.1rem; margin-bottom:.9rem;
}
.ds-card h4{
  font-size:.74rem; font-weight:600; color:var(--muted);
  letter-spacing:.06em; margin:0 0 .6rem 0; text-transform:uppercase;
}
.ds-todo{ display:flex; gap:.55rem; align-items:flex-start; padding:.24rem 0; font-size:.93rem; line-height:1.55; }
.ds-todo .mark{ width:1.1rem; flex:0 0 1.1rem; text-align:center; }
.ds-todo.done   .txt{ color:var(--muted); text-decoration:line-through; }
.ds-todo.doing  .txt{ color:var(--ink); font-weight:600; }
.ds-todo.wait   .txt{ color:var(--muted); }

.ds-live{
  display:flex; align-items:center; gap:.55rem;
  font-size:.88rem; color:var(--ink);
  background:var(--card); border:1px solid var(--line);
  border-left:3px solid var(--accent);
  border-radius:10px; padding:.6rem .9rem; margin-bottom:.9rem;
}
.ds-live .dot{
  width:7px; height:7px; border-radius:50%; background:var(--accent);
  animation:ds-pulse 1.1s ease-in-out infinite; flex:0 0 7px;
}
@keyframes ds-pulse{ 0%,100%{opacity:.25;} 50%{opacity:1;} }
.ds-live .el{ margin-left:auto; color:var(--muted); font-size:.78rem; font-variant-numeric:tabular-nums; }

.ds-done{
  font-size:.82rem; color:var(--muted); margin-bottom:.9rem;
  padding:.5rem .9rem; border:1px solid var(--line); border-radius:10px; background:var(--card);
}
.ds-step{ font-size:.83rem; color:var(--muted); padding:.16rem 0; line-height:1.5; }
.ds-step b{ color:var(--ink); font-weight:600; }
.ds-step .el{ color:#A9A69D; }
.ds-answer{ font-size:.97rem; line-height:1.75; color:var(--ink); }
.stChatInput textarea{ font-size:.95rem; }
</style>
""", unsafe_allow_html=True)

STATUS_OPTIONS = ["pending", "in_progress", "completed"]
TODO_MARK = {"completed": ("✓", "done"), "in_progress": ("◐", "doing"), "pending": ("○", "wait")}
# 任务已结束、但这一项没被 Agent 标记完成时用的记号。
# 不伪装成 ✓ —— 那会掩盖"中途放弃"这种真实情况。
TODO_MARK_STALE = ("⊘", "wait")

TOOL_LABEL = {
    "internet_search": ("🌐", "联网搜索"),
    "task": ("🤝", "派发子 Agent"),
    "write_todos": ("🗂️", "更新任务清单"),
    "execute_sql_query": ("🗄️", "执行 SQL 查询"),
    "list_sql_table": ("🗄️", "列出数据表"),
    "describe_table": ("🗄️", "查看表结构"),
    "get_table_data": ("🗄️", "取样表数据"),
    "search_knowledge_base": ("📚", "检索知识库"),
    "list_past_reports": ("🗃️", "查历史报告"),
    "ls": ("📁", "浏览文件"),
    "read_file": ("📄", "读取文件"),
    "write_file": ("📝", "写入文件"),
    "edit_file": ("✏️", "修改文件"),
}


def tool_label(name: str) -> tuple[str, str]:
    return TOOL_LABEL.get(name, ("🔧", f"调用 {name}"))


def esc(s) -> str:
    return html.escape(str(s))


# ---------------------------------------------------------------- 连接层
@st.cache_resource
def _registry() -> dict:
    return {}


def _ws_url(base: str, thread_id: str) -> str:
    base = base.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):] + f"/ws/{thread_id}"
    if base.startswith("http://"):
        return "ws://" + base[len("http://"):] + f"/ws/{thread_id}"
    return f"ws://{base}/ws/{thread_id}"


def connect_ws(base: str, thread_id: str) -> dict:
    reg = _registry()
    conn = reg.get(thread_id)
    if conn and conn.get("alive"):
        return conn

    q: queue.Queue = queue.Queue()
    conn = {"q": q, "alive": True, "error": None, "url": _ws_url(base, thread_id)}
    reg[thread_id] = conn

    def on_message(_ws, raw):
        try:
            q.put(json.loads(raw))
        except Exception:
            q.put({"type": "error", "message": f"无法解析事件: {raw[:200]}"})

    def on_error(_ws, err):
        conn["error"] = str(err)
        q.put({"type": "error", "message": f"WebSocket 错误: {err}"})

    def on_close(_ws, *_a):
        conn["alive"] = False

    app = websocket.WebSocketApp(
        conn["url"], on_message=on_message, on_error=on_error, on_close=on_close,
    )
    conn["ws"] = app
    t = threading.Thread(target=app.run_forever, kwargs={"ping_interval": 20}, daemon=True)
    conn["thread"] = t
    t.start()
    return conn


def disconnect_ws(thread_id: str):
    conn = _registry().get(thread_id)
    if not conn:
        return
    conn["alive"] = False
    try:
        conn["ws"].close()
    except Exception:
        pass


# ---------------------------------------------------------------- HTTP 层
def _headers() -> dict:
    token = st.session_state.get("api_token", "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def api(method: str, path: str, **kw):
    base = st.session_state["backend"].rstrip("/")
    kw.setdefault("timeout", 30)
    try:
        resp = requests.request(method, base + path, headers=_headers(), **kw)
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(
            f"连不上后端 {base}。请先在另一个终端跑：\n"
            f"uvicorn app.main:create_app --factory --reload --port 8000\n\n{e}"
        ) from e
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code} · {method} {path}\n{resp.text[:600]}")
    if resp.content:
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}
    return {}


# ---------------------------------------------------------------- 状态
def _init_state():
    ss = st.session_state
    ss.setdefault("backend", "http://localhost:8000")
    ss.setdefault("api_token", "")
    ss.setdefault("thread_id", f"ui-{uuid.uuid4().hex[:8]}")
    # thread_id 会被「新对话」按钮改写，不能直接当 widget 的 key
    # （Streamlit 禁止改写已实例化 widget 的 key）。用 nonce 换一个新 widget。
    ss.setdefault("tid_nonce", 0)
    ss.setdefault("asked", "")
    ss.setdefault("todos", [])          # Agent 推上来的计划
    ss.setdefault("timeline", [])       # 折叠区里的工作过程
    ss.setdefault("running", None)      # 当前正在跑的工具
    ss.setdefault("stream_text", "")
    ss.setdefault("final_answer", "")
    ss.setdefault("pending_interrupt", None)
    ss.setdefault("task_state", "idle")
    ss.setdefault("started_at", 0.0)
    ss.setdefault("finished_at", 0.0)   # 结束时刻，冻结耗时用
    ss.setdefault("last_error", "")
    ss.setdefault("event_count", 0)


_init_state()


def _reset_run():
    st.session_state.update(
        todos=[], timeline=[], running=None, stream_text="", final_answer="",
        pending_interrupt=None, last_error="", event_count=0, finished_at=0.0,
    )


def drain_events() -> bool:
    """后台线程 → session_state。只能在主线程调。

    返回值：本批事件里有没有「需要整页重绘」的。

    ★★ 为什么需要这个返回值（踩过的坑）：
    render_live 跑在 st.fragment 里，每 0.5 秒自动重跑。fragment 重跑**只重绘
    它自己那一块**，主脚本正文不会重新执行。而审批卡片、交付文档区都写在正文里。
    结果就是：interrupt 事件收到了、pending_interrupt 也写进 session_state 了，
    但界面上那张审批卡片永远不出现——任务已经停在中断点，不会再有新事件，
    也就没有任何东西能触发整页重跑。表现为「后端日志说在等审批，前端一直转圈」。
    所以这类事件必须让 fragment 主动喊一次 st.rerun(scope="app")。
    """
    conn = _registry().get(st.session_state["thread_id"])
    if not conn:
        return False
    ss = st.session_state
    q: queue.Queue = conn["q"]
    needs_full_rerun = False

    while True:
        try:
            ev = q.get_nowait()
        except queue.Empty:
            break

        etype = ev.get("type")
        data = ev.get("data") or {}
        ss["event_count"] += 1

        if etype == "token":
            ss["stream_text"] += ev.get("message", "")

        elif etype == "plan_update":
            todos = data.get("todos")
            if isinstance(todos, list) and todos:
                ss["todos"] = todos

        elif etype == "tool_start":
            name = data.get("tool", "?")
            icon, label = tool_label(name)
            ss["running"] = {"tool": name, "icon": icon, "label": label, "since": time.time()}
            ss["timeline"].append({
                "icon": icon, "label": label, "tool": name,
                "detail": _brief_args(data.get("args")), "elapsed": None,
            })

        elif etype == "tool_end":
            ss["running"] = None
            ms = data.get("elapsed_ms")
            for step in reversed(ss["timeline"]):
                if step["tool"] == data.get("tool") and step["elapsed"] is None:
                    step["elapsed"] = ms
                    break

        elif etype == "tool_error":
            name = data.get("tool", "?")
            icon, label = tool_label(name)
            if data.get("final"):
                ss["running"] = None
                ss["timeline"].append({
                    "icon": "❌", "label": f"{label} 失败", "tool": name,
                    "detail": esc(data.get("error", "")), "elapsed": None,
                })
            else:
                attempt = data.get("attempt", 1)
                ss["running"] = {
                    "tool": name, "icon": "🔁",
                    "label": f"{label} 失败，第 {attempt} 次重试中",
                    "since": time.time(),
                }
                ss["timeline"].append({
                    "icon": "🔁", "label": f"{label} 第 {attempt} 次重试", "tool": name,
                    "detail": esc(data.get("error", "")), "elapsed": None,
                })

        elif etype == "subagent_call":
            ss["timeline"].append({
                "icon": "🤝", "label": ev.get("message", "子 Agent 工作"),
                "tool": "subagent", "detail": "", "elapsed": None,
            })

        elif etype == "interrupt":
            ss["running"] = None
            ss["pending_interrupt"] = data
            ss["task_state"] = "waiting_approval"
            needs_full_rerun = True      # ★ 审批卡片在主脚本正文里，必须整页重绘

        elif etype == "task_result":
            # TaskService 开跑时也会发一条 task_result（没有 data），要区分开
            if "final" in data:
                ss["final_answer"] = data.get("final") or ""
                ss["running"] = None
                ss["task_state"] = "done"
                ss["finished_at"] = time.time()      # ★ 冻结耗时，否则页面开着就一直涨
                needs_full_rerun = True  # ★ 交付文档区也在正文里

        elif etype == "error":
            ss["running"] = None
            ss["task_state"] = "error"
            ss["last_error"] = ev.get("message", "未知错误")
            needs_full_rerun = True

    return needs_full_rerun


def _brief_args(args) -> str:
    if not isinstance(args, dict) or not args:
        return ""
    for key in ("query", "description", "sql", "keyword", "file_path", "content"):
        if key in args and args[key]:
            text = str(args[key]).replace("\n", " ").strip()
            return esc(text[:80] + ("…" if len(text) > 80 else ""))
    text = json.dumps(args, ensure_ascii=False)
    return esc(text[:80] + ("…" if len(text) > 80 else ""))


# ---------------------------------------------------------------- 自检
def self_check() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    base = st.session_state["backend"].rstrip("/")
    tid = st.session_state["thread_id"]
    try:
        r = requests.get(base + "/openapi.json", timeout=8)
        out.append(("后端可达", r.status_code < 500, f"GET /openapi.json → {r.status_code}"))
    except Exception as e:
        out.append(("后端可达", False,
                    f"连不上 {base}：{e}\n👉 另开终端：uvicorn app.main:create_app --factory --reload --port 8000"))
        return out
    try:
        r = requests.get(base + f"/task/{tid}", headers=_headers(), timeout=8)
        ok = r.status_code != 401
        out.append(("API Token", ok,
                    "401 未授权：.env 配了 API_TOKEN，请把同样的值填进侧边栏。" if not ok
                    else f"GET /task/{tid} → {r.status_code} {r.text[:100]}"))
    except Exception as e:
        out.append(("API Token", False, str(e)))
    try:
        ws = websocket.create_connection(_ws_url(base, "healthcheck-" + tid), timeout=8)
        ws.close()
        out.append(("WebSocket", True, "握手成功"))
    except Exception as e:
        out.append(("WebSocket", False, str(e)))
    return out


# ---------------------------------------------------------------- 侧边栏（设置都收这儿）
with st.sidebar:
    st.markdown("#### 设置")
    st.text_input("后端地址", key="backend")
    st.text_input("API Token", key="api_token", type="password",
                  help=".env 里没配 API_TOKEN 就留空")
    _tid_key = f"tid_input_{st.session_state['tid_nonce']}"

    def _on_tid_change():
        value = str(st.session_state.get(_tid_key, "")).strip()
        if value:
            st.session_state["thread_id"] = value

    st.text_input("会话号", value=st.session_state["thread_id"],
                  key=_tid_key, on_change=_on_tid_change)

    conn = _registry().get(st.session_state["thread_id"])
    st.caption(f"事件流：{'🟢 已连接' if conn and conn.get('alive') else '⚪ 未连接'}")

    if st.button("＋ 新对话", **W()):
        disconnect_ws(st.session_state["thread_id"])
        st.session_state["thread_id"] = f"ui-{uuid.uuid4().hex[:8]}"
        st.session_state["tid_nonce"] += 1   # 换 key，生成一个新的输入框
        st.session_state["asked"] = ""
        st.session_state["task_state"] = "idle"
        _reset_run()
        st.rerun()

    if st.button("⏹ 取消当前任务", **W()):
        try:
            r = api("DELETE", f"/task/{st.session_state['thread_id']}")
            st.session_state["task_state"] = r.get("state", "cancelled")
        except Exception as e:
            st.session_state["last_error"] = str(e)
        st.rerun()

    st.divider()
    if st.button("🩺 一键自检", **W()):
        with st.spinner("检查中…"):
            for name, ok, detail in self_check():
                (st.success if ok else st.error)(f"{name}：{'通过' if ok else '失败'}")
                st.code(detail)


# ---------------------------------------------------------------- 页面
st.markdown('<div class="ds-title">DeepSearch Pro</div>', unsafe_allow_html=True)
st.markdown(
    f'<div class="ds-sub">医药行业多 Agent 深度调研 · 会话 {esc(st.session_state["thread_id"])}</div>',
    unsafe_allow_html=True,
)

if st.session_state["last_error"]:
    st.error(st.session_state["last_error"])

if not st.session_state["asked"]:
    st.markdown(
        '<div class="ds-card" style="text-align:center;padding:2.4rem 1rem;">'
        '<div style="font-size:1.05rem;color:#1F1E1D;margin-bottom:.4rem;">今天想调研什么？</div>'
        '<div style="font-size:.85rem;color:#7A776F;">'
        '在下面输入需求，Agent 会自己拆解成任务清单并实时推给你</div></div>',
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f'<div class="ds-ask"><span class="lbl">你的需求</span>{esc(st.session_state["asked"])}</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------- 实时区
def render_plan(todos: list[dict], finished: bool = False):
    done = sum(1 for t in todos if t.get("status") == "completed")
    rows = []
    for t in todos:
        status = t.get("status", "pending")
        if finished and status != "completed":
            mark, cls = TODO_MARK_STALE      # 任务已结束，这项没标完 → 用 ⊘ 而不是转圈的 ◐
        else:
            mark, cls = TODO_MARK.get(status, ("○", "wait"))
        rows.append(
            f'<div class="ds-todo {cls}"><span class="mark">{mark}</span>'
            f'<span class="txt">{esc(t.get("content", ""))}</span></div>'
        )
    title = f"任务清单 · {done}/{len(todos)}"
    if finished and done < len(todos):
        title += "（⊘ = 任务已结束但 Agent 没标记完成）"
    st.markdown(
        f'<div class="ds-card"><h4>{title}</h4>{"".join(rows)}</div>',
        unsafe_allow_html=True,
    )


def render_live():
    needs_full_rerun = drain_events()
    ss = st.session_state

    # ★ fragment 内的整页重绘请求：必须在画完自己之前发出，
    #   否则这一帧画的内容马上会被整页重绘覆盖，白画一次。
    #   scope="app" 是关键——默认的 st.rerun() 在 fragment 里只重跑 fragment 自己，
    #   等于什么都没解决。
    if needs_full_rerun and _FRAGMENT is not None:
        st.rerun(scope="app")

    # 1) Agent 推上来的任务清单
    if ss["todos"]:
        render_plan(ss["todos"], finished=ss["task_state"] == "done")
    elif ss["task_state"] in ("running", "waiting_approval"):
        st.markdown('<div class="ds-card"><h4>任务清单</h4>'
                    '<div class="ds-todo wait"><span class="mark">◌</span>'
                    '<span class="txt">Agent 正在拆解任务…</span></div></div>',
                    unsafe_allow_html=True)

    # 2) 一行实时状态
    running = ss["running"]
    if running:
        el = time.time() - running["since"]
        st.markdown(
            f'<div class="ds-live"><span class="dot"></span>'
            f'<span>{running["icon"]} {esc(running["label"])}</span>'
            f'<span class="el">{el:.1f}s</span></div>',
            unsafe_allow_html=True,
        )
    elif ss["task_state"] == "running":
        st.markdown('<div class="ds-live"><span class="dot"></span><span>🤔 思考中…</span></div>',
                    unsafe_allow_html=True)
    elif ss["task_state"] == "done" and ss["started_at"]:
        end = ss["finished_at"] or time.time()
        st.markdown(
            f'<div class="ds-done">✓ 已完成 · {len(ss["timeline"])} 步 · '
            f'耗时 {end - ss["started_at"]:.0f}s</div>',
            unsafe_allow_html=True,
        )

    # 3) 工作过程（默认折叠）
    if ss["timeline"]:
        with st.expander(f"工作过程（{len(ss['timeline'])} 步）", expanded=False):
            for step in ss["timeline"]:
                el = f'<span class="el"> · {step["elapsed"] / 1000:.1f}s</span>' if step["elapsed"] else ""
                detail = f' — {step["detail"]}' if step["detail"] else ""
                st.markdown(
                    f'<div class="ds-step">{step["icon"]} <b>{esc(step["label"])}</b>{detail}{el}</div>',
                    unsafe_allow_html=True,
                )

    # 4) 最终结果（只在结束后出现）
    if ss["task_state"] == "done":
        answer = (ss["final_answer"] or "").strip()
        with st.container(border=True):
            st.markdown("###### 调研结果")
            if answer:
                st.markdown(answer)
            else:
                st.warning(
                    "任务已结束，但没取到最终文字回答。"
                    "常见原因：主 Agent 最后一轮只调了工具没说话，"
                    "或计划没跑完就收尾了。展开上面的「工作过程」看它做到哪一步。"
                )
                if ss["stream_text"].strip():
                    with st.expander("模型原始输出（兜底）", expanded=False):
                        st.markdown(ss["stream_text"])

        # 计划没做完就结束，是个值得注意的信号
        undone = [t for t in ss["todos"] if t.get("status") != "completed"]
        if ss["todos"] and undone:
            st.caption(
                f"{len(undone)}/{len(ss['todos'])} 项未标记完成（清单里显示为 ⊘）。"
                "更新 todos 需要额外一轮模型调用，Agent 答完后常常省掉这一步——"
                "不代表这些事没做。"
            )


if _FRAGMENT is not None:
    _FRAGMENT(run_every=0.5)(render_live)()
else:
    render_live()
    if st.button("🔄 刷新", **W()):
        st.rerun()


# ---------------------------------------------------------------- 交付文档
def fetch_files() -> list[dict]:
    """列出本会话生成的交付物。失败就返回空，不打扰主流程。"""
    try:
        r = api("GET", "/files/list", params={"thread_id": st.session_state["thread_id"]})
        return r.get("files") or []
    except Exception:
        return []


def render_documents():
    """展示 generate_markdown 生成的报告：页面内预览 + 下载 + 打开链接。

    注意 /files/download 现在返回的是文件本体（FileResponse）。
    原来它只返回 {"path": "服务端本地路径"}，前端拿不到内容，下载按钮做不出来。
    """
    files = fetch_files()
    if not files:
        return

    docs = [f for f in files if f["name"].lower().endswith((".md", ".txt"))]
    others = [f for f in files if f not in docs]
    if not docs and not others:
        return

    base = st.session_state["backend"].rstrip("/")
    tid = st.session_state["thread_id"]

    with st.container(border=True):
        st.markdown("###### 交付文档")

        if docs:
            names = [f'{f["name"]}（{f["size"] / 1024:.1f} KB）' for f in docs]
            idx = 0
            if len(docs) > 1:
                picked = st.selectbox("选择文档", names, index=0, label_visibility="collapsed")
                idx = names.index(picked)
            doc = docs[idx]

            # 直接在页面里渲染 markdown
            text = ""
            try:
                r = api("GET", "/files/content",
                        params={"thread_id": tid, "filename": doc["name"]})
                text = r.get("text", "")
            except Exception as e:
                st.warning(f"预览失败：{e}")

            c1, c2 = st.columns([1, 1])
            with c1:
                if text:
                    st.download_button(
                        "⬇ 下载", data=text.encode("utf-8"),
                        file_name=doc["name"], mime="text/markdown", **W(),
                    )
            with c2:
                # 新标签页打开后端的下载接口。带 token 时链接里不便附带鉴权头，
                # 所以只在没配 API_TOKEN 时给这个链接。
                url = f"{base}/files/download?thread_id={tid}&filename={doc['name']}"
                if st.session_state.get("api_token", "").strip():
                    st.caption("配了 API Token，请用左边的下载按钮")
                else:
                    st.markdown(f'<a href="{url}" target="_blank">↗ 新窗口打开</a>',
                                unsafe_allow_html=True)

            if text:
                with st.expander(f"预览 {doc['name']}", expanded=True):
                    st.markdown(text)

        if others:
            st.caption("其他文件：" + "、".join(f["name"] for f in others))


if st.session_state["task_state"] in ("done", "error", "waiting_approval"):
    render_documents()


# ---------------------------------------------------------------- 调整计划（折叠）
if st.session_state["todos"]:
    with st.expander("调整任务清单", expanded=False):
        st.caption("改完点下面的按钮写回 checkpoint，Agent 下一步读到的就是改过的计划。")
        edited = st.data_editor(
            st.session_state["todos"], num_rows="dynamic", key="todo_editor",
            column_config={
                "content": st.column_config.TextColumn("任务内容", width="large", required=True),
                "status": st.column_config.SelectboxColumn("状态", options=STATUS_OPTIONS, default="pending"),
            },
            **W(),
        )
        if st.button("写回 Agent", type="primary", **W()):
            clean = [
                {"content": str(r.get("content", "")).strip(), "status": r.get("status") or "pending"}
                for r in edited if str(r.get("content", "")).strip()
            ]
            try:
                api("PUT", f"/task/{st.session_state['thread_id']}/todos", json={"todos": clean})
                st.session_state["todos"] = clean
                st.toast("计划已写回", icon="✅")
            except Exception as e:
                st.session_state["last_error"] = str(e)
            st.rerun()


# ---------------------------------------------------------------- 人工审批
itr = st.session_state.get("pending_interrupt")
if itr:
    # ★★ 可能同时挂起多个中断（主 Agent 一轮派了多个子 Agent，各自停在审批点）。
    #    后端事件里的 interrupts 是完整列表，每项带 id；
    #    提交时必须按 id 分别给决策，否则 LangGraph 报
    #    "you must specify the interrupt id when resuming"。
    groups = itr.get("interrupts")
    if not groups:                       # 兼容老格式：顶层只有一份 action_requests
        groups = [{"id": None, "action_requests": itr.get("action_requests") or []}]

    multi = len(groups) > 1
    title = f"需要你确认（{len(groups)} 项待审批）" if multi else "需要你确认"
    st.markdown(f'<div class="ds-card"><h4>{title}</h4></div>', unsafe_allow_html=True)

    by_id: dict = {}                     # {中断id: [决策, ...]}
    flat: list = []                      # 单中断时用的扁平列表

    for gi, group in enumerate(groups):
        iid = group.get("id")
        reqs = group.get("action_requests") or []
        decisions = []

        for i, req in enumerate(reqs):
            key = f"{gi}_{i}"            # ★ widget key 必须带上组号，多组时不能只用 i，否则冲突
            with st.container(border=True):
                if multi:
                    st.caption(f"第 {gi + 1} 项")
                st.markdown(f"**{req.get('name', '?')}**")
                if desc := req.get("description"):
                    st.caption(desc)     # 显示「为什么被拦下来」，人才判断得了该不该批
                st.code(json.dumps(req.get("args", {}), ensure_ascii=False, indent=2), language="json")
                choice = st.radio("决定", ["approve", "edit", "reject"], horizontal=True,
                                  key=f"dec_{key}", label_visibility="collapsed")
                if choice == "edit":
                    raw = st.text_area("修改后的参数（JSON）",
                                       value=json.dumps(req.get("args", {}), ensure_ascii=False, indent=2),
                                       key=f"args_{key}", height=120)
                    try:
                        decisions.append({"type": "edit", "args": json.loads(raw)})
                    except json.JSONDecodeError:
                        st.error("JSON 格式不对")
                        decisions.append({"type": "reject", "message": "参数 JSON 非法"})
                elif choice == "reject":
                    decisions.append({"type": "reject",
                                      "message": st.text_input("拒绝理由", value="人工拒绝",
                                                               key=f"msg_{key}")})
                else:
                    decisions.append({"type": "approve"})

        if iid:
            by_id[iid] = decisions
        flat.extend(decisions)

    # 有 id 就按 id 提交（多中断唯一可行的方式），拿不到 id 才退回扁平列表
    payload = by_id if by_id else flat

    if st.button("提交决策并继续", type="primary", **W()):
        try:
            api("POST", f"/task/{st.session_state['thread_id']}/decision", json=payload)
            st.session_state["pending_interrupt"] = None
            st.session_state["task_state"] = "running"
        except Exception as e:
            st.session_state["last_error"] = str(e)
        st.rerun()


# ---------------------------------------------------------------- 输入框（底部）
prompt = st.chat_input("描述你的调研需求，例如：分析近三个月布洛芬的采购价格趋势…")
if prompt:
    if st.session_state["asked"]:
        # 同一 thread_id 提交第二个任务：checkpoint 里带着上一轮的全部消息历史，
        # 输入 token 会从几千起步，而且 Agent 可能被上一个话题带偏。
        # 想干净测试请点侧边栏「＋ 新对话」。
        st.toast("同一会话内再次提交，上一轮的上下文会被带上", icon="⚠️")
    _reset_run()
    st.session_state["asked"] = prompt
    st.session_state["task_state"] = "running"
    st.session_state["started_at"] = time.time()
    st.session_state["finished_at"] = 0.0
    # 先连 WebSocket 再提交，避免漏掉最开头的事件。
    # ★ 同一个会话跑第二个任务时，上一次的连接可能已经失效（后端旧版本会在任务
    #   结束时 drop 掉订阅者）。这里主动探测一次，不活就重连，别指望它还在。
    conn = _registry().get(st.session_state["thread_id"])
    if not (conn and conn.get("alive")):
        disconnect_ws(st.session_state["thread_id"])
        _registry().pop(st.session_state["thread_id"], None)
    connect_ws(st.session_state["backend"], st.session_state["thread_id"])
    time.sleep(0.6)
    try:
        r = api("POST", "/task",
                params={"query": prompt, "thread_id": st.session_state["thread_id"]})
        st.session_state["task_state"] = r.get("state", "running")
    except Exception as e:
        st.session_state["last_error"] = str(e)
        st.session_state["task_state"] = "error"
    st.rerun()
