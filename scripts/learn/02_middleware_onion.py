"""学习脚本 02 —— 中间件的洋葱结构，以及顺序为什么要紧

    python scripts/learn/02_middleware_onion.py           # 纯 Python 演示，不花钱不联网
    python scripts/learn/02_middleware_onion.py --real    # 再跑一遍真实的 create_agent（会调模型）

分三部分：

  A1  用 30 行纯 Python 把「洋葱嵌套」演示出来，看清 wrap 类 hook 的执行顺序
  A2  同样纯 Python，把「SQL 守卫放在重试外面 vs 里面」两种顺序各跑一遍，
      数一数守卫被触发了几次 —— 这就是 Phase 2 计划里那个结论的实证
  B   真实的 create_agent + 三个自定义中间件，打印全部 6 个 hook 的真实顺序
      （需要 .env 里的 LLM_MODEL / LLM_BASE_URL / LLM_API_KEY）
"""

from __future__ import annotations

import sys

# ======================================================================
# A1. 洋葱嵌套 —— 纯 Python，零依赖
# ======================================================================
# 中间件的 wrap 类 hook（wrap_model_call / wrap_tool_call）本质就是这个结构：
# 每一层拿到 request 和一个 handler，自己决定什么时候调 handler、调几次、调不调。


def demo_onion() -> None:
    print("=" * 68)
    print("A1. 洋葱嵌套：middleware=[A, B, C] 到底谁包着谁")
    print("=" * 68)

    def make_layer(name: str):
        def layer(request, handler):
            print(f"      进入 {name}")
            result = handler(request)  # ← 调下一层
            print(f"      离开 {name}")
            return result

        return layer

    def core(request):
        print("      >>> 真正干活：调模型 / 执行工具")
        return "结果"

    layers = [make_layer("A 观测"), make_layer("B 预算"), make_layer("C 守卫")]

    # 关键的一行：从最里面往外包。所以列表里第一个（A）最终在最外层。
    handler = core
    for layer in reversed(layers):
        handler = (lambda inner, lyr: lambda req: lyr(req, inner))(handler, layer)

    handler("一个请求")

    print()
    print("  记住这个形状：进入 A → 进入 B → 进入 C → 干活 → 离开 C → 离开 B → 离开 A")
    print("  middleware 列表里越靠前 = 越在外层 = 越先进入、越后离开。")
    print("  推论：观测中间件要放第一个，才能量到「含重试在内」的真实耗时。")
    print()


# ======================================================================
# A2. 顺序为什么要紧 —— 守卫 vs 重试
# ======================================================================
class Rejected(Exception):
    """模拟 SQL 安全校验不通过。"""


def demo_order_matters() -> None:
    print("=" * 68)
    print("A2. 同样两个中间件，只换顺序，结果差多少")
    print("=" * 68)

    counter = {"guard": 0, "core": 0}

    def guard(request, handler):
        """SQL 守卫：非法语句直接抛错，绝不放进去执行。"""
        counter["guard"] += 1
        if "DROP" in request.upper():
            raise Rejected(f"非法 SQL：{request}")
        return handler(request)

    def retry(request, handler):
        """重试：失败了就退避重试，最多 3 次。"""
        last = None
        for i in range(1, 4):
            try:
                return handler(request)
            except Exception as e:
                last = e
                print(f"        [重试层] 第 {i} 次失败（{type(e).__name__}），退避后再试")
        raise last

    def core(request):
        counter["core"] += 1
        return "查询成功"

    def compose(layers):
        handler = core
        for layer in reversed(layers):
            handler = (lambda inner, lyr: lambda req: lyr(req, inner))(handler, layer)
        return handler

    sql = "DROP TABLE drugs"

    for title, layers in [
        ("错的顺序  middleware=[retry, guard]   守卫在里面", [retry, guard]),
        ("对的顺序  middleware=[guard, retry]   守卫在外面", [guard, retry]),
    ]:
        counter["guard"] = counter["core"] = 0
        print(f"  {title}")
        try:
            compose(layers)(sql)
        except Rejected as e:
            print(f"        最终抛出：{e}")
        print(f"        >>> 守卫被触发 {counter['guard']} 次，工具体被进入 {counter['core']} 次")
        print()

    print("  结论：守卫必须在重试外层。放里面的话，一条 DROP 会产生 3 条重复安全告警，")
    print("  还白等了 1+2 秒退避 —— 而这条 SQL 无论重试几次都不可能变合法。")
    print("  同理：只重试 ConnectionError / TimeoutError 这类瞬时故障，")
    print("  ValueError（输入不合法）重试是纯浪费。")
    print()


# ======================================================================
# B. 真实的 create_agent —— 打印全部 6 个 hook 的执行顺序
# ======================================================================
def demo_real_agent() -> None:
    import os

    from dotenv import load_dotenv
    from langchain.agents import create_agent
    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.tools import tool

    load_dotenv()

    print("=" * 68)
    print("B. 真实的 create_agent：6 个 hook 的执行顺序")
    print("=" * 68)

    class TraceMiddleware(AgentMiddleware):
        """什么都不干，只把每个 hook 的进出打印出来。

        节点式 hook（before_* / after_*）—— 顺序执行
        包裹式 hook（wrap_*）           —— 嵌套执行
        """

        def __init__(self, name: str):
            super().__init__()
            self.name = name

        def before_agent(self, state, runtime):
            print(f"  before_agent      {self.name}")
            return None

        def before_model(self, state, runtime):
            print(f"    before_model    {self.name}")
            return None

        def wrap_model_call(self, request, handler):
            print(f"      进入 wrap_model_call  {self.name}")
            response = handler(request)
            print(f"      离开 wrap_model_call  {self.name}")
            return response

        def wrap_tool_call(self, request, handler):
            print(f"      进入 wrap_tool_call   {self.name}  tool={request.tool_call['name']}")
            result = handler(request)
            print(f"      离开 wrap_tool_call   {self.name}")
            return result

        def after_model(self, state, runtime):
            print(f"    after_model     {self.name}")
            return None

        def after_agent(self, state, runtime):
            print(f"  after_agent       {self.name}")
            return None

    @tool
    def get_stock(drug_name: str) -> str:
        """查询指定药品的库存数量。"""
        print(f"        >>> 工具真正执行了：get_stock({drug_name})")
        return f"{drug_name} 当前库存 320 盒"

    missing = [k for k in ("LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY") if not os.getenv(k)]
    if missing:
        print(f"  跳过：.env 里缺少 {', '.join(missing)}")
        return

    from langchain.chat_models import init_chat_model

    model = init_chat_model(
        model=os.environ["LLM_MODEL"],
        model_provider="openai",
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        timeout=60,
    )

    agent = create_agent(
        model=model,
        tools=[get_stock],
        middleware=[TraceMiddleware("A"), TraceMiddleware("B"), TraceMiddleware("C")],
    )

    agent.invoke({"messages": [{"role": "user", "content": "布洛芬还有多少库存？用工具查一下。"}]})

    print()
    print("  对着上面的输出核对这三条规则：")
    print("    before_*  正序 A → B → C")
    print("    after_*   倒序 C → B → A")
    print("    wrap_*    嵌套 进A → 进B → 进C → 干活 → 离C → 离B → 离A")
    print()
    print("  你项目里三个自研中间件的位置就是按这个推出来的：")
    print("    观测   放最外层 → 才能量到含重试的真实耗时")
    print("    SQL 守卫 放重试外层 → 非法语句拦 1 次而不是 3 次")
    print("    预算   放所有重试外层 → 钱花完了就别再重试烧钱了")


def main() -> None:
    demo_onion()
    demo_order_matters()

    if "--real" in sys.argv:
        demo_real_agent()
    else:
        print("=" * 68)
        print("上面两段不花一分钱。想看真实 create_agent 的 hook 顺序，加 --real 再跑一次：")
        print("    python scripts/learn/02_middleware_onion.py --real")
        print("=" * 68)


if __name__ == "__main__":
    main()
