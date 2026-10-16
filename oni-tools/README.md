# 缺氧计算查询工具

本地只读的《缺氧》（Oxygen Not Included）数据查询工具。双击 `run.bat` 就能用。

**对应版本：眼冒金星 DLC**

---

## 快速开始

双击 **`run.bat`**，浏览器会自动打开 `http://127.0.0.1:8781/`。

用完直接关掉那个黑色窗口。

需要 Python 3.8+（安装时勾选 *Add Python to PATH*）。**不需要安装任何第三方库。**

---

## 它做什么

**建筑速查** —— 搜建筑名或效果，查它的：

| 指标 | 说明 |
|---|---|
| 耗电 / 发电 | 运行时功率（W） |
| 转换 | 每秒消耗与产出的物质（kg/s），带温度 |
| 自发热 / 废气热 | 产热（kW） |
| 尺寸 / 建造质量 / 建造时间 | 规划基地用 |

支持按功能分类筛选（制氧、发电、精炼、温控、农业…），也可以只看常用建筑。

**搜索是双向的** —— 搜中文「电解」「制氧」，也搜英文 `Electrolyzer`、`Oxygen`，还能搜元素名。

**房间规划** —— 选几个想放进房间的建筑，算出：

| 指标 | 说明 |
|---|---|
| 能构成哪些房间 | 营房 / 食堂 / 抽水马桶卫生间 / 实验室…共 19 种 |
| 需要多少格 | 每种房间的尺寸区间（如营房 12~64 格，大厅 32~120 格） |
| 还缺什么 | 距离建成还差哪件家具（「还缺：洗手池」） |
| 有什么冲突 | 放了互相排斥的东西（「冲突：不要旱厕」） |

原理：缺氧的房间判定是「用砖块/门围出一块空间，空间内的建筑决定房间类型」。
建筑在源码里各自声明了 `RoomConstraints` 标签（如抽水马桶带 `FlushToiletType`），
工具把标签和房间的约束规则做匹配。**房间大小 = 内部空气格数**（不含砖块本身）。

**制氧测算** —— 两向都能算：

| 模式 | 输入 | 输出 |
|---|---|---|
| 按人口算机器 | 有几个复制人 | 每种制氧设备各要几台、够不够、余量多少 |
| 按机器算人口 | 几台什么设备 | 能养活几个人、耗多少水和电 |

每名复制人每秒消耗 **100 g 氧气**、呼出 **2 g 二氧化碳**（游戏源码常量）。
5 种制氧设备可以横向对比：电解器、铁锈脱氧机、氧气扩散器、空气净化器、藻类箱。
顺手也算出机器要喝多少水（按「kg/周期」换算，一个周期 600 秒）。

**供电测算** —— 把要用电的建筑加进清单，算出：

| 指标 | 说明 |
|---|---|
| 用电清单 | 每个建筑几台、单台功率、小计，以及总耗电 |
| 发电机配比 | 用煤炭/氢气/天然气/石油/木料发电机分别要几台、余量多少 |
| 燃料消耗 | 每种方案每天要烧多少燃料（kg/s 与 kg/周期） |

同一个用电量下，5 种发电机各自的台数和燃料需求会并排列出来，方便权衡烧什么。

---

## 数据是怎么来的

**没有靠抄 Wiki。** 数据是从**游戏本体的反编译源码**里直接提取的：

```
游戏 Assembly-CSharp.dll
   ↓ 反编译（ilspycmd）
_decomp/*.cs   （4410 个源文件）
   ↓ extract_buildings.py  正则解析
data/buildings.json   （64 个常用建筑）
   ↓
网页展示
```

房间规划的数据多走了两条链路：

```
_decomp/*Config.cs
   ↓ extract_tags.py  抓 AddTag(RoomConstraints.ConstraintTags.X)
tags.json            （186 栋建筑 → 房间标签）
   ↓
_decomp/RoomConstraints.cs + ROOMS.cs
   ↓ extract_rooms.py
rooms.json           （19 种房间的约束规则）

游戏 strings_preinstalled_zh_klei.po（官方中文翻译）
   ↓ build_names.py  用 <link="建筑ID"> 反查中文
build_names_zh.json  （453 个建筑的中文名）
```

中文名不是手写的，是从**游戏自带的官方中文语言包**里取的，所以和游戏内显示一致
（`Cot` → 床铺，`Lavatory` → 抽水马桶，`Mess Table` → 小餐桌）。

制氧与供电测算的常量多走一条链路：

```
_decomp/MinionConfig.cs（小人代谢）+ 各制氧设备 *Config.cs
   ↓ extract_constants.py
constants.json       （耗氧/卡路里/膀胱等常量 + 5 台制氧设备 + 5 种发电机）
```

这么做的原因：Wiki 的数值可能滞后好几个版本，而源码是**权威且当前**的。

### 几个真实例子

提取出来的数值（可以在网页上核对）：

- **电解器**：水 1 kg/s → 氧气 0.888 + 氢气 0.112 kg/s @ 343K(70°C)，耗电 120 W
- **煤炭发电机**：煤 1 kg/s → 600 W，尾气二氧化碳 0.02 kg/s @ 383K(110°C)
- **金属精炼器**：耗电 1200 W，自发热 16 kW

---

## 已知局限（重要，请先读）

1. **部分配方抓不到，只能留空。**
   有些建筑的配方是**运行时动态生成**的，不是写死的常量。典型是**金属精炼器** ——
   它的配方是遍历全元素表，把所有金属按 `100kg → 100kg` 生成的。这类配方无法用正则提取，
   网页上会显示为空。这不是 bug，是提取方式的边界。

2. **温度缺失时不显示，而不是显示 0。**
   有些输出的温度源码里没写（用引擎默认值）。工具**选择不显示**，而不是算成
   绝对零度 -273°C 那种假数据。

3. **只覆盖 64 个建筑**，不是游戏全部建筑。覆盖的是最常用的一批。

4. **发电机燃料公式有五种写法**（3 参数 / 6 参数 / 裸字符串 / `InputItem` 数组 / 手填 Formula 对象），
   工具能识别前四种。5 种发电机的燃料现在都抓到了；若后续版本新增手填对象形式会显示为空。

   注意：**发电机在建筑速查里没有「耗电」是正常的** —— 工具把「耗电」（`EnergyConsumptionWhenActive`）
   和「发电」（`GeneratorWattageRating`）分成两个字段。发电机只发电不耗电。

5. **供电测算只列有耗电值的建筑**（当前 25 个，都在 64 个核心清单内）。
   聚合器、液冷机等不在核心清单里的建筑搜不到 —— 想加的话要先把它们加进
   `target_buildings.txt` 再重跑提取脚本。搜不到时页面会明确提示，不会静默漏算。

6. **房间规划只做格数与条件核算。**
   实际游戏里还要考虑建筑朝向、装饰物的具体摆放位置、房间高度连续性等，
   工具不算这些。另外 `IS_BACKWALLED`（贴背景墙）这类房间天然满足的条件会被跳过。

7. **测算取的是满载理论值。**
   耗电按建筑满载功率累加，不含电线损耗与发电机启停；燃料按满载算，实际会随负载波动。
   制氧的用氧量取源码常量 100 g/s，实际呼吸量受气压等影响，规划时余量建议留一点。

---

## 文件结构

```
oni-tools/
├─ run.bat               双击启动
├─ app.py                本地服务（127.0.0.1:8781，纯标准库）
├─ extract_buildings.py  从反编译源码提取建筑数据
├─ extract_tags.py       提取建筑的房间标签
├─ extract_rooms.py      提取房间类型与约束规则
├─ extract_room_buildings.py  合并出 186 栋房间相关建筑
├─ build_names.py        从游戏官方中文包提取建筑中文名
├─ room_engine.py        房间规划计算引擎（命令行可单跑）
├─ extract_constants.py  提取小代谢常量 + 制氧设备 + 发电机
├─ calc_engine.py        制氧/供电测算引擎（命令行可单跑）
├─ target_room_buildings.txt  186 栋目标建筑清单
├─ data/                 给前端用的数据（提取产物的副本，不进 Git）
├─ web/
│  ├─ index.html
│  ├─ style.css
│  ├─ app.js             建筑速查（零依赖原生 JS）
│  ├─ rooms.js           房间规划
│  ├─ calc.js            制氧测算 / 供电测算
│  ├─ _selftest.html     calc.js 与 calc_engine.py 的数值一致性自测（34 项）
│  └─ _e2e.html          供电/制氧交互端到端自测（24 项）
├─ tools/                ilspycmd 反编译工具（用 fetch_ilspy.py 重新下载）
├─ _decomp/              反编译出来的游戏源码（约 4400 个 .cs，体积大）
└─ README.md
```

### 命令行单跑测算

不想开网页时，三个引擎都能直接问：

```bat
python room_engine.py 床铺 抽水马桶 洗手池     :: 房间规划
python calc_engine.py oxy 8                    :: 8 个人要几台制氧机
python calc_engine.py oxy --machines Electrolyzer 2   :: 2 台电解器能养几个人
python calc_engine.py power Electrolyzer:2 LiquidPump:1   :: 用电汇总 + 发电机配比
python calc_engine.py list                     :: 列出可选的制氧设备与发电机
```

`calc_engine.py` 与网页端的 `calc.js` 是**两套独立实现**，用 `web/_selftest.html`
交叉核对，保证两边算出的数一致。

---

## 重新生成数据

如果游戏更新了，想刷新数值：

**建筑速查的数据：**

```bat
python extract_buildings.py
copy buildings.json data\buildings.json
```

`extract_buildings.py` 会遍历 `_decomp/` 目录，按内置的 64 建筑清单查找对应的
`*Config.cs` 并解析。

**房间规划的数据：**

```bat
python extract_tags.py             :: tags.json        建筑 -> 房间标签
python extract_rooms.py            :: rooms.json       19 种房间的约束规则
python build_names.py              :: build_names_zh.json   建筑中文名
python extract_room_buildings.py   :: buildings_rooms.json  合并成 186 栋
copy rooms.json tags.json buildings_rooms.json data\
```

**顺序有依赖**：`extract_room_buildings.py` 需要 `build_names_zh.json` 来填中文名，
所以要先跑 `build_names.py`。

**制氧/供电测算的数据：**

```bat
python extract_constants.py   :: constants.json  小人常量 + 制氧设备 + 发电机
copy constants.json data\
```

`extract_constants.py` 从 `_decomp/` 读 `MinionConfig.cs`（小人代谢）和各制氧设备/发电机的
`*Config.cs`。注意源码里卡路里与体力消耗是**负数**（表示扣除），工具保留原符号。

`extract_tags.py` / `extract_rooms.py` 从 `_decomp/` 读源码；
`build_names.py` 从**你本机游戏的官方中文语言包**读翻译，路径写在脚本头部
（`SteamLibrary\steamapps\common\OxygenNotIncluded\...\strings_preinstalled_zh_klei.po`），
换机器要改。

**注意**：清单里写的是建筑类名，脚本会自动优先找 `XxxConfig.cs`（配置类）而不是
`Xxx.cs`（执行层组件）—— 这两者同名但内容完全不同，抓错了会缺 ID 和转换率。

---

## 设计原则

- **不联网**：所有数据本地读取
- **不写用户文件**：纯只读查询
- **零依赖**：纯 Python 标准库 + 原生 JS
- **只监听 127.0.0.1**：不对局域网开放

---

## 数据安全

`_decomp/` 目录是从你本机的游戏文件反编译出来的，属于游戏版权内容。
如果这个项目要分享给他人，**应当排除 `_decomp/` 和 `buildings.json`**，
只分享提取脚本和网页部分。
