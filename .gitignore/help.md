--------------------------------------------------------------------------
                                文件操作
--------------------------------------------------------------------------
from pathlib import Path
Path(__file__).resolve()是什么意思把路径中的相对引用（..、.）和符号链接解析成真实的绝对路径。
__file__ 是 Python 内置变量，代表"当前这个 .py 文件自己在哪
file: UploadFile = File(...) 传入单个文件，（……）代表必填
files: List[UploadFile] = File(...) 就是传入多个文件
thread_id: str = Form(...)   FastAPI这个参数从表单的普通字段里取
target_dir.mkdir(parents=True, exist_ok=True)      parents=True：自动创建所有缺失的父目录。
file.read() 会把整个文件一次性读进内存。 数据过大时容易爆炸
shutil.copyfileobj 流式复制，安全
Path() 是把一个普通字符串变成路径对象，这样才能用 .resolve()、.is_relative_to() 这些方法。
a.is_relative_to() 就是检查"A是不是在B目录下"
FileResponse(abs_path, filename=abs_path.name)  从哪里读取，保存为什么名字
abs_path.glob("*.txt")      # 第一层所有 .txt 文件
abs_path.rglob("*.txt")     # 所有层所有 .txt 文件
abs_path.iterdir()           # 第一层所有文件和目录（不支持通配符）
abs_path.rglob("**/*.pdf")  # 所有层所有 .pdf 文件（跟 rglob("*.pdf") 等效）


--------------------------------------------------------------------------
                                FastAPI
--------------------------------------------------------------------------
# GET + 普通参数 → 自动走URL 简单
# POST + BaseModel → 自动走JSON  中等
# POST + Form() → 强制走表单  复杂

add_middleware：是给FastAPI添加中间件
CORSMiddleware — 跨域控制（这个项目用的）
TrustedHostMiddleware — 限制允许访问的域名，防Host头攻击
GZipMiddleware — 自动压缩响应体，减少传输大小
HTTPSRedirectMiddleware — 强制HTTP跳转到HTTPS
SessionMiddleware — 管理用户session/cookie

asyncio.create_task(run_deep_agent(request.query, thread_id))
asyncio.create_task() — 把一个异步任务丢进事件循环后台执行
run_deep_agent agent的主函数，负责整个agent的编排流程

await websocket.receive_text()   # 阻塞等待，直到前端发来消息

--------------------------------------------------------------------------
                                其他
--------------------------------------------------------------------------
yaml.safe_load(f) 把 YAML 文件的内容转成 Python 字典