# Steam 游玩报告 · 代码审查报告

> 由「👁️ 代码审查工程师」专家于本机审查产出，全程只读，未改动任何项目文件。
> 审查范围：`app.py` 673 行 / `steam_local.py` 641 行 / `steam_online.py` 211 行 / `web/app.js` 1052 行 / `web/index.html` 125 行 / `web/style.css` 388 行。

## 一、总体判断

**健康度：良好，明显高于「个人小工具」的平均水平。**

防御性处理是有意为之而非碰巧：acf 逐条 `except Exception: continue`、图片重名不覆盖、manual.json 原子替换、成就 6 小时刹车 + `achBusy` 去重、`state.openId` 守卫防并发弹窗串台、`end_headers` 统一 `no-store`。

自研 VDF 解析器比预期稳（实测截断 + 二进制垃圾不抛异常；内存放大仅 ~8×；真实文件嵌套深度 7 层）。**`appinfo.vdf` 4.6MB 二进制问题不存在 —— 全仓代码从未引用它**（只有 `cache/appinfo.json`，`steam_local.py:89`）。

真正的问题集中在一处：**「写用户数据」这条路径没有并发保护，而它恰好会被自动流程触发。**

## 二、最该修的三件事（全部几行代码）

| # | 问题 | 修法 | 代价 |
|---|---|---|---|
| 1 | manual.json 读-改-写无锁 → 静默丢标记 | `app.py:137` 外包 `threading.Lock()` | 3 行 |
| 2 | 只填「已完成」不填「总数」时手填值被自动读成就覆盖 | `web/app.js:833` 前加 `mark_source` 判断 | 1 行 |
| 3 | 一次 400 就永久写死 `noach`，成功读取也清不掉 | `app.py:501` 去掉 `or "400" in msg`；`app.py:505` 加 `"noach": False` | 2 行 |

---

## 三、严重问题

### 🔴1. manual.json 读-改-写没有任何并发保护，会静默丢掉刚点的标记

- **位置**：`app.py:137-175`（`update_manual`）+ `app.py:120-124`（`save_manual`，固定 tmp 名 `manual.json.tmp`）
- **触发条件**（日常点法就会中）：
  1. 点开某游戏详情 → `openDetail` 自动调 `autoAch()`（`app.js:848`）→ 它会 `POST /api/manual`；
  2. 与此同时点卡片上的「全部游玩」按钮，或点「🔄 重新读取成就」（`app.js:803-816`）；
  3. 服务是 `ThreadingHTTPServer`（`app.py:667`），每请求一线程 —— 两个请求同时落在读-改-写窗口里。
- **实测后果**：2 线程并发 300 次试验 → **36% 抛 `PermissionError`（HTTP 500），64% 两次写都「成功」但只留 1 条记录 = 标记被静默吃掉**。12 线程下最终只剩 2/12 个 key，抛 171 次 `[WinError 32] 另一个程序正在使用此文件…: 'manual.json.tmp' -> 'manual.json'`。**唯一会丢真实数据的缺陷。**
- **最小修法**：

```python
# app.py:43 附近，紧跟 _cache_lock
_manual_lock = threading.Lock()

# app.py:137 —— 整个函数体包进临界区
def update_manual(appid, payload):
    with _manual_lock:                 # ← 只加这一层
        ...                            # 原有 139-175 行原封不动
```
`tmp` 名可顺手改成 `MANUAL_PATH + ".%d.tmp" % threading.get_ident()`，但只要加了锁，固定名也已安全。`save_config` 形状相同，但只由手动点「保存」触发，可不改。

### 🔴2. 只填「已完成」不填「成就总数」的手填记录，会被自动读成就覆盖

- **位置**：`web/app.js:838`（`return true;`）+ `app.py:487-494`（服务端新鲜度判断漏判 `source`）
- **触发条件**：打开游戏 → 成就页 → **只填「已完成」= 12，总数留空** → 保存（发 `{done:false, ach:12, ach_total:'', source:'手填'}`，服务端 `_int_or_none('')` → `None`）→ 记录 `ach_total` 为 null、`source` 为 `手填` → 下次再打开这款游戏 → `needAchFetch` 走到 `830-839`：`if (g.ach_total)` 为假 → 直接落到 838 行 `return true` → 打 `/api/achievements` → `app.py:505-507` 写回 Steam 真值 → **手填的 12 被无声改写**。
- 这**直接违背代码自己的承诺**（`app.js:828-829` 注释写着「自己手填的…都不碰」）。判据是「`ach_total` 是否为空」而不是「填没填」，所以「只填总数不填已完成」的人反而不会中招。
- **最小修法**：
```js
// web/app.js:833 之前插入
if (g.mark_source && g.mark_source !== 'steam') return false;   // 手填的别碰
```
逃生口本来就有：想让它去问 Steam，点「🔄 重新读取成就」（走 `force=1`）。服务端再防一层的话，`app.py:487` 的判据加上 `cur.get("source") == "steam"`。

---

## 四、中等问题

### 🟡3. 一次 400 就永久写死 `noach`，成功读取也清不掉
- **位置**：`app.py:501`、`app.py:505-507`、`app.py:156-161`
- 400 的原因不止「没有成就系统」（家庭共享/别人账号装的游戏、steamid 写错、appid 下架都会 400），而 `steam_online.py:45-68` 把所有 400 统一翻译成「最常见的原因是这款游戏没有成就系统」。
- 后果：① 卡片从此显示「没有成就系统」，`needAchFetch` 永久刹车；② **即使点「🔄」成功拿到成就，`noach: true` 仍留在记录里**，界面继续显示「没成就」。只能手工改 manual.json 才能恢复。
- **最小修法**：
```python
# app.py:501
if "没有成就系统" in msg:
# app.py:505-507
rec, _ = update_manual(appid, {"ach": r["achieved"], "ach_total": r["total"], "source": "steam", "noach": False})
```

### 🟡4. `showFatal` 写下的内联 `display:none` 没有恢复路径
- **位置**：`web/app.js:982-985`（对 `main > *` 写 `el.style.display='none'`），恢复代码在成功路径上不存在（`app.js:1005-1006` 只做 `renderAll(); openFromHash();`）
- 触发：任何一次 `/api/data` 失败 → `showFatal`；之后点顶栏「重新扫描」（顶栏在 `<main>` 之外，仍可点）成功 → 数据已读到，页面却只剩红牌，必须手工 F5。
- **最小修法**：
```js
// app.js:987 之后
function clearFatal() {
  for (const el of document.querySelectorAll('main > *')) el.style.display = '';
  $('#fatal').hidden = true;
}
// app.js:1005 之前（load 成功分支）
clearFatal();
```

### 🟡5. 排序选项消失后 `state.sort` 变陈旧 → `filtered()` 抛 TypeError，列表冻结到 F5
- **位置**：`web/app.js:199`（`return list.sort(by || by.playtime);`）+ `web/app.js:396-403`（重建下拉后没纠正 `state.sort`）
- 复现：① 排序选「按成就完成度」；② 打开最后一个有成就记录的游戏点「清空标记」→ `nAch` 变 0 → 下拉重建，`state.sort` 仍是 `'ach'`；③ 之后每次 `renderGrid()` 都 `by.playtime` 于 undefined → `TypeError`，卡片区冻结。
- **最小修法**：
```js
// web/app.js:199
return list.sort(by || ((a, b) => b.playtime_min - a.playtime_min));
// web/app.js:402 之前
if (!sorts.some(([k]) => k === state.sort)) state.sort = 'playtime';
```

### 🟡6. `manual.json` 读不出来就当「空」，下次保存整体覆盖
- **位置**：`app.py:108-117`（`except (OSError, ValueError)` → `return {}`）+ `app.py:174`（无条件 `save_manual(m)`）
- 后果：内容损坏后重新标记任何一款，历史标记永久消失，无备份无提示。
- **最小修法**：`except` 里先 `shutil.copyfile(MANUAL_PATH, MANUAL_PATH + ".bad")`（需 `import shutil`）。

### 🟡7. 所有 POST 接口不校验 `Origin` / `Content-Type`
- **位置**：`app.py:522-600`。工具运行期间，同浏览器里任意页面的 JS 都能用 `text/plain`（无预检）POST 覆写 Key 或删标记。
- 不会泄露 Key（无 CORS 头，响应读不到），但**破坏性写入足够**。
- **最小修法**（约 6 行，零依赖）：
```python
origin = self.headers.get("Origin")
if origin and origin not in ("http://127.0.0.1:%d" % self.server.server_port,
                             "http://localhost:%d" % self.server.server_port):
    return self._json({"ok": False, "error": "拒绝跨站请求"}, 403)
host = (self.headers.get("Host") or "").split(":")[0]
if host not in ("127.0.0.1", "localhost"):
    return self._json({"ok": False, "error": "只接受本机访问"}, 403)
```
（对「本机其它进程」不设防是合理取舍 —— 它们本来就能直接读 config.json。）

### 🟡8. `/api/data` 失败时前端丢掉服务端的中文错误
- **位置**：`web/app.js:1003`（`throw new Error('HTTP ' + r.status)`）
- 后果：服务明明活着，用户却被引向「服务多半已经关掉了」。
- **最小修法**：
```js
if (!r.ok) {
  const b = await r.json().catch(() => null);
  throw new Error((b && b.error) || ('HTTP ' + r.status));
}
```

---

## 五、轻微问题

| # | 位置 | 问题 | 修法 |
|---|---|---|---|
| 9 | `app.py:515` | `'²'.isdigit()` 为真但 `int('²')` 抛错，`/api/images` 分支没 try/except → 连接被截断 | `if not (appid.isascii() and appid.isdigit()):` |
| 10 | `app.py:329-344` | `_local_data` 命中缓存只做浅拷贝 → `apply_manual` 改的是缓存里的同一批 dict，并发时可能 `RuntimeError` | `cached["games"] = [dict(g) for g in cached["games"]]` |
| 11 | `web/app.js:224`、`:1010` | 未套 `esc()`（账号目录名、`e.message`）——**当前构造不出有效载荷**，顺手补齐 | 套上 `esc()` |
| 12 | `app.py:219-235` | `image_counts` 不判 `isfile`，子目录会被多算 | 补 `os.path.isfile(...)` |
| 13 | `app.py` 的 `ACH_TTL` 与 `web/app.js:836` 的 `6*3600` | 同一语义常量两端各写一份 | 注释里互相指认 |
| 14 | `steam_online.py:116-131`、`manifest_last_played`、`app.js:107` | 死代码（`fetch_recent` 无人调用等） | **可留可删，收益为零** |
| 15 | `web/app.js:351-373` | 吃灰卡片对「装了但一次没打开」仍追加「· 上次 <日期>」，可能自相矛盾 | 该分支不渲染「上次」 |

---

## 六、明确「没问题」的部分（已实测/逐行核对，不用再怀疑）

1. **`appinfo.vdf` 不会被当文本读**：全仓零引用，只有 `cache/appinfo.json`。
2. **畸形/截断 VDF 不炸解析器**：实测截断+二进制垃圾 → `read_text` 走 latin-1 兜底，`parse_vdf` 不抛异常；token 越界有 `pos < total` 保护。
3. **递归不会炸**：真实 localconfig 最大嵌套 7 层，要到 2000 层才 `RecursionError`，且被 `read_playtime` / `read_manifests` 的 `except Exception` 兜住。
4. **内存放大可控**：0.4MB localconfig 的 token 峰值仅 3.4MB（≈8×），`collect()` 冷启动 90ms / 热 114ms。
5. **静态服务无目录穿越**：stdlib `translate_path` 丢弃 `..` 组件；`config.json` / `manual.json` 在 `web/` 之外，HTTP 取不到。
6. **图片路径处理安全**：`_safe_name` 先 `basename` 再拒分隔符与 `..`，`_img_dir` 用 `int(appid)` 作目录名，重名加后缀不覆盖。
7. **不存在「上传即 XSS」**：`svg`/`svg+xml` 被白名单拒绝。（建议顺手加 `X-Content-Type-Options: nosniff`。）
8. **前端注入面基本封闭**：逐条核对所有插值点 —— `alt` / `title` / `data-del` / `href` / `src` / `#scanInfo` / `#notice` / `installdir` / 错误提示**全部套了 `esc()`**；`img_public` 用 `quote` 编码文件名。唯二没套的两处构造不出载荷。
9. **成就自动读取的刹车在所有失败路径下都有效**：成功 → `source=steam` + `at=now`（6h）；没成就 → `noach` 永久刹车；401/403/429/超时 → **不写负缓存**；`state.achBusy` 在 `finally` 复位。**不会无限重试。** 代价是每次打开该游戏会重问一次 Steam —— 单人使用可接受，**不建议加退避**（会制造「明明能读到却一直说没有」）。
10. **弹窗没有监听器泄漏**：`escClose` 用同一函数引用（DOM 规范自动去重），`closeDetail` 里 remove；卡片处理器是重建 DOM 后重新赋值 `onclick`。
11. **`[hidden]` 被作者样式覆盖的坑只有已修的那几处**：逐条核对 style.css 里所有带 `display` 的规则与 index.html 里所有 `hidden` 元素 —— `.modal[hidden]` / `.tabPane[hidden]` / `.fatal[hidden]` / `#achNote[hidden]` 已补齐，其余元素的 CSS 未设 `display`。
12. **413 之后不排空 body 不会串包**：没设 `protocol_version` → HTTP/1.0，每请求关连接。
13. **错误文案不泄露 Key，也不泄露堆栈**：`traceback.print_exc()` 只打到控制台。
14. **写配置顺序正确**：先算好 cfg → `save_config` 成功才更新内存，失败回 500 不污染状态。
15. **`update_manual` 写入语义正确**：总数夹值、全空删壳、`os.replace` 原子替换。
16. **键值语义没问题**：ACF `LastPlayed` 与 localconfig `LastPlayed` 都是「上次启动时间」；`LastUpdated` 单独放在 `last_updated` 并标成「最近更新」，没参与吃灰计算。唯一可挑的是 `autocloud.lastexit`（上次退出/云同步时间）跨机时略偏晚 —— **建议只在注释里写清，不改逻辑**。

---

## 七、建议**不要**做的

1. 不要给 HTTP 加鉴权/多用户/session/CSRF token（单人本机，6 行 Origin 校验就够）。
2. 不要重写 VDF 解析器或换第三方 `vdf` 库（实测 90ms、8× 内存、畸形输入不抛异常）。
3. 不要给 config.json 的 API Key 加密或哈希（明文要发给 Steam）。
4. 不要把 manual.json 换成 SQLite（加锁+原子替换已足够，SQLite 引入 WAL/锁语义新坑）。
5. 不要为「理论上存在」的注入点做大范围转义重构（只补两处 `esc()`）。
6. 不要拆分 app.py / 引入路由框架（单一职责清晰，这个体量保持现状最优）。
7. 不要给成就读取加失败退避/负缓存。
8. 不要动 `free_port`（`app.py:603-612`）的 bind-close-then-rebind TOCTOU。
9. 不要删 `manifest_last_played`、`fetch_recent`、`imgFail` 死分支。
10. 不要动 `read_text` 的 latin-1 兜底顺序（有意的最后防线）。

---

## 八、动手顺序（预计 20 分钟，全部零依赖）

1. `app.py:43` 加 `_manual_lock`，`app.py:137` 包住 `update_manual`（🔴1）—— 唯一会丢数据的问题，先修它。
2. `web/app.js:833` 前加 `mark_source` 判断（🔴2）。
3. `app.py:501` 去掉 `or "400" in msg`，`app.py:505` 加 `"noach": False`（🟡3）。
4. `web/app.js:199` 修兜底比较器 + `402` 纠正陈旧 `state.sort`（🟡5）。
5. `web/app.js` 加 `clearFatal()` 并在成功分支调用（🟡4）。
6. `web/app.js:1003` 带回服务端错误体（🟡8）；有空再补 🟡7 的 `Origin` 校验和 🟡6 的 `.bad` 备份。
