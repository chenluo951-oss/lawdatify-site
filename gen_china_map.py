#!/usr/bin/env python3
"""生成中国省级监管态势地图数据 sources/radar/china.json。

数据源：DataV.GeoAtlas 100000_full.json（含 34 个省级行政区 + 南海诸岛九段线要素，
边界符合中国官方标准画法，台湾省、香港、澳门均为独立省级要素）。
投影：Albers 等积圆锥（标准纬线 25°/47°，中央经线 105°），与常用中国地图观感一致。
输出为示意性 SVG 路径，供 news/map.html 点击中国后下钻使用。
"""
import json
import math
import os

SRC = "/tmp/china_full.json"
DST = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "sources", "radar", "china.json")

# ⚠️ 省级条目**不再写死在本文件**（原 PROV_ITEMS 的 7 条已迁到
# sources/radar/prov_curated.json，作为人工精选来源之一）。
#
# 原因：写死的结果是「站点的合规动态与案例库每天都在涨，省市级地图却一直
# 只有那 7 条」—— 用户 2026-09-17 反馈「省市的还是没更新啊」。
#
# 现在省级条目由 tools/build_prov_data.py 聚合生成：
#   · sources/radar/prov_curated.json   人工精选的地方监管动作
#   · sources/news/items.jsonl          合规动态（按发布机关判属地）
#   · sources/cases/cases.json          案例库（机关名 / 属地判据）
#   · sources/cases/local_amr.jsonl     地方市场监管机关公示（agency 字段最准）
# 本文件只负责**几何**（省界路径 + 标注点），跑完请接着跑：
#   python3 tools/build_prov_data.py --apply
# 该脚本会保留 path / cx / cy / viewBox，只重写 provinces[].items。
PROV_ITEMS = {}

PROV_SHORT = {
    "北京市": "北京", "天津市": "天津", "河北省": "河北", "山西省": "山西", "内蒙古自治区": "内蒙古",
    "辽宁省": "辽宁", "吉林省": "吉林", "黑龙江省": "黑龙江", "上海市": "上海", "江苏省": "江苏",
    "浙江省": "浙江", "安徽省": "安徽", "福建省": "福建", "江西省": "江西", "山东省": "山东",
    "河南省": "河南", "湖北省": "湖北", "湖南省": "湖南", "广东省": "广东", "广西壮族自治区": "广西",
    "海南省": "海南", "重庆市": "重庆", "四川省": "四川", "贵州省": "贵州", "云南省": "云南",
    "西藏自治区": "西藏", "陕西省": "陕西", "甘肃省": "甘肃", "青海省": "青海", "宁夏回族自治区": "宁夏",
    "新疆维吾尔自治区": "新疆", "台湾省": "台湾", "香港特别行政区": "香港", "澳门特别行政区": "澳门",
}


def albers(lon, lat):
    """Albers 等积圆锥，标准纬线 25/47，原点 (105,36)。返回像素坐标。"""
    p1, p2, p0, l0 = map(math.radians, (25, 47, 36, 105))
    t = lambda p: math.cos(p) / math.sqrt(1 - math.sin(p) ** 2)
    n = (math.sin(p1) + math.sin(p2)) / 2
    C = t(p1) ** 2 + 2 * n * math.sin(p1)
    rho = lambda p: math.sqrt(max(0.0, C - 2 * n * math.sin(p))) / n
    th = n * (math.radians(lon) - l0)
    x = rho(math.radians(lat)) * math.sin(th)
    y = rho(p0) - rho(math.radians(lat)) * math.cos(th)
    return x, y


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    feats = d["features"]
    # 计算全部坐标范围
    allxy = []

    def collect(coords):
        if isinstance(coords[0], (int, float)):
            allxy.append(coords)
        else:
            for c in coords:
                collect(c)

    for f in feats:
        g = f["geometry"]
        collect(g["coordinates"])
    xs = [p[0] for p in allxy]
    ys = [p[1] for p in allxy]
    sx = [albers(x, y) for x, y in allxy]
    minx, maxx = min(p[0] for p in sx), max(p[0] for p in sx)
    miny, maxy = min(p[1] for p in sx), max(p[1] for p in sx)
    W, H = 1000.0, 820.0
    pad = 8
    k = min((W - 2 * pad) / (maxx - minx), (H - 2 * pad) / (maxy - miny))
    ox = pad + (W - 2 * pad - (maxx - minx) * k) / 2
    oy = pad + (H - 2 * pad - (maxy - miny) * k) / 2

    def px(lon, lat):
        x, y = albers(lon, lat)
        # albers 的 y 轴向北为正，SVG 向下为正 → 翻转
        return round((ox + (x - minx) * k), 1), round(H - (oy + (y - miny) * k), 1)

    EPS = 1.4  # 像素级抽稀
    def ring_path(ring):
        pts, last = [], None
        for lon, lat in ring:
            q = px(lon, lat)
            if last and abs(q[0] - last[0]) < EPS and abs(q[1] - last[1]) < EPS:
                continue
            pts.append(q)
            last = q
        if len(pts) < 4:
            return ""
        return "M" + "L".join(f"{a} {b}" for a, b in pts) + "Z"

    provs = []
    for f in feats:
        name = f["properties"].get("name") or ""
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        parts = []
        for poly in polys:
            p = ring_path(poly[0])
            if p:
                parts.append(p)
        if not parts:
            continue
        c = f["properties"].get("centroid") or f["properties"].get("center")
        cx = cy = None
        if c:
            cx, cy = px(c[0], c[1])
        code = str(f["properties"].get("adcode", ""))
        if name:
            provs.append(dict(code=code, name=name, short=PROV_SHORT.get(name, name),
                              path="".join(parts), cx=cx, cy=cy,
                              items=PROV_ITEMS.get(name, [])))
        else:
            # 南海诸岛/九段线要素：保留轮廓用于合规展示
            provs.append(dict(code=code or "SJXT", name="南海诸岛", short="",
                              path="".join(parts), cx=None, cy=None, items=[]))

    out = dict(
        _src="DataV.GeoAtlas 100000_full（含九段线；台湾省/香港/澳门为独立省级要素）| Albers 等积圆锥 25/47 @105,36 | 示意性视图，非地理精确边界",
        viewBox=f"0 0 {W:.0f} {H:.0f}", provinces=provs)
    json.dump(out, open(DST, "w", encoding="utf-8"), ensure_ascii=False)
    n_items = sum(len(p["items"]) for p in provs)
    print(f"provinces={len(provs)} items={n_items}（几何层；条目由 build_prov_data.py 填充）-> {DST}")
    sizes = sorted(len(p["path"]) for p in provs)
    print("path size min/med/max:", sizes[0], sizes[len(sizes)//2], sizes[-1])


if __name__ == "__main__":
    main()
