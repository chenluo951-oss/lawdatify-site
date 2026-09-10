#!/usr/bin/env python3
"""生成中国省级监管态势地图数据 sources/radar/china.json。

数据源：DataV.GeoAtlas 100000_full.json（含 34 个省级行政区 + 南海诸岛九段线要素，
边界符合中国官方标准画法，台湾省、香港、澳门均为独立省级要素）。
投影：Albers 等积圆锥（标准纬线 25°/47°，中央经线 105°），与常用中国地图观感一致。
输出为示意性 SVG 路径，供 radar/map.html 点击中国后下钻使用。
"""
import json
import math
import os

SRC = "/tmp/china_full.json"
DST = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "sources", "radar", "china.json")

# 省级监管动态（全部为政府官网具体页面深链，2026 年内）
PROV_ITEMS = {
    "上海市": [{
        "date": "2026-08-27", "type": "政策宣贯", "domain": "平台合规",
        "title": "上海召开即时零售高质量发展行业交流暨政策宣贯会，落地《行动方案（2026-2028）》",
        "url": "https://www.shanghai.gov.cn/nw31406/20260828/1da9c35152004622a258bf0c11b2c9df.html",
        "note": "市商务委 9 部门 6 月联合印发《上海市支持即时零售高质量发展行动方案（2026—2028年）》"
                "（沪商电商〔2026〕178号），提出打造即时零售总部「第一城」，12 条措施细化为 30 余项工作举措："
                "优化前置仓选址支持、支持店仓一体、鼓励无人机/机器人配送、加强骑手驿站与新就业群体服务管理。"}],
    "山西省": [{
        "date": "2026-05-07", "type": "行政约谈", "domain": "食品合规",
        "title": "山西省、太原市两级市场监管局联合集体约谈全省外卖平台",
        "url": "https://scjgj.taiyuan.gov.cn/sjdt/20260509/30297306.html",
        "note": "落实总局 123 号令，省委网信办、公安厅等七部门参会，美团、淘宝闪购、京东、抖音等平台与省内备案平台 200 余人参加。"
                "聚焦「幽灵外卖」、一证多店、证照信息不一致，要求问题清单化、闭环式整改，平台现场签订《承诺书》。"}],
    "辽宁省": [{
        "date": "2026-03-18", "type": "执法约谈", "domain": "食品合规",
        "title": "沈阳市市场监管局对三大网络餐饮平台开展执法约谈",
        "url": "https://scj.shenyang.gov.cn/tpxx/202603/t20260318_5001391.html",
        "note": "围绕 123 号令压实平台责任：入网资质线上核验 + 线下实地抽查、证照信息线上公示、"
                "常态化数据报送；对「幽灵外卖」、无证无照、套证借证「零容忍」，问题商户坚决下线。"}],
    "江西省": [
        {"date": "2026-06", "type": "行政约谈", "domain": "食品合规",
         "title": "江西省市场监管局约谈美团、淘宝闪购、京东外卖在赣负责人",
         "url": "https://amr.jiangxi.gov.cn/amr/sjdt/content/content_2074340051348267008.html",
         "note": "结合亮证亮照专项解读 123 号令：运营机构台账全量梳理与合规自查、监管数据全量获取与白名单机制、"
                 "骑手权益保障与网约配送合作机制建设。"},
        {"date": "2026-02-10", "type": "行政约谈", "domain": "食品合规",
         "title": "江西省市场监管局集中约谈网约配送企业，通报「幽灵外卖」典型案例",
         "url": "https://amr.jiangxi.gov.cn/amr/sjdt/content/content_2021788454815272960.html",
         "note": "针对「幽灵外卖」、网络抽检不合格等突出问题，指出平台在商户资质审核、日常巡查、质量管控上的短板，"
                 "要求限期整改并报告结果，逾期未改将依法从严处理。"},
        {"date": "2026-06-02", "type": "行政约谈", "domain": "食品合规",
         "title": "抚州市临川区：123 号令实施 24 小时内约谈平台运营机构",
         "url": "https://fzscj.jxfz.gov.cn/art/2026/6/5/art_5623_4453996.html",
         "note": "五项硬性要求：严审入网资质清理「幽灵外卖」、推进「互联网+明厨亮灶」并对接省智慧监管平台、"
                 "无堂食商户显著标识、外卖封签「出餐必封、一餐一封」、建立政企协同与骑手「一线巡查员」机制。"}],
    "湖南省": [{
        "date": "2026-08-24", "type": "行政约谈", "domain": "食品合规",
        "title": "湖南省市场监管局约谈美团、淘宝闪购、京东网络餐饮平台区域负责人",
        "url": "https://amr.hunan.gov.cn/amr/xxx/xtdtx/202608/t20260825_34050618.html",
        "note": "通报入网商户资质审核不严、食品安全责任落实不到位、骑手权益保障缺失等问题："
                "依法按时核验更新商户登记信息、常态化配送员安全培训与健康资质审核、全面落实外卖封签与餐箱消杀制度。"}],
    "广西壮族自治区": [{
        "date": "2026-06-01", "type": "集体约谈", "domain": "食品合规",
        "title": "河池市召开网络食品交易第三方平台集体约谈会",
        "url": "http://scjgj.hechi.gov.cn/xwzx/gzdt/t27755170.shtml",
        "note": "宣贯 123 号令并提出「三个绝不」：月底前完成入网商户全覆盖穿透式核查、全面清除「幽灵外卖」；"
                "代理商按时限向自治区局报告；严格落实每 6 个月一次的商户信息实地核验并留存记录。"}],
    "陕西省": [{
        "date": "2026-03-16", "type": "行政指导", "domain": "食品合规",
        "title": "西安市高陵区约谈网络餐饮外卖运营商，部署 123 号令重点任务",
        "url": "http://www.gaoling.gov.cn/ztzl/rdzt/fzzfjs/pfxc/2039271935049760770.html",
        "note": "要求资质实质性审查、线上线下一致，清理无证、套证、超范围经营及「幽灵外卖」；"
                "推广食安封签、规范配送容器消杀、推进「互联网+明厨亮灶」，发挥骑手监督员作用。"}],
}

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
    print(f"provinces={len(provs)} items={n_items} -> {DST}")
    sizes = sorted(len(p["path"]) for p in provs)
    print("path size min/med/max:", sizes[0], sizes[len(sizes)//2], sizes[-1])


if __name__ == "__main__":
    main()
