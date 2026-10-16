# -*- coding: utf-8 -*-
"""
从游戏本地化文件提取建筑中文名。

链路:
  _decomp/STRINGS/BUILDINGS.cs  ->  建筑 ID + 英文基础名
  游戏 strings_preinstalled_zh_klei.po  ->  英文 -> 中文（按 <link="ID"> 标签）
  输出: build_names_zh.json  { 建筑ID: 中文名 }
"""
import os, re, json

HERE = os.path.dirname(os.path.abspath(__file__))
DECOMP = os.path.join(HERE, "_decomp")
PO_PATH = (r"V:\SteamLibrary\steamapps\common\OxygenNotIncluded"
           r"\OxygenNotIncluded_Data\StreamingAssets\strings"
           r"\strings_preinstalled_zh_klei.po")
OUT = os.path.join(HERE, "build_names_zh.json")

# 已知的家具类/装饰类前缀词（用于剔除皮肤变体）
SKIN_HINTS = re.compile(
    r'\b(Lavatory|Cot|Bed|Table|Sink|Station|Fridge|Display|Shelf|Lamp|Chair|Door)\b'
)


def parse_english_names():
    """从 BUILDINGS.cs 拿 { 建筑ID: 英文基础名 }"""
    src = open(os.path.join(DECOMP, "STRINGS", "BUILDINGS.cs"),
               encoding="utf-8", errors="ignore").read()
    out = {}
    for name, body in re.findall(r'public class (\w+)\s*\{(.*?)\n\t\t\}', src, re.S):
        m = re.search(r'NAME\s*=\s*UI\.FormatAsLink\(\s*"(.*?)"\s*,\s*"(\w+)"\s*\)', body, re.S)
        if m:
            out[m.group(2)] = m.group(1)   # link ID -> 英文名
    return out


def parse_po():
    """从 PO 拿 { link ID : { 英文名: 中文名 } }"""
    txt = open(PO_PATH, encoding="utf-8", errors="ignore").read()
    pat = re.compile(r'msgid "((?:[^"\\]|\\.)*)"\s*\nmsgstr "((?:[^"\\]|\\.)*)"')
    by_link = {}
    for m in pat.finditer(txt):
        e, c = m.group(1), m.group(2)
        lm = re.search(r'<link=\\"(\w+)\\">(.*?)</link>', e, re.S)
        if not lm or not c.strip():
            continue
        link, en = lm.group(1), lm.group(2).strip()
        cm = re.search(r'<link=\\"\w+\\">(.*?)</link>', c, re.S)
        if not cm:
            continue
        cn = cm.group(1).strip()
        # 剔掉明显不是建筑名的（句子类）
        if len(en) > 40 or len(cn) > 40:
            continue
        by_link.setdefault(link, {})[en] = cn
    return by_link


def main():
    en_names = parse_english_names()
    po = parse_po()

    out, miss, skin = {}, [], []
    for bid, en in en_names.items():
        table = po.get(bid)
        if not table:
            miss.append((bid, en)); continue
        if en in table:
            out[bid] = table[en]
        else:
            # 英文名不完全匹配：找最短的那个中文（通常是基础名）
            cand = sorted(table.items(), key=lambda kv: len(kv[1]))
            if cand:
                out[bid] = cand[0][1]
                skin.append((bid, en, cand[0][0], cand[0][1]))
            else:
                miss.append((bid, en))

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"by_id": out, "by_class": en_names}, f, ensure_ascii=False, indent=2)

    print(f"英文名表: {len(en_names)} 栋")
    print(f"PO link 表: {len(po)} 个 ID")
    print(f"精确匹配成功: {len(out)} 栋")
    print(f"回退取最短: {len(skin)} 栋")
    print(f"完全没找到: {len(miss)} 栋")
    print()
    print("--- 抽查 ---")
    for k in ["BED", "OUTHOUSE", "FLUSHTOILET", "DININGTABLE", "RESEARCHCENTER",
              "WASHSINK", "LUXURYBED", "MASSAGETABLE", "POWERSTATION", "FARMSTATION"]:
        print(f"  {k:<16} {en_names.get(k,''):<22} -> {out.get(k,'(缺)')}")
    if miss:
        print(f"\n--- 缺失前 10 ---")
        for bid, en in miss[:10]:
            print(f"  {bid:<26} {en}")


if __name__ == "__main__":
    main()
