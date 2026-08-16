# DeepSearch Pro 前端控制台（Streamlit）

## 装依赖

```bash
pip install streamlit requests websocket-client
```

## 启动

两个进程，都要开着：

```bash
# 1) 后端
uvicorn app.main:create_app --factory --reload --host 0.0.0.0 --port 8000

# 2) 前端（项目根目录下执行）
streamlit run web/app.py
```

浏览器打开 http://localhost:8501。

> Streamlit 是独立的 Web 服务，不能由 FastAPI 用 StaticFiles 托管
> （它自己有 Tornado server + 前后端协议）。所以是两个端口。
> 前端的 HTTP 请求和 WebSocket 都是从 Streamlit 服务端进程发出的，
> 因此**不受浏览器 CORS 限制**，`cors_origins` 不用改。

## 用法

1. 侧边栏填后端地址；`.env` 里如果配了 `API_TOKEN`，把同样的值填进 Token 框。
2. 左侧编辑「需求描述」和「待办清单」——清单可以直接在表格里增行、删行、改内容、改状态。
3. 点 **🚀 提交任务**：会先建 WebSocket 再 POST `/task`，所以不会漏掉开头的事件。
4. 右侧实时面板每 0.6 秒自动刷新，显示：
   - Agent 当前的 todos 和完成进度（后端 `plan_update` 事件推的）
   - 模型流式输出
   - 完整事件日志
5. 任务跑到一半觉得计划不对：改左边的表格 → **⬆️ 把清单推给运行中的任务**，
   会调 `PUT /task/{thread_id}/todos` 直接改 checkpoint 里的图状态。
   反向可以用 **⬇️ 拉取 Agent 当前清单** 把 Agent 自己写的计划拉进编辑器。
6. 命中 HITL（比如 `execute_sql_query`）时，左下方出现审批卡片，
   支持 approve / edit / reject，提交后调 `POST /task/{id}/decision` 恢复执行。

## 配套的后端改动

- `app/agents/stream.py`
  - 新增 `plan_update` 事件：扫 `updates` 流里各节点的 `todos` 状态增量，变了就推。
  - 新增 `task_result` 收尾事件，带最终回答全文。
  - 新增 `subagent_call` 事件（按节点名粗判）。
  - `_unpack()` 兼容 `{'type','data'}` 和 LangGraph 原生 `(mode, payload)` 两种 chunk 形态。
- `app/api/routes_task.py`
  - `GET  /task/{thread_id}/todos` — 读图状态里的 todos
  - `PUT  /task/{thread_id}/todos` — 覆盖写 todos（`agent.aupdate_state`），并广播一条 `plan_update`

## 已知坑

- `EventBus.drop()` 在任务结束的 `finally` 里被调用，会清掉该会话的历史缓冲。
  所以任务跑完再连 WebSocket 是看不到历史事件的——先连再提交。
- `PUT /todos` 依赖 checkpointer；该 thread 从没跑过任务时图里没有状态，会返回空清单。
