# Server.py 学习笔记

## 一、这个文件是干什么的

`api/server.py` 是整个项目的**后端入口**，基于 FastAPI 框架构建。它负责接收前端请求、调度 Agent 后台运行、管理文件上传下载、并通过 WebSocket 实时推送 Agent 执行进度。

## 二、技术框架

- **FastAPI**：Python 异步 Web 框架，自动生成 Swagger 文档，原生支持 async/await
- **Uvicorn**：ASGI 服务器，负责启动和运行 FastAPI 应用
- **asyncio**：Python 异步库，提供事件循环、create_task 等异步原语
- **WebSocket**：双向长连接协议，用于实时推送 Agent 进度
- **Pydantic**：数据验证库，用 BaseModel 定义请求体结构

## 三、数据流动全景

```
服务启动
  └─ 创建事件循环 loop → 交给 WebSocket 管理器保存

用户操作（按时间顺序）：
  1. POST /api/task      → 生成 thread_id → 后台启动 Agent → 立即返回 id
  2. WS /ws/{thread_id}  → 建立长连接 → Agent 实时推进度
  3. POST /api/upload     → 带 thread_id 上传文件 → 存到 session 目录
  4. Agent 运行完毕       → 结果写入 output 目录
  5. GET /api/files       → 查看 output 下的文件列表
  6. GET /api/download    → 下载指定文件

thread_id 是贯穿全程的纽带，把所有接口串在一起。
```

## 四、面试 Q&A

### Q1：CORS 是解决什么问题的？不加会怎样？

CORS（跨域资源共享）是**浏览器的安全策略**。当前端页面域名（如 `localhost:3000`）和 API 域名（如 `localhost:8000`）不同时，浏览器会拦截请求。

不加 CORS 中间件 = 服务端没有在响应头里声明"我允许谁来访问" = 浏览器默认拒绝。

注意：Postman、curl、后端服务器调 API 完全不受影响，因为 CORS 是浏览器自己加的规则，不是 HTTP 协议的规则。

中间件加在**服务端**，作用是在响应头里加上 `Access-Control-Allow-Origin` 字段，浏览器看到这个字段才放行。

`allow_origins=["*"]` 表示允许所有域名访问，生产环境应改为具体域名。

---

### Q2：为什么用 get_running_loop() 而不是 new_event_loop()？

因为 uvicorn 启动时已经创建了一个事件循环（循环 A），所有路由、WebSocket 都跑在这个循环里。

如果用 `new_event_loop()` 创建一个新循环（循环 B），它和循环 A 完全隔离。把循环 B 交给 WebSocket 管理器，后台线程往 B 里投递消息，但 WebSocket 连接在 A 里，消息永远送不到。

`get_running_loop()` 拿的就是 uvicorn 正在用的那个循环，确保所有东西在同一个循环里。

---

### Q3：create_task 创建的后台任务报错了，前端能收到吗？

**不能。** 错误会被静默吞掉，控制台只会打一个 warning。

因为 `create_task` 扔到后台就不管了，没人 `await` 它，也就没人接住异常。

解决方案：在 `run_deep_agent` 内部自己 try/except，出错时通过 WebSocket 主动推一条错误消息给前端：

```python
async def run_deep_agent(query, thread_id):
    try:
        # 正常逻辑...
    except Exception as e:
        await manager.send(thread_id, {"type": "error", "message": str(e)})
```

---

### Q4：上传接口为什么用 File(...) 和 Form(...)，不能都用 JSON？

JSON 根本**不能携带二进制数据**。JSON 只能装文本（字符串、数字、布尔值），图片、PDF 是二进制数据，塞不进去。

传文件必须用 `multipart/form-data` 格式（HTTP 规范决定的）。在这种格式下，所有字段都是表单字段，所以 `thread_id` 也只能用 `Form(...)` 接收。

```
JSON：       只能传文字  {"name": "abc", "age": 18}
Form-data：  能传文字 + 二进制文件（图片、PDF、视频等）
```

---

### Q5：下载接口的路径安全检查在防什么？攻击者怎么攻击？

防止**路径穿越攻击（Path Traversal）**。攻击者在 path 参数里用 `..` 往上跳目录：

```
正常请求：GET /api/download?path=output/攻略.txt
恶意请求：GET /api/download?path=output/../../etc/passwd
```

`..` 表示上级目录，连续用就能跳出 output 目录，访问服务器上任意文件。

防御方式：`resolve()` 把 `..` 展开成真实路径，`is_relative_to()` 检查展开后是否还在 output 目录下，不在就拒绝。

---

### Q6：WebSocket 的 while True 循环会不会占满 CPU？

**不会。** 因为循环里有 `await`：

```python
while True:
    data = await websocket.receive_text()  # 挂起，等前端发消息
```

`await` 让函数暂停，交出控制权给事件循环，不消耗 CPU。只有前端发来消息时才会继续执行。

如果写成 `while True: pass`（不带 await），那才会死循环烧 CPU。

**关键：`while True` + `await` = 等待不耗 CPU。`while True` 不带 `await` = 死循环烧 CPU。**

---

### Q7：shutil.copyfileobj 和 file.read() 有什么区别？

`file.read()` 一次性把整个文件读进内存。用户传 500MB 文件就占 500MB 内存。

`shutil.copyfileobj` 流式复制，每次只搬 16KB，内存占用恒定。

```
file.read()：         [=====500MB=====] 全部加载到内存
shutil.copyfileobj：  [16KB][16KB][16KB]... 一块一块搬
```

功能上都能跑通，但大文件场景下 `file.read()` 会撑爆内存。

## 五、关键知识点速查

| 概念 | 说明 |
|------|------|
| `await` | 当前函数暂停等待，事件循环去忙别的，回来后继续 |
| `create_task` | 扔到后台不等，当前函数直接往下走 |
| `resolve()` | 把相对路径转成绝对路径，展开 `..` |
| `is_relative_to()` | 判断路径是否在某个目录下 |
| `rglob("*")` | 递归遍历目录下所有文件（含子目录） |
| `stat()` | 获取文件元信息（大小、修改时间等） |
| `FileResponse` | 把服务器文件作为响应发给客户端，触发下载 |
| `Path(...)` | 把字符串转成路径对象，才能调用路径相关方法 |
| `mkdir(parents=True, exist_ok=True)` | 创建目录，自动建父目录，已存在不报错 |

## 六、FastAPI 参数来源规则

| 来源 | 判断条件 | 示例 |
|------|----------|------|
| 路径参数 | 参数名出现在路由的 `{}` 里 | `@app.get("/ws/{thread_id}")` |
| 查询参数 | 参数名不在路由里，无特殊标注 | `@app.get("/api/download")` → `?path=xxx` |
| 请求体 | 用 `Body()`、`File()`、`Form()` 标注 | `files: List[UploadFile] = File(...)` |
