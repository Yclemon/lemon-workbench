#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从反编译源码提取缺氧的「房间类型」规则。

数据来源: _decomp/Database/RoomTypes.cs
每个房间类型形如:

    Barracks = Add(new RoomType("Barracks", NAME, DESC, TIP, EFFECT,
        Db.Get().RoomTypeCategories.Sleep,      <- 分类
        RoomConstraints.LUXURY_BED_SINGLE,       <- 主约束
        new RoomConstraints.Constraint[N] {      <- 附加约束数组
            RoomConstraints.NO_COTS,
            RoomConstraints.MINIMUM_SIZE_12,
            ...
        },
        new RoomDetails.Detail[K] {...},         <- 显示项
        priority, upgrade_paths, ...));

同时提取 RoomConstraints.cs 里每个约束的**判定条件**和**中文名**，
这样才能告诉用户「为什么我的房间不成立」。
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DECOMP = os.path.join(HERE, "_decomp")
ROOM_TYPES_SRC = os.path.join(DECOMP, "Database", "RoomTypes.cs")
ROOM_CONSTRAINTS_SRC = os.path.join(DECOMP, "RoomConstraints.cs")

# 约束 ID -> 中文说明（源码里只有 STRINGS 引用，取不到正文，这里人工对照）
CONSTRAINT_DOC = {
    "MINIMUM_SIZE_12": ("最小 12 格", "可用空间至少 12 格"),
    "MINIMUM_SIZE_24": ("最小 24 格", "可用空间至少 24 格"),
    "MINIMUM_SIZE_32": ("最小 32 格", "可用空间至少 32 格"),
    "MAXIMUM_SIZE_64": ("最大 64 格", "可用空间不超过 64 格"),
    "MAXIMUM_SIZE_96": ("最大 96 格", "可用空间不超过 96 格"),
    "MAXIMUM_SIZE_120": ("最大 120 格", "可用空间不超过 120 格"),
    "CEILING_HEIGHT_4": ("层高至少 4", "房间内高至少 4 格"),
    "CEILING_HEIGHT_6": ("层高至少 6", "房间内高至少 6 格"),
    "NO_COTS": ("不要简易床", "房间里不能有简易床(行军床)"),
    "NO_OUTHOUSES": ("不要旱厕", "房间里不能有户外厕所"),
    "NO_INDUSTRIAL_MACHINERY": ("无工业机械", "有工业机械的房间不算这类房间"),
    "NO_MESS_STATION": ("不要餐桌", "房间里不能有餐桌"),
    "NO_BASIC_MESS_STATIONS": ("不要基础餐桌", "房间里不能有基础餐桌"),
    "TOILET": ("有厕所", "至少一个厕所(含旱厕)"),
    "FLUSH_TOILET": ("有冲水马桶", "至少一个抽水马桶"),
    "WASH_STATION": ("有洗手台", "至少一个洗手池/洗手台"),
    "ADVANCEDWASHSTATION": ("有洗手池", "至少一个洗手池"),
    "BED": ("有床", "至少一张床"),
    "HAS_BED": ("有床", "至少一张床，且该床不属于医疗设施"),
    "LUXURY_BED": ("有豪华床", "至少一张豪华床"),
    "HAS_LUXURY_BED": ("有豪华床", "至少一张豪华床"),
    "LUXURY_BED_SINGLE": ("有豪华单人床", "正好一张豪华床，不能多"),
    "MESS_STATION": ("有餐桌", "至少一张餐桌"),
    "MESS_STATION_SINGLE": ("一张餐桌", "正好一张餐桌"),
    "DINING_TABLE": ("有餐桌", "至少一张餐桌"),
    "MULTI_MINION_DINING_TABLE": ("多人大餐桌", "至少一张多人餐桌"),
    "COOKING_STATION": ("有烹饪台", "至少一个食物加工设备"),
    "COOK_TOP": ("有灶台", "至少一个灶台"),
    "SPICE_STATION": ("有调味台", "至少一个香料研磨设备"),
    "KITCHENREFRIGERATOR": ("厨房冰箱", "至少一个冰箱"),
    "FARM_STATION": ("农业站", "有农业站和至少一种植物"),
    "RANCH_STATION": ("牧栏站", "有牧栏站和小动物"),
    "CLINIC": ("诊所设备", "有医疗建筑(病床/医疗站)"),
    "MASSAGE_TABLE": ("按摩台", "至少一个按摩台"),
    "SCIENCE_BUILDINGS": ("研究设备×2", "至少两个研究类建筑"),
    "PARK_BUILDING": ("公园标识", "至少一个公园标识建筑"),
    "REC_BUILDING": ("娱乐建筑", "至少一个娱乐设施"),
    "ORNAMENTDISPLAYED": ("装饰物", "至少展示一个装饰品"),
    "DECORATIVE_ITEM": ("装饰物", "至少一个装饰性建筑"),
    "DECORATIVE_ITEM_2": ("装饰物×2", "至少两个装饰性建筑"),
    "IS_BACKWALLED": ("贴背景墙", "房间要有背景墙(不能是太空暴露)"),
    "POWER_STATION": ("发电站", "至少一个发电站(人力/煤炭等发电机)"),
    "LABORATORY": ("实验室设备", "至少一个研究设备"),
    "PLANT": ("植物", "至少一株植物"),
    "WILD_PLANT": ("野生植物", "至少一株野生植物"),
    "WILDPLANT": ("野生植物", "至少一株野生植物"),
    "WILDPLANTS": ("野生植物×2", "至少两株野生植物"),
    "ORIGINALTILES": ("天然地表", "地面是天然地块，没被建造物覆盖"),
    "BUILDING_DECOR_POSITIVE": ("装饰值为正", "房间装饰值 > 0"),
    "MACHINE_SHOP": ("机械车间", "至少一个机械车间设备"),
    "ROCKET": ("火箭", "在火箭内部"),
    "PARTY": ("娱乐", "—"),
    "NO_BUILDINGS": ("没有建筑", "房间里不能有任何建筑"),
}


def extract_constraint_conditions(src: str) -> dict:
    """从 RoomConstraints.cs 抓每个约束的 lambda 判定条件，用于说明。"""
    out = {}
    # 形如: public static Constraint NAME = new Constraint(...);
    for m in re.finditer(
        r"public static Constraint (\w+)\s*=\s*new Constraint\((.*?)\);",
        src,
        re.S,
    ):
        name = m.group(1)
        body = m.group(2)
        # 抓 size 数字
        size_m = re.search(r"NumCells\s*<=\s*(\d+)", body)
        height_m = re.search(r"maxY\s*-\s*room\.cavity\.minY\s*>=\s*(\d+)", body)
        info = {}
        if size_m:
            info["max_cells"] = int(size_m.group(1))
        if height_m:
            info["min_height"] = int(height_m.group(1))
        if info:
            out[name] = info
    # MINIMUM_SIZE_XX 用的是 >= 比较
    for m in re.finditer(
        r"public static Constraint (\w+)\s*=\s*new Constraint\((.*?)\);", src, re.S
    ):
        name = m.group(1)
        body = m.group(2)
        if name.startswith("MINIMUM_SIZE_"):
            mn = re.search(r"NumCells\s*>=\s*(\d+)", body)
            if mn:
                out.setdefault(name, {})["min_cells"] = int(mn.group(1))
    return out


def extract_room_types(src: str) -> list:
    """提取所有房间类型定义。"""
    rooms = []

    # 每个房间是: X = Add(new RoomType("Id", ... ));
    # 用括号配平来找完整的调用
    pattern = re.compile(r"(\w+)\s*=\s*Add\(new RoomType\(")
    for m in pattern.finditer(src):
        field = m.group(1)
        start = m.end() - len("new RoomType(")
        # 从 "new RoomType(" 开始配平括号
        depth = 0
        i = start + len("new RoomType") - 1  # 指向 '('
        in_str = False
        esc = False
        while i < len(src):
            c = src[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                    if depth == 0:
                        break
            i += 1
        body = src[start:i + 1]

        rec = {"field": field}

        # 房间 ID: new RoomType("Xxx",
        idm = re.search(r'new RoomType\(\s*"([^"]+)"', body)
        if idm:
            rec["id"] = idm.group(1)

        # 分类: Db.Get().RoomTypeCategories.Xxx
        cm = re.search(r"RoomTypeCategories\.(\w+)", body)
        if cm:
            rec["category"] = cm.group(1)

        # 主约束: 分类之后紧跟的那个 RoomConstraints.XXX （不在数组里）
        # 附加约束: new RoomConstraints.Constraint[N] { ... }
        addm = re.search(r"new RoomConstraints\.Constraint\[\d+\]\s*\{(.*?)\}\s*,", body, re.S)
        primary = None
        if addm:
            before = body[:addm.start()]
            # 主约束是分类后最后一个 RoomConstraints.XXX
            prim_all = re.findall(r"RoomConstraints\.(\w+)", before)
            if prim_all:
                primary = prim_all[-1]
            rec["additional"] = re.findall(r"RoomConstraints\.(\w+)", addm.group(1))
        else:
            prim_all = re.findall(r"RoomConstraints\.(\w+)", body)
            if prim_all:
                primary = prim_all[-1]
        if primary:
            rec["primary"] = primary

        # priority: 附加约束数组后第一个整数
        if addm:
            tail = body[addm.end():]
            pm = re.match(r"\s*(\d+)\s*,", tail)
            if pm:
                rec["priority"] = int(pm.group(1))

        # effects: new string[N] { "A", "B" }
        em = re.search(r"new string\[\d+\]\s*\{([^}]*)\}", body)
        if em:
            rec["effects"] = re.findall(r'"([^"]+)"', em.group(1))

        # 升级路径: new RoomType[N] { Xxx }
        um = re.search(r"new RoomType\[\d+\]\s*\{([^}]*)\}", body)
        if um:
            rec["upgrades_to"] = [s.strip() for s in um.group(1).split(",") if s.strip()]

        rooms.append(rec)

    return rooms


def main():
    for p in (ROOM_TYPES_SRC, ROOM_CONSTRAINTS_SRC):
        if not os.path.isfile(p):
            print(f"错误: 找不到 {p}")
            return 1

    types_src = open(ROOM_TYPES_SRC, encoding="utf-8").read()
    cons_src = open(ROOM_CONSTRAINTS_SRC, encoding="utf-8").read()

    rooms = extract_room_types(types_src)
    print(f"提取到房间类型: {len(rooms)}")

    conds = extract_constraint_conditions(cons_src)
    print(f"提取到带数值条件的约束: {len(conds)}")

    # 整理输出
    out = []
    for r in rooms:
        rec = {
            "id": r.get("id"),
            "field": r.get("field"),
            "category": r.get("category"),
            "priority": r.get("priority", 0),
            "effects": r.get("effects", []),
        }
        creqs = []
        allc = ([r["primary"]] if r.get("primary") else []) + r.get("additional", [])
        for c in allc:
            doc = CONSTRAINT_DOC.get(c)
            item = {
                "id": c,
                "name": doc[0] if doc else c,
                "desc": doc[1] if doc else "",
            }
            if c in conds:
                item.update(conds[c])
            creqs.append(item)
        rec["c_primary"] = r.get("primary")
        rec["constraints"] = creqs
        if r.get("upgrades_to"):
            rec["upgrades_to"] = r["upgrades_to"]
        out.append(rec)

    # 补上中文房名（源码里 STRINGS 取不到，人工对照）
    NAME_CN = {
        "Neutral": "普通房间", "Latrine": "旱厕", "PlumbedBathroom": "抽水马桶卫生间",
        "Barracks": "营房", "Bedroom": "卧室", "Private Bedroom": "私人卧室",
        "MessHall": "食堂", "Kitchen": "厨房", "GreatHall": "大厅",
        "BanquetHall": "宴会厅", "Hospital": "医院", "MassageClinic": "按摩诊所",
        "PowerPlant": "发电站", "Farm": "农场", "CreaturePen": "畜栏",
        "MachineShop": "机械车间", "RecRoom": "娱乐室", "Park": "公园",
        "NatureReserve": "自然保护区", "Laboratory": "实验室",
    }
    for r in out:
        r["name_cn"] = NAME_CN.get(r["id"], r["id"])

    dst = os.path.join(HERE, "rooms.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"输出: {dst}")

    print("\n--- 抽查 ---")
    for r in out:
        if r["id"] in ("Barracks", "PlumbedBathroom", "GreatHall", "Private Bedroom"):
            print(f"\n{r['name_cn']} ({r['id']})  分类={r['category']}  优先级={r['priority']}")
            for c in r["constraints"]:
                extra = ""
                if "min_cells" in c:
                    extra = f"  [{c['min_cells']}格起]"
                elif "max_cells" in c:
                    extra = f"  [最多{c['max_cells']}格]"
                elif "min_height" in c:
                    extra = f"  [高≥{c['min_height']}]"
                print(f"    - {c['name']}{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
