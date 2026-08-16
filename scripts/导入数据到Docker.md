# 把 init_pharma_db.sql 导入 Docker 里的 MySQL

Windows 环境。全程在 PowerShell 或 CMD 里操作，项目根目录 `D:\deep_search_pro-main`。

---

## 0. 先确认容器在跑

```powershell
docker ps
```

找到你的 MySQL 容器名（CONTAINER NAME 那一列），下面统一用 `mysql` 代替，你换成自己的。

如果列表里没有，说明容器停了，先启动：

```powershell
docker ps -a          # 看所有容器，包括停掉的
docker start mysql    # 换成你的容器名
```

如果压根没建过 MySQL 容器，用这条建一个（密码换成你 `.env` 里 `MYSQL_PASSWORD` 的值）：

```powershell
docker run -d --name mysql `
  -e MYSQL_ROOT_PASSWORD=你的密码 `
  -p 3306:3306 `
  mysql:8.0 `
  --character-set-server=utf8mb4 `
  --collation-server=utf8mb4_unicode_ci
```

> `--character-set-server=utf8mb4` 别省。MySQL 8 默认已经是 utf8mb4，但显式写上，
> 换成 5.7 镜像时不至于中文全变问号。

---

## 1. 把 SQL 文件拷进容器

```powershell
docker cp D:\deep_search_pro-main\scripts\init_pharma_db.sql mysql:/tmp/init.sql
```

**为什么不直接用 `<` 重定向？**

网上常见的写法是这样：

```bash
docker exec -i mysql mysql -uroot -p密码 < init_pharma_db.sql    # ❌ Windows 上别用
```

在 Linux/Mac 上没问题，但在 Windows 上有两个坑：

1. **PowerShell 根本不支持 `<`**，会直接报 `“<”运算符是为将来使用而保留的`
2. 就算用 CMD 或 `Get-Content | ...` 绕过去，PowerShell 管道会按系统默认编码
   （中文 Windows 是 GBK）重新编码文本，**这个 55 万字符的中文 SQL 会整个乱码**，
   导进去全是问号

`docker cp` 是二进制拷贝，不碰编码，最稳。

---

## 2. 在容器里执行导入

```powershell
docker exec -i mysql mysql -uroot -p你的密码 --default-character-set=utf8mb4 -e "source /tmp/init.sql"
```

`--default-character-set=utf8mb4` 同样别省，它决定客户端和服务端之间用什么编码通信。

**执行时间**：5800 条销售记录，大概 3～10 秒。脚本里已经加了
`SET autocommit=0` + `SET unique_checks=0`，是批量导入的标准提速手段——
不然 5800 条会被拆成 5800 个事务，慢十倍以上。

密码里如果有特殊字符（`!` `$` `&` 之类），用双引号包起来：`-p"你的密码"`。

如果嫌命令行带密码不安全，可以省掉 `-p` 后面的值，回车后会提示你输入：

```powershell
docker exec -it mysql mysql -uroot -p --default-character-set=utf8mb4 -e "source /tmp/init.sql"
```

---

## 3. 验证

脚本末尾自带三条自检查询，执行完会直接打印出来。你应该看到：

```
表      行数
药品    111
库存    344
销售    5799

最早         最晚         总笔数   总金额万元
2025-08-01  2026-08-10   5799     36023.6
```

再单独确认一次中文没乱码：

```powershell
docker exec -it mysql mysql -uroot -p --default-character-set=utf8mb4 pharma_db -e "SELECT generic_name, brand_name, therapeutic_area FROM drugs LIMIT 5;"
```

看到「布洛芬缓释胶囊 / 芬必得 / 解热镇痛」这种就对了。**如果是 `???` 或者方块，
说明编码没设对**，回到第 2 步检查 `--default-character-set=utf8mb4` 有没有加。

---

## 4. ★ 别忘了删缓存

```powershell
del D:\deep_search_pro-main\data\schema_cache.json
```

你的 `schema_cache.py` 会把表结构缓存到磁盘，有效期 24 小时。**不删的话，
Agent 读到的还是旧结构**（这次建表加了字段注释，注释会一起喂给模型帮它写 SQL，
旧缓存里没有）。

删掉之后下次任务会自动重新探测，只花一条毫秒级的 SQL。

---

## 5. 重启后端，试一句

```powershell
uvicorn app.main:create_app --factory --reload --port 8000
```

然后在前端问：

> 分析近三个月布洛芬的销售情况

这次应该能查到数据了——布洛芬类（缓释胶囊 / 混悬液 / 片）在 2026-05-11 之后有 32 条记录。

---

## 常见问题

**`Access denied for user 'root'`**
密码不对。`.env` 里的 `MYSQL_PASSWORD` 和容器启动时设的 `MYSQL_ROOT_PASSWORD` 必须一致。

**`Can't connect to MySQL server on 'localhost'`（后端报的）**
容器端口没映射出来。`docker ps` 看 PORTS 那列，必须有 `0.0.0.0:3306->3306/tcp`。
没有的话得删容器重建，加上 `-p 3306:3306`。

**`ERROR 2006 (HY000): MySQL server has gone away`**
单条 INSERT 太大超过了 `max_allowed_packet`。脚本已经把每条 INSERT 控制在
400 行以内（约 40KB），远低于默认的 64MB，正常不会碰到。真遇到就加参数重建容器：
`--max-allowed-packet=128M`。

**想重新导一次**
直接重跑第 2 步就行。脚本开头有 `DROP TABLE IF EXISTS`，会先清干净再建，
不会出现重复数据。

---

## 这批数据能问出什么

数据不是纯随机生成的，刻意埋了几条分析线索，方便你测 Agent 的分析能力：

| 问题 | 数据里的设计 |
|---|---|
| 「哪些药在冬天卖得最好？」 | 呼吸/抗病毒/中成药有明显冬季峰值，抗病毒类 12 月销量是 6 月的 20 倍 |
| 「有没有药品价格明显下降？」 | 约 18% 的品种自 2026-01 起进集采，单价直接砍到 65%（如布洛芬片从 9.3 元降到 6.1 元） |
| 「哪些批次快过期了？」 | 10 个已过期批次 + 20 个 90 天内到期批次 |
| 「各区域销售分布如何？」 | 7 大区，华东/华北客户数最多 |
| 「销售额 TOP10 是哪些药？」 | 销量分三档（畅销/普通/长尾），符合真实的长尾分布 |
| 「同比增长如何？」 | 覆盖 2025-08 ~ 2026-08 完整 12 个月，可做同比环比 |
