#!/usr/bin/env python3
"""生成站点用世界地图矢量数据（sources/radar/geo.json）。

数据源为 Natural Earth 110m 简化版（world-atlas TopoJSON，公开领域数据），
仅在本机一次性转换为静态 SVG 路径；运行时页面不请求任何在线地图服务。

合规处理要点
------------
1. 中国（ISO 156）与台湾地区（158）、港澳（344/446）合并为同一个 CN 色块，
   使用完全相同的填充样式，不单独着色、不单独描边、不并列标注。
2. 地图为等距圆柱投影的**示意性视图**，非地理精确边界地图，不承担划界意义。
3. 不标注争议地区名称。

输出结构
--------
{
  "viewBox": [w, h],
  "grp": {"CN": {"zones": [{"id":..,"d":..}], "label": [x,y], "micro": bool}},
  "other": [{"d":..}]
}
"""

import base64
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sources", "radar", "geo.json")
CACHE_TOPO = "/tmp/countries-110m.json"
TOPO_URL = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json"

# 裁剪纬度：去掉南极洲与过高纬度空白，让构图更紧凑
LAT_TOP, LAT_BOTTOM = 84.0, -58.0
WIDTH = 1200.0

# 辖区 → ISO 3166-1 numeric 成员。
# 说明：158（台湾地区）、344（香港）、446（澳门）并入 156（中国）同一色块。
GROUP_ISO = {
    "CN": [156, 158, 344, 446],
    "US": [840],
    "CA": [124],
    "JP": [392],
    "KR": [410],
    "IN": [356],
    "SG": [702],
    "AU": [36],
    "ID": [360],
    "VN": [704],
    "BR": [76],
    "MX": [484],
    "ZA": [710],
    "NG": [566],
    "AE": [784],
    "SA": [682],
    "GB": [826],
    "EU": [40, 56, 100, 191, 196, 203, 208, 233, 246, 250, 276, 300, 348,
           372, 380, 428, 440, 442, 470, 528, 616, 620, 642, 703, 705, 724,
           752],
    "RU": [643],
    "TR": [792],
}

# 面积过小的辖区（110m 精度下几乎不可见）改用定位圆点标记
MICRO = {"SG"}

# 定位点（近似行政中心经纬度），仅用于 micro 辖区与标签锚点
ANCHOR = {
    "CN": (104.0, 35.5), "US": (-98.0, 39.5), "CA": (-106.0, 56.0),
    "JP": (138.5, 36.5), "KR": (127.8, 36.5), "IN": (78.9, 22.5),
    "SG": (103.82, 1.35), "AU": (134.0, -25.5), "ID": (118.0, -2.0),
    "VN": (106.5, 16.0), "BR": (-51.0, -10.0), "MX": (-102.0, 23.0),
    "ZA": (24.0, -29.0), "NG": (8.0, 9.0), "AE": (54.0, 24.0),
    "SA": (45.0, 24.0), "GB": (-2.0, 54.0), "EU": (10.0, 51.0),
    "RU": (95.0, 61.0), "TR": (35.0, 39.0),
}


def miller_y(lat):
    """Miller 圆柱投影纵坐标（弧度单位）。"""
    phi = math.radians(max(min(lat, 89.9), -89.9))
    return 1.25 * math.log(math.tan(math.pi / 4 + 2 * phi / 5))


def build_projector():
    x0 = -math.pi
    x1 = math.pi
    y_top = miller_y(LAT_TOP)
    y_bot = miller_y(LAT_BOTTOM)
    scale = WIDTH / (x1 - x0)
    height = (y_top - y_bot) * scale

    def proj(lon, lat):
        x = (math.radians(max(min(lon, 180.0), -180.0)) - x0) * scale
        y = (y_top - miller_y(max(min(lat, LAT_TOP), LAT_BOTTOM))) * scale
        return x, y

    return proj, height


def fetch_topo():
    if os.path.exists(CACHE_TOPO):
        return CACHE_TOPO
    print("下载 Natural Earth 110m …")
    subprocess.run(["curl", "-sL", "--max-time", "60", TOPO_URL,
                    "-o", CACHE_TOPO], check=False)
    if not os.path.exists(CACHE_TOPO):
        sys.exit("地图源数据下载失败")
    return CACHE_TOPO


def decode_arcs(topo):
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    out = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        out.append(pts)
    return out


def ring_points(arc_idx, arcs):
    pts = []
    for i in arc_idx:
        seg = arcs[i] if i >= 0 else arcs[~i][::-1]
        pts.extend(seg[1:] if pts else seg)
    return pts


def path_d(rings, proj, min_area=1.2):
    """把一组环转成 SVG path；面积过小的岛礁直接丢弃以压缩体积。"""
    parts = []
    for ring in rings:
        if len(ring) < 4:
            continue
        if shoelace(proj(*p) for p in ring) < min_area:
            continue
        seg = ["M%.1f %.1f" % proj(*ring[0])]
        last = ring[0]
        for p in ring[1:]:
            x, y = proj(*p)
            px, py = proj(*last)
            if abs(x - px) > WIDTH * 0.5:
                # 跨 180° 经线（斐济、白令海峡）：投影后 x 跳变半幅以上，
                # 必须断开子路径，否则会画出横贯整幅地图的直线
                seg.append("M%.1f %.1f" % (x, y))
            elif abs(x - px) < 0.35 and abs(y - py) < 0.35:
                continue
            else:
                seg.append("L%.1f %.1f" % (x, y))
            last = p
        if len(seg) < 3:
            continue
        seg.append("Z")
        parts.append("".join(seg))
    return "".join(parts)


def shoelace(pts):
    pts = list(pts)
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def main():
    topo = json.load(open(fetch_topo(), encoding="utf-8"))
    arcs = decode_arcs(topo)
    proj, height = build_projector()

    iso2grp = {}
    for grp, isos in GROUP_ISO.items():
        for iso in isos:
            iso2grp[iso] = grp

    groups = {g: {"zones": [], "area": 0.0} for g in GROUP_ISO}
    others = []

    for geom in topo["objects"]["countries"]["geometries"]:
        iso = geom.get("id")
        try:
            iso = int(iso)
        except (TypeError, ValueError):
            iso = -1
        polys = []
        if geom["type"] == "Polygon":
            polys = [geom["arcs"]]
        elif geom["type"] == "MultiPolygon":
            polys = geom["arcs"]
        rings = [[ring_points(r, arcs) for r in poly] for poly in polys]

        grp = iso2grp.get(iso)
        if grp is None:
            d = path_d([r for poly in rings for r in poly], proj, min_area=4.0)
            if d:
                others.append(d)
            continue
        for ri, poly in enumerate(rings):
            d = path_d(poly, proj)
            if not d:
                continue
            groups[grp]["zones"].append({"id": f"{grp}-{ri}", "d": d})
            groups[grp]["area"] += max(
                shoelace(proj(*p) for p in r) for r in poly)

    out_grp = {}
    for code, meta in groups.items():
        # 微型辖区可能完全没有可见路径（110m 精度下 <1.2px²），
        # 但只要配置了锚点就必须保留，靠定位圆点才认得出来。
        if not meta["zones"] and code not in MICRO:
            continue
        lon, lat = ANCHOR.get(code, (0, 0))
        # 标签锚点取辖区面积加权中心以外的稳定位置：大辖区用锚点，避免压在线上
        ax, ay = proj(lon, lat)
        out_grp[code] = {
            "micro": code in MICRO or meta["area"] < 90,
            "label": [round(ax, 1), round(ay, 1)],
            "zones": meta["zones"],
        }
        if code in MICRO:
            # 面积过小：路径仍保留（可能不可见），但主要靠定位点识别
            out_grp[code]["anchor"] = [round(ax, 1), round(ay, 1)]

    data = {
        "_src": "Natural Earth 110m via world-atlas (public domain) | "
                "Miller cylindrical | 示意性视图，非地理精确边界地图",
        "viewBox": [round(WIDTH), round(height, 1)],
        "groups": out_grp,
        "other": others,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(OUT)
    print(f"生成 {OUT}  ({size/1024:.1f} KB)")
    print(f"viewBox: {data['viewBox'][0]} x {data['viewBox'][1]}")
    print(f"辖区 {len(out_grp)} 个，底图岛屿 {len(others)} 组")
    for c, m in out_grp.items():
        n = len(m["zones"])
        print(f"  {c:<4} zones={n:<4} micro={str(m['micro']):<5} "
              f"label={m['label']}")
    _ = base64  # noqa（保留导入以便将来内联压缩时使用）


if __name__ == "__main__":
    main()
