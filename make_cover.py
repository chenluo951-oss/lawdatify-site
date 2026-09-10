#!/usr/bin/env python3
"""生成社会化分享封面图 assets/og-cover.png（1200×630）。

为什么不用 AI 生图：一是要消耗额度，二是中文在生成图里容易糊，
三是og:image 上平台会自动叠加 og:title，图上再写标题反而重复。
这里用 Pillow 本地绘制，零成本、中文锐利、可重复生成。

用法：
    python3 make_cover.py            # 生成（覆盖）
"""

import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets", "og-cover.png")

W, H = 1200, 630

# 品牌配色（与 assets/style.css 的 hero 渐变保持一致）
C_TL = (18, 55, 92)      # #12375c
C_MID = (27, 79, 138)    # #1b4f8a
C_BR = (15, 123, 108)    # #0f7b6c


def find_font(size: int, prefer_medium=True):
    """挑一个可用的中文字体，按优先级回退。"""
    cands = [
        ("/System/Library/Fonts/STHeiti Medium.ttc", 2),
        ("/System/Library/Fonts/STHeiti Light.ttc", 2),
        ("/System/Library/Fonts/PingFang.ttc", 4),
        ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
    ]
    if not prefer_medium:
        cands = cands[1:]
    for path, idx in cands:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size, index=idx)
            except Exception:
                continue
    return ImageFont.load_default()


def gradient_bg():
    """对角渐变背景：小图绘制后放大，既快又平滑。"""
    sw, sh = W // 6, H // 6
    small = Image.new("RGB", (sw, sh))
    px = small.load()
    for y in range(sh):
        for x in range(sw):
            t = (x / max(sw - 1, 1)) * 0.5 + (y / max(sh - 1, 1)) * 0.5
            if t < 0.5:
                k = t / 0.5
                c = tuple(int(C_TL[i] + (C_MID[i] - C_TL[i]) * k) for i in range(3))
            else:
                k = (t - 0.5) / 0.5
                c = tuple(int(C_MID[i] + (C_BR[i] - C_MID[i]) * k) for i in range(3))
            px[x, y] = c
    return small.resize((W, H), Image.LANCZOS)


def radial(size, inner=(255, 255, 255), alpha=42):
    """生成一块径向光晕，用于 corporate 风格的柔光点缀。"""
    r = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(r)
    cx = cy = size / 2
    steps = size // 2
    for i in range(steps, 0, -2):
        v = int(alpha * (1 - i / steps) ** 2)
        d.ellipse([cx - i, cy - i, cx + i, cy + i], fill=v)
    layer = Image.new("RGBA", (size, size), tuple(inner[:3]) + (0,))
    layer.putalpha(r)
    return layer


def main():
    img = gradient_bg().convert("RGBA")

    # 右上角柔光
    glow = radial(760)
    img.alpha_composite(glow, dest=(W - 560, -180))

    d = ImageDraw.Draw(img)

    # ---- 右侧装饰：同心环 + 节点连线，隐喻「规则 / 监管网络」 ----
    cx, cy = 1010, 300
    for rr, wdt, op in ((250, 1, 38), (188, 1, 30), (126, 1, 24)):
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                  outline=(255, 255, 255, op), width=wdt)
    nodes = [(cx, cy - 126), (cx + 109, cy - 63), (cx + 109, cy + 63),
             (cx, cy + 126), (cx - 109, cy + 63), (cx - 109, cy - 63)]
    # 六边形轮廓 + 中心辐条（网络感）。注意不能用隔点连线 (i+2)%6，
    # 那会画出六芒星图案，对外场合有宗教联想风险。
    for i in range(len(nodes)):
        x1, y1 = nodes[i]
        x2, y2 = nodes[(i + 1) % len(nodes)]
        d.line([x1, y1, x2, y2], fill=(255, 255, 255, 34), width=1)
    for x, y in nodes:
        d.line([cx, cy, x, y], fill=(255, 255, 255, 20), width=1)
    d.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=(255, 255, 255, 120))
    for x, y in nodes:
        d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=(255, 255, 255, 150))

    # ---- 左侧文字区 ----
    L = 88
    f_eye = find_font(21)
    f_h1 = find_font(66)
    f_sub = find_font(28)
    f_foot = find_font(23)

    d.text((L, 150), "LEGAL & COMPLIANCE HUB", font=f_eye, fill=(255, 255, 255, 165))

    # 标题略带字距感：Pillow 无字距参数，用逐字绘制实现
    title = "即时零售合规主站"
    x = L
    y = 208
    for ch in title:
        d.text((x, y), ch, font=f_h1, fill=(255, 255, 255, 255))
        x += f_h1.getlength(ch) + 6
    title_w = x - L - 6

    # 标题下细分隔线
    d.line([L, y + 92, L + 92, y + 92], fill=(255, 255, 255, 130), width=3)

    d.text((L, 340), "六大领域监管动态 · 逐条官方深链", font=f_sub, fill=(214, 232, 240, 255))
    d.text((L, 382), "可溯源的合规资讯与分析", font=f_sub, fill=(214, 232, 240, 255))

    # ---- 右下落款 ----
    brand = "合规无终点"
    bw = f_foot.getlength(brand)
    d.text((W - 88 - bw, H - 78), brand, font=f_foot, fill=(255, 255, 255, 200))
    d.line([W - 88 - bw - 18, H - 62, W - 88 - bw - 18, H - 114],
           fill=(255, 255, 255, 90), width=2)

    img.convert("RGB").save(OUT, "PNG", optimize=True)
    size_kb = os.path.getsize(OUT) / 1024
    print(f"封面图已生成：{OUT}")
    print(f"  尺寸 {W}×{H}, 体积 {size_kb:.0f} KB (标题宽 {title_w:.0f}px)")


if __name__ == "__main__":
    main()
