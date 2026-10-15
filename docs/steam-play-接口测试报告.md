# Steam 游玩情况报告工具 —— 接口测试报告

- **被测对象**：`V:\Software\WorkBench\Wx-work\steam-play\`（Python 3.10 纯标准库后端 + 零依赖前端）
- **测试方式**：整目录复制到临时目录后在副本上跑，原目录**只读、未改动任何文件**
- **测试日期**：本轮会话（时间戳基准 1791272xxx，与本机 system clock 一致）
- **结论摘要**：**不建议**以当前状态交付给"会被并发访问/会被手工改配置"的场景。功能路径基本可用、路径穿越与 Key 保护做得很扎实，但**写盘路径没有任何并发保护**（实测 200 次并发写 → 101 次 500、94 次静默丢写、用户原有记录被抹掉），以及**manual.json 读坏时会被静默清空覆盖**，这两条属于会真实吃掉用户数据的缺陷。

---

## 一、环境下发生了什么

### 1.1 副本与端口

| 项目 | 值 |
| --- | --- |
| 原目录（只读，未改） | `V:\Software\WorkBench\Wx-work\steam-play\` |
| 测试副本 | `C:\Users\Yellow 灿\AppData\Local\Temp\steam-play-test\`（`Copy-Item -Recurse -Force` 复制） |
| 主服务启动命令 | `cd C:\Users\Yellow 灿\AppData\Local\Temp\steam-play-test; python app.py --no-browser --port 8899` |
| 容错组（每次新进程） | `python app.py --no-browser --port 8901`（工作目录同上） |
| 用到的端口 | **8899**、**8901** |
| 8770（用户正在用） | **全程未碰**，实测 `Get-NetTCPConnection -LocalPort 8770` 显示已被占用 |
| Python | 3.10.7（PATH 上的 `python`），无 node/npm |
| HTTP 客户端 | 自己写的 `http.client` 封装（`...\Temp\sptest\client.py`），**未使用 curl** |
| 服务健康检查 | `GET /api/health` → `200 {"ok": true, "steam_root": "d:\\steam"}` |

测试脚手架目录 `C:\Users\Yellow 灿\AppData\Local\Temp\sptest\`，共 9 个脚本：

| 脚本 | 覆盖内容 |
| --- | --- |
| `t01_baseline.py` | 基线：config/data/静态头/Key 是否泄漏/缓存 TTL |
| `t02_get_params.py` | GET 参数边界（非法 appid、成就与图片的 GET 分支） |
| `t03_manual_post.py` | `POST /api/manual` 全边界（30 条） |
| `t04_images.py` | `POST /api/images` 全边界：格式/大小/文件名清洗/同名/op/appid |
| `t05_static_traversal.py` | 静态文件、路径穿越、HTTP 方法、图片名 URL 编码回取、`image_count` 与缓存失效 |
| `t06_concurrency.py` / `t06b_race.py` | 并发写 manual.json / images，抓 500 报错、丢更新、半截文件观察 |
| `t07_faulty_files.py` | config.json / manual.json 被弄坏后能否启动（端口 8901） |
| `t08_config_post.py` | `POST /api/config` 全边界 + 假 Key 联网错误路径 |
| `t09_cfg_mem_disk.py`、`t10_params_ach.py`、`t11_teardown.py` | 内存/磁盘配置覆盖、vanity 错误路径、缓存约定、noach 约定、收尾复位 |

### 1.2 测试数据保护

- 副本里的 `manual.json`（14 条真实记录）、`config.json` 在开测前先备份为 `*.ORIG-BACKUP`。
- 测试过程中 `manual.json` 被并发用例破坏过（见缺陷 P0-1），收尾时已从备份复位为原 14 条；
- `config.json` 在各组用例后按原值复位，最终磁盘值 = `{"api_key":"4E78…（原 32 位，未改动）","steamid":"76561199232537961","online":true}`，`GET /api/config` 与之一致。
- 自己造的测试图片目录 `web/images/0`、`web/images/777200`、`web/images/777300`、`web/images/108600` 已全部删除 —— **原目录和副本原本都没有 `web/images` 这个目录**（`app.py:180-184 _img_dir(create=True)` 在首次上传图片时才创建），副本 `web/` 已回到与原目录完全一致的三文件状态（`app.js` / `index.html` / `style.css`）。
- 原目录从未被写入，收尾复核：`manual.json` 仍是 14 条、`config.json` 的 api_key 仍是原 32 位（`4E78…`）、`web/app.js` 仍是 42875 字节（与副本一致）、`web/` 下没有多出任何文件。

### 1.3 对真实 Steam API 的消耗（刻意压到最低）

| 触发点 | 请求 | 次数 |
| --- | --- | --- |
| 服务启动（副本 config 里 online=true） | `GetOwnedGames` | 1 |
| `GET /api/achievements?appid=99999999&force=1`（不存在但合法的 appid） | `GetPlayerAchievements` | 2（第二次仍是 force，验证 force 会绕过本地记录） |
| `POST /api/config {"steamid":"zzz_not_exist_9x8y7"}` | `ResolveVanityURL` | 1 |
| 假 Key 场景（`0`×32） | `GetOwnedGames` | 2（401 / 未配置分支） |

合计约 6 次，其余全部走本地缓存、本地记录或错误分支。

---

## 二、测试用例表

> 说明：结论列的 ✅ = 符合预期，⚠️ = 行为可解释但不理想，❌ = 不符合预期/有缺陷（对应第三章编号）。

### 2.1 基线 / 缓存 / 配置读取

| 用例 | 输入 | 期望 | 实际 | 结论 |
| --- | --- | --- | --- | --- |
| 配置视图 | `GET /api/config` | 打码回传，不含完整 Key | `200 {"online":true,"steamid":"76561199232537961","key_set":true,"key_hint":"4E78…8D87","configured":true}` | ✅（全响应比对：整串 Key **未**出现） |
| 健康检查 | `GET /api/health` | 200 | `200 {"ok": true, "steam_root": "d:\\steam"}` | ✅ |
| 带无关查询参数 | `GET /api/health?x=1` | 200 | `200 {"ok": true, ...}` | ✅ |
| 全量数据 | `GET /api/data` | 108 款游戏 | `200`，`games=108`，`elapsed_ms=94`，`online:{enabled,ok:true,persona:"emo小心~",game_count:90,matched:68,added:22}` | ✅ |
| 60 秒 TTL（命中） | 连续两次 `GET /api/data` | 第二次 `cached:true` | `cached:true` | ✅ |
| 60 秒 TTL（绕过） | `GET /api/data?force=1` | `cached:false` | `cached:false` | ✅ |
| **enrich 不读不写缓存** | `force=1` → `enrich=1&force=1` → 默认 | 三者都 `cached:false`，之后默认仍是 force 写的那份 | `默认=True force=False enrich+force=False 再默认=True` | ✅（与代码 `app.py:333`、`:341` 一致） |
| account 不存在 | `GET /api/data?account=__nope__` | 报错或空 | `200`，**静默回退到 `1272272233`**（无任何提示） | ⚠️ 见 3.12 |
| account 空 | `GET /api/data?account=` | 用默认账号 | `200`，`elapsed_ms=101` | ✅ |
| force 空/0 | `?force=`、`?force=0` | 不强制 | 均返回缓存数据 | ✅ |
| 图片增删后缓存失效 | 加图前后 `GET /api/data` | 缓存被清、`image_count` 立刻更新 | 加图后 `cached=False image_count=1`；删图后 `cached=False image_count=0` | ✅ |

### 2.2 非法与极端参数（GET）

| 用例 | 输入 | 期望 | 实际 | 结论 |
| --- | --- | --- | --- | --- |
| 图片接口不传 appid | `GET /api/images` | 400 | `400 {"ok":false,"error":"appid 不对"}` | ✅ |
| 空值 | `/api/images?`、`?appid=`、`?appid=%20` | 400 | 均 `400 appid 不对` | ✅ |
| 非数字 | `?appid=abc`、`?appid=1e3`、`?appid=1.5` | 400 | 均 `400 appid 不对` | ✅ |
| 负数 | `?appid=-1` | 400 | `400 appid 不对` | ✅ |
| 前导零 | `?appid=007` | 400 或按 7 处理 | `200 {"appid": 7}`（与 7 同键；7 是 `NON_GAME_IDS` 里的 Steam 客户端） | ⚠️ 见 3.4 |
| 零 | `?appid=0` | 400（0 不是游戏） | `200`，且返回了此前用例建出的 `images/0/zero.png` | ❌ 3.4 |
| 超大数字 | `?appid=99999999999999999999`（20 位） | 400 | `200 {"appid": 99999999999999999999}` | ❌ 3.4 |
| **Unicode 数字** | `?appid=²`（%C2%B2，上标 2） | 400 | **连接被直接关闭，无任何响应**：`RemoteDisconnected: Remote end closed connection without response`；服务端 `ValueError: invalid literal for int() with base 10: '\xb2'`（`app.py:517` / `app.py:482`） | ❌ **3.3** |
| 全角数字 | `?appid=%EF%BC%91`（全角１） | 400 | `200 {"appid": 1}`（被接受并归一） | ⚠️ 见 3.3 |
| 重复参数 | `?appid=108600&appid=2` | 取第一个或报错 | `200 {"appid": 108600}`（取第一个） | ✅ |
| 成就接口不传/非法 | `/api/achievements`、`?appid=`、`?appid=-7`、`?appid=abc` | 400 | 均 `400 appid 不对` | ✅ |
| 无 Key 时读成就 | 清空 api_key 后 `GET /api/achievements` | 可读错误 | `400 {"error":"要先连上 Steam 账号（填 API Key + SteamID）才能读成就。"}` | ✅ |

### 2.3 `POST /api/manual`（30 条，节选关键项）

| 用例 | 输入 | 期望 | 实际 | 结论 |
| --- | --- | --- | --- | --- |
| 只传 appid（新） | `{"appid":"777001"}` | 不产生记录或明确报错 | `200 {"manual": null}`，文件里无此键 | ✅ |
| 只传 appid（已有） | `{"appid":"1237970"}` | 不动记录 | `200`，记录内容不变但 `at` 从 `1791271185` 被刷成 `1791272321` | ❌ 3.12（等于给成就缓存续期） |
| ach>ach_total | `{"appid":"777002","ach":12,"ach_total":8}` | 夹到 12/12 | `{"ach":12,"ach_total":12}` | ✅ |
| ach_total=0 | `{"appid":"777003","ach":10,"ach_total":0}` | 夹取/报错 | 存成 `10/0`（夹取条件要求 total 为真值，`app.py:163`） | ⚠️ 3.12 |
| ach 负数 | `{"appid":"777004","ach":-5}` | 400 或夹到 0 | `200 {"manual": null}`（静默不写） | ⚠️ 3.12 |
| ach 字符串数字 | `{"ach":"12","ach_total":"30"}` | 转成数字 | `{"ach":12,"ach_total":30}` | ✅ |
| ach 垃圾 | `{"ach":"abc"}` | 400 | `200 {"manual": null}` | ⚠️ 3.12 |
| ach 浮点 | `{"ach":1.9,"ach_total":3}` | 取整 | 存成 `1`（截断，非四舍五入） | ⚠️ 3.12 |
| ach 布尔 | `{"ach":true,"ach_total":3}` | — | 存成 `1` | ⚠️ 3.12 |
| done 字符串 | `{"appid":"777009","done":"false"}` | 视为 false 或报错 | `200`，存成 `"done": true` | ❌ 3.12 |
| done=0 | `{"appid":"777010","done":0}` | false | 不产生记录 | ✅ |
| **clear 与其它字段同传** | `{"appid":"1237970","clear":true,"done":true,"ach":99}` | clear 优先 | 记录被删除，其余字段忽略 | ✅ |
| **clear 字符串 "0"** | `{"appid":"777005","clear":"0"}` | 视为不清除 | **记录被删除** | ❌ **3.11** |
| clear=false | `{"appid":"777005","clear":false,"done":true}` | 正常更新 | 正常更新 | ✅ |
| appid=0 | `{"appid":"0","done":true}` | 400 | `200`，`manual.json` 里出现 `"0"` 键 | ❌ 3.4 |
| appid 20 位 | `{"appid":"99999999999999999999","done":true}` | 400 | `200`，原样落盘 | ❌ 3.4 |
| **appid='²'** | `{"appid":"²","done":true}` | 400 | **无响应**（连接关闭），traceback：`app.py:563 → app.py:140 str(int(appid))` | ❌ **3.3** |
| source 超长 | `source` = 100 个 `S` | 拒绝或保留 | 静默截断成 `"SSSSSSSSSSSS"`（12 字符） | ⚠️ 3.12 |
| body 非 JSON | `{not json` | 400 | `400 {"error":"请求格式不对：Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"}` | ✅（但回吐内部异常文本） |
| body 空 | `Content-Length: 0` | 400 | `400 {"error":"appid 不对"}` | ✅ |
| body 数组 / null / 字符串 | `[1,2,3]` / `null` / `"hi"` | 400 | 均 `400 {"error":"请求格式不对：body 必须是 JSON 对象"}` | ✅ |
| body 空对象 | `{}` | 400 | `400 {"error":"appid 不对"}` | ✅ |
| body 非法 UTF-8 | `{"appid":"\xff\xfe"}` | 400 | `400 {"error":"请求格式不对：'utf-8' codec can't decode byte 0xff in position 10: invalid start byte"}` | ✅ |
| **超大 body（伪造 CL）** | `Content-Length: 41MB`，实发 10 字节 | 413 | `413 {"error":"这次传的东西太大了（上限 40 MB）"}` | ✅ |
| **超大 body（真 41MB）** | 真发 41MB | 413 | **`ConnectionAbortedError: [WinError 10053] 你的主机中的软件中止了一个已建立的连接。`** —— 413 到不了客户端 | ❌ **3.9** |
| Content-Length 非数字 | `Content-Length: abc` | 400 | `400 {"error":"请求格式不对：invalid literal for int() with base 10: 'abc'"}` | ✅ |
| Content-Length 负数 | `Content-Length: -5` | 400/无挂死 | `400 {"error":"请求格式不对：read length must be non-negative or -1"}`（未挂死） | ✅ |
| chunked 上传 | `Transfer-Encoding: chunked` 无 CL | 支持或明确报错 | `400 {"error":"appid 不对"}`（按 0 长度处理，body 被忽略） | ⚠️ 3.12 |

### 2.4 `POST /api/images`

| 用例 | 输入 | 期望 | 实际 | 结论 |
| --- | --- | --- | --- | --- |
| 正常添加 | 1×1 PNG，`name:"up.png"` | 200 + 文件落盘 | `200`，`web/images/<aid>/up.png` 出现 | ✅ |
| data 非 data URL | `"hello"` | 400 | `400 {"error":"图片数据格式不认识（应该是 data:image/…;base64,…）"}` | ✅ |
| 非 image/ 前缀 | `data:text/plain;base64,…` | 400 | 同上 400 | ✅ |
| 缺 data 字段 | 只有 appid/name | 400 | 同上 400 | ✅ |
| 非 base64 字符 | `…;base64,!!!!` | 400 | `400 {"error":"这是一张空图"}`（`validate=False` 把非法字符丢掉后为空，文案会误导） | ⚠️ 3.12 |
| base64 长度非法 | `…;base64,AAAAA` | 400 | `400 {"error":"图片数据解不开，可能传到一半断了"}` | ✅ |
| **合法 base64 但非图片** | `…;base64,` + `aGVsbG8gd29ybGQ=`（"hello world"） | 400 | `200`，落盘 `fake.png`，内容确为 `hello world`，`GET` 时 `Content-Type: image/png` | ❌ **3.10** |
| 非法扩展名 | `data:image/svg+xml;…` | 400 | `400 {"error":"先不支持 .svg+xml 这个格式，转成 png / jpg / webp / gif 再传"}` | ✅ |
| 扩展名大写 | `image/PNG` | 归一 | `200`，落成 `up.png` | ✅ |
| jpeg 归一 | `image/jpeg` | 落成 `.jpg` | `200`，`j.jpg` | ✅ |
| 带 charset | `image/png;charset=utf-8;base64,` | 宽容或 400 | `400 格式不认识`（浏览器 FileReader 不会产出这种串，实际无影响） | ⚠️ |
| **危险名 `../escape.png`** | — | 落在 appid 目录内 | `200`，落成 `escape.png`；`web\escape.png`、副本根 `escape.png` **均不存在** | ✅ 穿越被挡住 |
| 危险名 `a\b.png` | — | 同上 | 落成 `b.png` | ✅ |
| 名字 `.hidden` | — | 400 或改名 | `200`，静默落成 **`image.png`** | ❌ 3.7 |
| 名字 `..` | — | 400 | 静默落成 `image.png` | ❌ 3.7 |
| 名字 `a:b?.png` | — | 400 或清洗 | 静默落成 `image.png` | ❌ 3.7 |
| 名字 130 字符 | — | 400 或截断 | 静默落成 `image.png` | ❌ 3.7 |
| 不传 name | — | 400 或兜底 | 静默落成 `image.png` | ⚠️ 3.7 |
| **名字 `screenshot.2024`** | — | 保留原名 | 落成 **`screenshot.png`**（`.2024` 被当扩展名剥掉） | ❌ 3.7 |
| 中文+空格名 | `"中文 名字.png"` | 正常存取 | `200`；`GET /images/<aid>/%E4%B8%AD%E6%96%87%20%E5%90%8D%E5%AD%97.png` → `200 len=70 CT=image/png` | ✅ |
| Windows 保留名 | `con.png` / `nul.png` | 报错或改写 | `200`，本机 C: 上真的建出了同名文件 | ✅（环境相关） |
| 纯数字名 | `"123"` | 补扩展名 | 落成 `123.png` | ✅ |
| 同名重复 ×3 | `dup.png` | `dup.png / dup-1.png / dup-2.png` | 完全符合 | ✅ |
| **正好 12MB** | 12×1024×1024 字节 | 允许 | `200`，落盘 `exact12.png` | ✅ |
| **12MB+1 字节** | — | 400 | `400 {"error":"单张图上限 12 MB，这张有 12.0 MB"}` | ✅（文案四舍五入有点唬人） |
| op 未知 | `op:"move"` | 400 | `400 {"error":"不认识的 op：move"}` | ✅ |
| op 缺失 | 无 op | 默认 add | `200`，按 add 处理 | ✅ |
| del 不存在 | `op:"del","name":"nope.png"` | 400 | `400 {"error":"找不到这张图（可能已经删过了）"}` | ✅ |
| del 不传 name | `{"op":"del"}` | 400 | `400 {"error":"文件名不对"}` | ✅ |
| **del 穿越** | `op:"del","name":"../../config.json"` | 400，不能删到外面 | `400 找不到这张图`；`config.json` 完好 | ✅ |
| del 正常 | `op:"del","name":"fake.png"` | 200，文件消失 | `200`，目录里 `fake.png` 消失 | ✅ |
| appid 缺失 / 非数字 | 无 appid / `"abc"` | 400 | 均 `400 {"error":"appid 不对"}` | ✅ |
| appid=0 | `{"appid":"0",...}` | 400 | `200`，并在 `web/images/0/` 建出文件 | ❌ 3.4 |
| **appid='²'** | — | 400 | `400 {"error":"invalid literal for int() with base 10: '²'"}`（未崩，但把内部异常文本回吐） | ⚠️ 3.3 |
| 取回静态图片 | `GET /images/777200/fake.png` | 200 | `200 len=11 CT=image/png CC=no-store, max-age=0` | ✅ |

### 2.5 静态文件、路径穿越、HTTP 方法

| 用例 | 输入 | 期望 | 实际 | 结论 |
| --- | --- | --- | --- | --- |
| 首页 | `GET /` | 200 + `no-store` | `200 len=4712`，`Cache-Control: no-store, max-age=0` | ✅ |
| JS / CSS | `GET /app.js`、`/style.css` | 200 + `no-store` | `200 len=42875` / `200`，均带 `no-store, max-age=0` | ✅ |
| 带 `./` 与 `%2e` | `/./app.js`、`/%2e/app.js` | 200 | 均 200 | ✅ |
| 不存在 | `/nope.js`、`/favicon.ico`、`/web/app.js`、`/api/unknown` | 404 | 均 404 | ✅ |
| **源码不可访问** | `GET /app.py` | 404 | `404` | ✅ |
| **穿越（上跳）** | `/../app.py`、`/..%2fapp.py`、`/%2e%2e/app.py` | 404 | 均 404 | ✅ |
| **穿越（拿配置文件）** | `/../config.json`、`/../manual.json`、`/../cache/appinfo.json` | 404 | 均 404 | ✅ |
| **穿越（多级）** | `/images/../../config.json` | 404 | `404` | ✅ |
| 反斜杠穿越 | `/..\app.py`、`/images/..%5c..%5cconfig.json` | 不泄露 | 均 `301`（重定向），**未读到内容** | ✅ |
| 绝对路径 | `/C:/Windows/win.ini` | 404 | `404` | ✅ |
| 双斜杠 | `//app.py` | 404 | `404` | ✅ |
| 目录列表 | `GET /images/` | 可接受 | `200`，列出目录（`SimpleHTTPRequestHandler` 默认行为） | ⚠️ 3.12 |
| 方法：HEAD | `HEAD /api/health`、`HEAD /api/manual` | 200 | `404`（`do_HEAD` 未覆写，走静态逻辑） | ⚠️ 3.12 |
| 方法：其它 | `PUT/DELETE/OPTIONS/PATCH /api/health` | 501/405 | 均 `501`（标准库默认） | ✅ |
| 请求头容错 | `Connection: close`、空 `Host` | 可用 | 均 `200` | ✅ |
| 错误响应也带 no-store | 404/400/413 | `no-store` | `end_headers` 无条件添加（`app.py:425-427`） | ✅ |

### 2.6 并发

| 用例 | 输入 | 期望 | 实际 | 结论 |
| --- | --- | --- | --- | --- |
| **8 线程 × 25 个不同 appid 写标记** | 200 次 `POST /api/manual` | 200 全成功且全部落盘 | **响应码 `{200: 99, 500: 101}`**；文件里只查到 **5 / 200** 个新 appid；**94 个返回 200 的请求其实没写进去**；跑完 `manual.json` 由 22 条塌成 **6 条**（用户原有记录被抹） | ❌ **P0-1** |
| 失败报文样本 | — | — | `500 {"error":"写不进 manual.json：[WinError 2] 系统找不到指定的文件。: '...\\manual.json.tmp' -> '...\\manual.json'"}`、`[WinError 5] 拒绝访问`、`[Errno 13] Permission denied: '...\\manual.json.tmp'` | — |
| 同 appid 并发写 200 次 | 每条不同 ach | 无 500、无破损 | `非200响应=110`，最终值 `{"ach":195,...}`（最后一个写者） | ❌ P0-1 |
| 并发期间被读坏？ | 另一线程每 2ms 读一次 `manual.json` | 不能读到半截 | `解析失败 0 次 / 读到空文件 0 次 / 成功读到 72 次` | ✅（`os.replace` 对读者原子） |
| 40 张不同名并发加图 | 8 线程 | 40 个文件 | `非200=0`，落盘 40 个 | ✅ |
| **30 次同名并发加图** | 10 线程全部 `race.png` | 30 个文件或明确失败 | 全部 200，但**只落盘 19 个**（`race.png`…`race-18.png`），11 张被静默覆盖 | ❌ **3.8** |
| 混合并发 | `/api/data?force=1` × 12 + 写标记 × 6 | 全 200 | `{200: 16, 500: 2}` | ❌ P0-1 |

### 2.7 容错（config.json / manual.json 被弄坏，每次新进程 8901 端口）

| 用例 | 输入 | 期望 | 实际 | 结论 |
| --- | --- | --- | --- | --- |
| A 非法 JSON | `config.json = "{oops"` | 能启动 + 可读提示 | 进程存活，`200 {"online":false,...,"configured":false}`，日志 `!! config.json 读不了（Expecting property name enclosed in double quotes: line 1 column 2 (char 1)），按未配置处理` | ✅ |
| B 空文件 | `""` | 同上 | 同上，提示 `Expecting value: line 1 column 1 (char 0)` | ✅ |
| C 删除 | 文件不存在 | 同上 | 同上（无提示，符合预期） | ✅ |
| D 只有 `{}` | `{}` | 同上 | 同上 | ✅ |
| E 类型错（数组） | `[1,2]` | 同上 | 同上（`app.py:59 isinstance` 挡住） | ✅ |
| F 布尔类型坑 | `{"online":"false","api_key":"0"×32,...}` | `online` 应为 false | `200 {"online": true, ...}`，服务**真的联网**，`/api/data` 返回 `{"online":{"enabled":true,"ok":false,"error":"API Key 无效（Steam 返回 401）..."}}` | ❌ **3.5** |
| G manual.json 非法 | `'{"108600": {"done": true},  <<<< 坏掉了'` | 启动成功但**必须提示/拒写** | 启动正常；`GET /api/data` → `200`，`manual` 汇总全 0（`saved_count:0`），`108600` 的 `done` 变 `False`，**无任何用户可见提示**；随后一次 `POST /api/manual` 把文件重写成只剩 1 条（**14 条真实标记丢失**） | ❌ **P0-2** |

### 2.8 `POST /api/config`

| 用例 | 输入 | 期望 | 实际 | 结论 |
| --- | --- | --- | --- | --- |
| 基线与复位 | `GET /api/config` | `4E78…8D87` | 一致，且磁盘/内存均与备份一致 | ✅ |
| **online 字符串** | `{"online":"false"}` / `"0"` / `"no"` | 关闭联网 | `online: true`（并写盘为 `true`） | ❌ **3.5** |
| online 空串/0/false/[]/{} | — | false | 均 `online: false` | ✅ |
| online 1/"true" | — | true | `online: true` | ✅ |
| api_key 纯空白 | `{"api_key":"   "}` | 视为未设置 | `200 key_set:false key_hint:""`，磁盘 `"api_key":""` | ✅ |
| api_key 数字 | `{"api_key":12345678901234567890}` | 400 或按字符串处理 | `200`，磁盘存 `"12345678901234567890"`，`key_hint":"1234…7890"` | ⚠️ 3.12 |
| api_key 数组 | `{"api_key":["a","b"]}` | 400 | `200`，磁盘存 **`"['a', 'b']"`**，`key_set` 仍 true | ❌ 3.12 |
| steamid 数字 | `{"steamid":76561199232537961}` | 存成字符串 | 正确 | ✅ |
| steamid 清空 | `{"steamid":""}` | 清空 | `configured:false` | ✅ |
| steamid 自定义网址名（无 Key） | `{"api_key":"","steamid":"abc"}` | 400 + 提示 | `400 {"error":"填自定义网址名前，得先有 API Key 才能解析。"}` | ✅ |
| steamid 自定义网址名（真 Key） | `{"steamid":"zzz_not_exist_9x8y7"}` | 400 + 可读错误 | `400 {"error":"找不到这个自定义网址名：zzz_not_exist_9x8y7"}` | ✅（消耗 1 次真实请求） |
| 未知字段 | `{"nothing":1}` | 忽略 | `200` 原样返回 | ✅ |
| body 非 JSON | `nope` | 400 | `400 {"error":"请求格式不对：Expecting value: line 1 column 1 (char 0)"}` | ✅ |
| body 空 | `Content-Length: 0` | 400 或 no-op | `200`（no-op）—— 与 `/api/manual` 空 body 返回 400 不一致 | ⚠️ 3.12 |
| body 数组 | `[1]` | 400 | `400 body 必须是 JSON 对象` | ✅ |
| 假 Key + online | `{"api_key":"0"×32,"online":true}` 后 `GET /api/data?online=1` | 可读错误、不 500 | `200`，`{"online":{"enabled":true,"ok":false,"configured":false,"error":"还没有填 SteamID 和 API Key。"}}`，`games=86`（本地部分） | ✅ |
| **内存/磁盘不一致** | 运行中手工把磁盘 api_key 改成 `ABCDEF…`，再 `POST {"online":true}` | 应发现/重读磁盘 | `GET /api/config` 仍返回内存旧值；随后一次普通保存把内存值**写回磁盘**，用户的 `ABCDEF…` 消失 | ❌ **3.6** |
| Key 泄漏扫描 | 以上所有响应 | 不含完整 Key | 整串比对：**未出现** | ✅ |

### 2.9 成就接口与 6 小时缓存约定

| 用例 | 输入 | 期望 | 实际 | 结论 |
| --- | --- | --- | --- | --- |
| 命中本地（noach） | `GET /api/achievements?appid=108600` | 不打网络 | `200 {"ok":true,"none":true,"cached":true,"manual":{...,"noach":true}}` | ✅ |
| 命中本地（有数字） | `?appid=1237970` | 不打网络 | `200 {"achieved":30,"total":50,"cached":true}` | ✅ |
| **400 → noach** | `?appid=99999999&force=1`（真实请求 1 次，0.26s） | 记 noach 并返回 none | `200 {"ok":true,"none":true,"note":"Steam 说这个请求不成立（400）—— 最常见的原因是这款游戏没有成就系统。","manual":{"noach":true,"at":1791272518,"source":"steam"}}`，磁盘写入成功 | ✅ |
| noach 之后不再打网络 | `?appid=99999999`（不带 force） | 走缓存 | `200 {"ok":true,"none":true,"cached":true,...}` | ✅ |
| **force 语义** | `?force=TRUE` | 视为 force | 被忽略（`app.py:481` 只认小写 `1/true/yes`），返回旧缓存 `{"cached":true}` | ⚠️ 3.12 |
| force 绕过本地 | `?appid=99999999&force=1` 第二次 | 仍打网络 | 仍打网络（0.24s，第 2 次真实请求） | ✅ |
| 手填记录不被 steam 覆盖？ | 实测 `source:"steam"` 才会走快路径 | — | `:505` 会用 steam 结果覆盖任意旧值（含手填），符合代码注释但值得确认 | ⚠️ 见 3.12 |

---

## 三、缺陷清单（按严重程度排序）

### P0-1 并发写 `manual.json`：请求大面积 500 + 静默丢更新 + 文件被"最后一个写者"重写

- **现象**
  - 8 线程 × 25 次（200 次）`POST /api/manual`，appid 互不相同：响应码 `{200: 99, 500: 101}`。
  - 文件里只查到 **5/200** 个新 appid；**94 个返回 200 的请求实际没写进去**（静默丢更新）。
  - 同一批用例把 `manual.json` 从 **22 条塌缩成 6 条**——用户已有记录被整体抹掉。
  - 典型 500 报文：`WinError 2 系统找不到指定的文件: 'manual.json.tmp' -> 'manual.json'`、`WinError 5 拒绝访问`、`Errno 13 Permission denied: 'manual.json.tmp'`。
- **复现**
  ```powershell
  cd C:\Users\Yellow 灿\AppData\Local\Temp\sptest
  python t06b_race.py      # 脚本内 8 线程 × 25 个不同 appid
  ```
- **根因定位**
  - `app.py:120-124 save_manual()` 用**固定**临时路径 `MANUAL_PATH + ".tmp"`；两个线程同时写同一 tmp 文件，一方 `os.replace` 后另一方再 replace 就 `WinError 2`；一方正在写/关闭时另一方 replace 就 `WinError 5 / Errno 13`。
  - `app.py:137-175 update_manual()` 是完整的"读—改—写"，**全程无锁**；`app.py:522 do_POST` 走 `ThreadingHTTPServer`，每连接一线程。
  - 全文件只有一把 `_cache_lock`（`app.py:43`），且只保护 `/api/data` 缓存（`:332`、`:553`、`:598`）。
  - `app.py:502`、`:505`（成就回写）与 `:563`（手动保存）都会走这条路径 → **打开详情页自动读成就（`web/app.js:550`）与用户点"保存/标记完成"同时发生就会踩到**，不是纯理论并发。
- **最小修法**：新增一把模块级 `_write_lock = threading.Lock()`，`update_manual()` 整个函数体（load → 改 → save）持锁；`save_manual()` 的临时名改为 `tempfile.mkstemp(dir=BASE_DIR, prefix="manual.", suffix=".tmp")` 并且同样持锁（或至少在 `os.replace` 外不再复用固定名）。图片写盘建议共用同一把锁（见 3.8）。

### P0-2 `manual.json` 读不出来时静默当空，下一次写入直接覆盖原文件（不可恢复）

- **现象**：把 `manual.json` 改成 `{"108600": {"done": true},  <<<< 坏掉了` 后启动：
  - 服务正常起来，`GET /api/data` → `200`，`manual` 汇总 `{"done_count":0,"ach_count":0,...,"saved_count":0}`，`108600` 的 `done` 变成 `False`（前端会显示成"一款都没通关"）；
  - **没有任何用户可见提示**；日志里连 `!! manual.json 读不了` 都没留下（`print` 到被重定向的 stdout，进程结束时缓冲丢失）；
  - 随后一次 `POST /api/manual {"appid":"730","done":true}` → 文件被重写成 `{"730": {...}}`，**原 14 条真实标记永久丢失**（`manual.json` 没有历史备份）。
- **复现**：`python t07_faulty_files.py`（G 用例）。
- **根因定位**：`app.py:108-117 load_manual()` 捕获 `(OSError, ValueError)` 后返回 `{}`，调用方**无法区分"空"与"读坏了"**；`app.py:120-124 save_manual()` 全量覆盖；触发点还有 `app.py:502`、`:505`。
- **最小修法**：`load_manual()` 读失败时抛 `RuntimeError` 或返回 `(dict, err)`；`update_manual()` 在 `err` 非空时**拒绝写入**，`/api/manual` 返回 `500 {"error":"manual.json 读不出来（…），为免覆盖已拒绝写入，请先修好或删除该文件"}`；写入前把现有文件复制成 `manual.json.bak`。

### P1-3 非法 appid（Unicode 数字）直接打死请求线程，客户端拿不到任何 HTTP 响应

- **现象**：`GET /api/images?appid=²`、`GET /api/achievements?appid=²`、`POST /api/manual {"appid":"²"}` → 客户端 `RemoteDisconnected: Remote end closed connection without response`（无状态码、无 body）。服务端 traceback：
  ```
  File "...\steam-play-test\app.py", line 517, in do_GET
      return self._json({"ok": True, "appid": int(appid),
  ValueError: invalid literal for int() with base 10: '\xb2'
  ```
  （另两处：`app.py:482`、`app.py:563` → `app.py:140`）
- **复现**：`python t02_get_params.py` / `t03_manual_post.py`（`appid=²` 行）。
- **根因定位**：守卫用 `str.isdigit()`（`app.py:475`、`:515`、`:539`、`:560`），它对上标 `²³¹`、带圈 `①`、部分全角/其它 Unicode 数字返回 `True`，而这些字符 `int()` 解析不了。`POST /api/images` 之所以没崩，是因为 `app.py:549 except ValueError` 把 `int()` 的 ValueError 当"参数错"吞了 —— 于是把内部异常文本原文回吐：`400 {"error": "invalid literal for int() with base 10: '²'"}`。
- **最小修法**：四处守卫改成 `appid.isascii() and appid.isdigit()`（`int()` 只接受 ASCII 十进制）；并在 `update_manual` / `save_image` 内部对 `int(appid)` 做一次 try，失败就 400 "appid 不对"（不要回吐 `str(e)`）。

### P1-4 不存在的 appid 会被写进 `manual.json`、并能在 `web/images/` 下建目录

- **现象**
  - `POST /api/manual {"appid":"99999999999999999999","done":true}` → `200`，`manual.json` 里出现这个 20 位 key；
  - `POST /api/manual {"appid":"0","done":true}` → `200`，出现 `"0"` 键；
  - `POST /api/images {"appid":"0","name":"zero.png",...}` → `200`，并真的创建了 `web/images/0/zero.png`；
  - `GET /api/images?appid=007` → `200 {"appid": 7}`，与 `7`（`NON_GAME_IDS` 里的 Steam 客户端本体，见 `steam_local.py:496`）同键。
- **复现**：`python t03_manual_post.py`（⑥ 系列）、`python t04_images.py`（⑨c）。
- **根因定位**：`app.py:539-540`、`app.py:559-561` 只做 `isdigit()` 检查；`app.py:137-175 update_manual()` 与 `app.py:238-266 save_image()` 对 appid 无任何存在性/范围校验。
- **最小修法**：校验 `1 <= int(appid) <= 0xFFFFFFFF`，并（更强）要求 appid 出现在 `_local_data()["games"]` 里，否则 400 "不认识这个 appid"。前端 `web/app.js` 已经在正确的 appid 上调用，不受影响。

### P1-5 `online` 开关的类型坑：`"false"` / `"0"` / `"no"` 都是 true

- **现象**：`POST /api/config {"online":"false"}` → `200` 且 `online: true`（`"0"`、`"no"` 同样）；手工把 config.json 写成 `{"online":"false", ...}` 后启动，`GET /api/config` 报 `online: true`，服务真的去联网：`GET /api/data?online=1` → `{"online":{"enabled":true,"ok":false,"error":"API Key 无效（Steam 返回 401）..."}}`。
- **复现**：`python t08_config_post.py`（② 组）、`python t07_faulty_files.py`（F 用例）。
- **根因定位**：`app.py:591 cfg["online"] = bool(payload.get("online"))` 与 `app.py:62 cfg["online"] = bool(raw.get("online") or False)` —— 非空字符串恒为真。
- **最小修法**：加一个 `_truthy(v)`（`v is True or (isinstance(v,str) and v.strip().lower() in ("1","true","yes","on"))` 或 `v in (1,"1","true","yes","on")`），两处都改用它。

### P1-6 运行期间手工改 `config.json` 不生效，且下一次保存会把用户的修改覆盖掉

- **现象**：服务运行中把磁盘 `config.json` 的 `api_key` 手工改成 `ABCDEF…` → `GET /api/config` 仍返回内存旧值（`key_hint:"0000…0000"`）；紧接着一次无害的 `POST /api/config {"online":true}` 就把内存里的旧值写回磁盘，磁盘上的 `ABCDEF…` 消失。
- **复现**：`python t09_cfg_mem_disk.py`（①②）——它同时演示了"内存胜出 + 覆盖磁盘"两步。
- **根因定位**：`app.py:97 CONFIG["_cfg"] = load_config()` 只在启动读一次；`app.py:576 cfg = dict(CONFIG["_cfg"])` → `app.py:593 save_config(cfg)` 每次 POST 全量覆盖磁盘，从不检查磁盘是否被外部改过。
- **最小修法**：`save_config()` 前比对 `os.path.getmtime(CONFIG_PATH)`（与上次读入时记录的值比较），变了就重读并只覆盖本次提交的字段；或在文档/README 里明确"改 config.json 必须重启服务"（成本最低，但建议至少加 mtime 检查以免吞掉用户输入）。

### P2-7 图片名清洗过于激进：非法名静默变 `image.png`，合法名被截断

- **现象**
  - `.hidden`、`..`、`a:b?.png`、130 字符名、以及**不传 name** → 全部静默落成 `image.png`（重复时 `image-1.png`…），接口返回 200，用户看到"我传的图叫 image.png"。
  - `screenshot.2024` → 落成 **`screenshot.png`**（真名字里的 `.2024` 被当扩展名剥掉）。
  - 好的部分：`../escape.png` → 落成 `escape.png`，**没有**写到 `web/` 或副本根（实测两个位置均无文件）；`a\b.png` → `b.png`。穿越确实被挡住了。
- **复现**：`python t04_images.py`（④ 组）。
- **根因定位**：`app.py:187-194 _safe_name()` 用返回 `""` 表示"不合格"，`app.py:256 stem = _safe_name(name) or "image"` 静默兜底；`app.py:257` 的扩展名剥离正则 `re.sub(r"\.[A-Za-z0-9]+$", "", stem)` 对点号结尾的**真名字**也会动手。
- **最小修法**：`_safe_name()` 返回 None 时直接 400（"文件名不能空/不能以点开头/不能含 `..` 和 `\/:*?\"<>|`，请改名"）；兜底名带短随机或时间戳（`image-<ts>.png`），并在响应里回真实落盘名（现在已经在回，够用）；只在 `os.path.splitext(name)[1].lower()` 属于 `IMG_EXT` 时才剥扩展名。

### P2-8 同名图片并发添加互相覆盖

- **现象**：10 线程 × 30 次同名 `race.png` → 全部 200，但只落盘 19 个文件（`race.png`…`race-18.png`），11 张被静默覆盖。
- **复现**：`python t06b_race.py`（D 用例）。
- **根因定位**：`app.py:260-263` 的 `while os.path.exists(dst): stem = base + "-" + i` 与随后的 `open(dst,"wb")` 之间存在竞态（`ThreadingHTTPServer` 多线程）。
- **最小修法**：用 `fd = os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY)` 抢占文件名，`FileExistsError` 就 `i += 1` 重试；或复用 P0-1 引入的写锁。

### P2-9 真实超大 body（>40MB）的 413 客户端收不到，连接被 RST

- **现象**：伪造 `Content-Length: 41MB`（只发 10 字节）→ 干净的 `413 {"ok":false,"error":"这次传的东西太大了（上限 40 MB）"}`；**真发 41MB** → 客户端 `ConnectionAbortedError: [WinError 10053] 你的主机中的软件中止了一个已建立的连接。`（看不到 413）。
- **复现**：`python t03_manual_post.py`（⑨ 与 ⑩ 两条对比）。
- **根因定位**：`app.py:529-530` 只按 `Content-Length` 判断就立即响应并结束请求，**没有把已到达的请求体读掉**；服务端 `close()` 时内核给还在写数据的对端发 RST，响应被丢弃。
- **最小修法**：要回 413 前先 `self.rfile.read(min(length, 4*1024*1024))` 把管道尽量读空（或循环读到 EOF，设总上限），再发响应并 `Connection: close`。前端 `web/app.js:668-694` 也应在 `readAsDataURL(f)` **之前**加一句 12MB 预检，省掉这次注定失败的十几 MB 上传。

### P2-10 图片内容零校验：任意字节都能以 `.png` 存下来并当图片对外提供

- **现象**：`data:image/png;base64,aGVsbG8gd29ybGQ=`（"hello world"）→ `200`，落盘 `fake.png`，前 11 字节确为 `hello world`；`GET /images/777200/fake.png` → `200`，`Content-Type: image/png`。前端 `<img>` 会显示破图，用户不知道为什么。
- **复现**：`python t04_images.py`（②f）。
- **根因定位**：`app.py:238-266 save_image()` 只校验 data URL 前缀（正则）、base64 可解、大小上限，不校验图片魔数。
- **最小修法**：按扩展名校验前若干字节（png `\x89PNG\r\n\x1a\n`、jpg `\xFF\xD8\xFF`、gif `GIF8`、webp `RIFF….WEBP`、bmp `BM`、avif 检查 `ftyp` 品牌），不匹配则 400 "这不是一张 png/jpg 图片"。

### P3-11 `clear` 用真值判断：`"clear": "0"` / `"false"` 会删掉记录

- **现象**：`POST /api/manual {"appid":"777005","clear":"0"}` → `200` 且该 appid 的记录被**删除**（`manual: null`）；`{"clear": false}` 则正常当更新。
- **复现**：`python t03_manual_post.py`（⑤b）。
- **根因定位**：`app.py:142 if payload.get("clear"):`。
- **最小修法**：`if payload.get("clear") is True or str(payload.get("clear", "")).strip().lower() in ("1","true","yes"):`。

### P3-12 其它类型 / 取值 / 一致性小坑（都不崩，但语义与直觉不符）

| # | 现象 | 根因（file:line） | 最小修法 |
| --- | --- | --- | --- |
| a | `done:"false"`（字符串）→ 存成 `true`；`done:0` → 记录被删 | `app.py:147-149` 真值判断 | 用统一 `_truthy()` |
| b | `ach:-5`、`ach:"abc"` → `200 {"manual": null}`（静默不写），调用方分不清"没改"和"参数错" | `app.py:127-134 _int_or_none` | 显式带字段但解析失败时返回 400 |
| c | `ach:1.9` → 存成 `1`（截断）；`ach:true` → `1` | `app.py:131 int(v)` | 限制为整数字符串/整数，浮点拒绝 |
| d | `ach=10, ach_total=0` → 存成 `10/0`，前端会显示 "10 · 0%" | `app.py:163` 夹取条件要求 `ach_total` 为真值 | 条件改成 `is not None` |
| e | `source` 超 12 字符被静默截断（100 个 `S` → `SSSSSSSSSSSS`） | `app.py:167-168`（`str(payload["source"])[:12]`） | 校验长度或直接 400 |
| f | **只传 `{"appid":X}` 会把已有记录的 `at` 刷成当前时间** → 每次打开详情页（`web/app.js:809 await postManual(appid, {})`）都给成就缓存续 6 小时，成就可能长期不刷新 | `app.py:166 cur["at"] = int(time.time())` 无条件执行，`:170-171` 又把已有记录整条写回 | 无字段变更时直接返回 `cur`，不动 `at` |
| g | `POST /api/config` 空 body → 200 no-op，`POST /api/manual` 空 body → 400，不一致 | `app.py:531 if length else {}` | 空 body 统一 400 |
| h | `POST /api/config {"api_key":["a","b"]}` → 存成字符串 `"['a', 'b']"`，`key_set` 仍为 true（UI 以为配好了） | `app.py:578 str(...)` | 只接受 str，否则 400 |
| i | `?force=TRUE`（大写）被忽略，回旧缓存 | `app.py:481 in ("1","true","yes")` | `str.lower()` 后比较 |
| j | `HEAD /api/health` → 404；`GET /images/` → 目录列表 | `do_HEAD` 未覆写 + `app.py:520 super().do_GET()` | 无害；若要严格可显式覆写 `do_HEAD` / 关目录列表 |
| k | 400/413 报文回吐 Python 内部异常文本（`Expecting property name enclosed in double quotes: line 1 column 2 (char 1)`、`invalid literal for int() with base 10: '²'`） | `app.py:535`、`:550` | 只回自己的中文文案，细节写日志 |
| l | `GET /api/health` 回传本机路径 `d:\steam`；`manual.json` 读坏时无任何提示；`account=__nope__` 静默回退默认账号 | `app.py:511`、`:108-117`、`steam_local.py:310-330` | 本机单人场景可接受，若要收紧：账号无效时 400 |

### 做得好、值得保留的部分

- **路径穿越全部挡住**：`/../app.py`、`/..%2fapp.py`、`/%2e%2e/app.py`、`/../config.json`、`/../manual.json`、`/../cache/appinfo.json`、`/images/../../config.json`、`/..\app.py`、`/C:/Windows/win.ini`、`//app.py`、`/web/app.js`、`/app.py` 全部 404 或无内容 301；`/app.py`（源码本身）也不可访问。
- **Key 永不回传**：`/api/config` 只给 `4E78…8D87`，所有配置相关响应做过"整串 Key 是否出现"的比对，结果 **未出现**。
- **所有响应都带 `Cache-Control: no-store, max-age=0`**（`app.py:425-427`），连 400/404/413 与图片都带；`/`、`/app.js`、`/style.css` 实测确认。
- **`config.json` 容错很好**：非法 JSON / 空文件 / 删除 / `{}` / `[1,2]` 五种坏法都能正常启动并回可读默认值，非法 JSON 与空文件还有中文提示。
- **`os.replace` 的读者安全性成立**：并发轰炸期间另一线程每 2ms 读一次，72 次成功读取、0 次解析失败、0 次读到空文件 —— 坏的是写者之间互踩和丢更新，不是文件被写坏。
- **缓存约定与实现一致**：60 秒 TTL、`force` 绕过、`enrich` 既不读也不写缓存、图片增删主动失效 `/api/data`；成就 6 小时 TTL + `noach` 快路径（`app.py:487-490`）实测符合描述，400 只在第一次出现，之后走本地。
- **单张 12MB 边界正确**（正好 12MB 通过、+1 字节拒绝），`data:` 前缀、扩展名白名单、`op` 校验、`del` 不存在的文件都有明确中文报错。

---

## 四、没测到的盲区（明确说明）

1. **前端 UI 层完全没测**：本机没有 node/npm 与浏览器自动化，`web/app.js`（1063 行）只做了静态阅读。多文件上传的交互、成就面板渲染、`image.png` 兜底名的观感、`10/0` 进度条的实际显示、以及"两次快速点击不同按钮"的真实触发概率，都没有在浏览器里验证。
2. **Steam 官方接口的成功/限流路径没测**：只观察了启动那一次在线合并（22 款来自在线）与 4 次错误路径（401/403/400/vanity 404）。429 限流、网络超时（25s 超时边界）、断网、Steam 返回 `success:false` 的成功响应体（非异常）分支、以及 `merge_online` 的字段合并正确性（`matched:68 added:22` 的具体内容）都未验证；这是刻意为了不消耗用户配额。
3. **不能碰真实环境的部分**：运行中删除/破坏 `d:\steam`、`--account` 指向另一个账号（`1845166588`）的实际数据正确性、`--steam-root`/`--enrich` 启动参数组合、注册表探测路径（`steam_local.py:34` 的兜底分支）、`V:\SteamLibrary` 这第二个库文件夹的清单解析，均未测。
4. **磁盘/权限异常**：只读目录、磁盘写满、`manual.json` 被另一进程独占打开等情况下 `POST /api/manual` 的表现未测（仅在并发场景间接拿到 `WinError 5 / Errno 13`）。
5. **网络暴露面**：服务默认 `127.0.0.1`，`--host 0.0.0.0` 之后的行为与风险（无鉴权、能删图片、能改配置）未测，也未测 IPv6 与远端访问。
6. **长期运行**：内存/文件句柄增长（每次 `/api/images` 都 `listdir`、每次写标记都全量扫描一次 Steam 目录）、几百张图片时的 `/api/images` 响应体大小、`web/images/` 单目录文件数上限都未测。
7. **图片相关未覆盖**：**当前 checkout 里根本不存在 `web/images/` 目录**（任务说明里提到的"用户自己加的图片"这次没有真实样本），所以图片接口全部是对我自造的 1×1 PNG 与假文本文件测的；WebP/AVIF/BMP/GIF 的真实解码（只测了扩展名白名单与 base64 通路）、超长文件名接近 120 字符边界的截断行为、图片目录里手工放入怪名文件后 `/api/images` 的渲染、以及 `Content-Type` 是否按扩展名正确映射（只在 PNG 上验证过 `image/png`）也都没测。
8. **`favicon.ico` 404** 属于已知现象，未评估对前端体验的影响。
9. **Windows 保留设备名**（`con.png`/`nul.png`）在本机 C: 盘实测能正常创建，但没在共享盘/网络盘/其它文件系统上复验——这类行为依环境而异。
10. **`config.json` 里的 `steam_root` 字段**：代码里 `CONFIG["steam_root"]`（`app.py:47`）只来自默认值与 `--steam-root`，`load_config()` 并不读 config.json 的该字段 —— 即用户无法通过改 config.json 换 Steam 目录。这是阅读代码得到的结论，未列为缺陷，但也未做端到端验证。

---

## 五、复现入口（脚本与关键命令）

```powershell
# 起服务（副本，8899）
cd C:\Users\Yellow 灿\AppData\Local\Temp\steam-play-test
python app.py --no-browser --port 8899

# 各组用例
cd C:\Users\Yellow 灿\AppData\Local\Temp\sptest
python t01_baseline.py          # 基线 / Key 泄漏 / 静态头
python t02_get_params.py        # GET 参数边界
python t03_manual_post.py       # POST /api/manual（含 413 两种打法）
python t04_images.py            # POST /api/images（含 12MB 边界、文件名清洗）
python t05_static_traversal.py  # 路径穿越 / 方法 / image_count / 编码取图
python t06b_race.py             # 并发：101 次 500、94 次静默丢更新
python t07_faulty_files.py      # 坏 config/manual（自己起 8901）
python t08_config_post.py       # POST /api/config（跑完自动复位 config.json）
python t09_cfg_mem_disk.py      # 内存覆盖磁盘 + vanity 错误路径
python t11_teardown.py          # 收尾：清理测试图片目录、复位 manual.json
```

**建议的修复优先级**：P0-1 → P0-2 → P1-3/P1-5（两天内）→ P1-4/P1-6 → P2 组 → P3 组。
其中 **P0-1 + P0-2 都属于"会吃掉用户手工标记"的数据安全问题**，而 `manual.json` 是这工具里唯一由用户产生的业务数据，建议连同一份"写入前自动备份"一起做掉。
