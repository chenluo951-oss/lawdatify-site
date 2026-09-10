#!/usr/bin/env python3
"""
合规义务的「参考设计」界面稿：返回内联 SVG 字符串，供 build_standards.py 内嵌。

设计约定：
- 画幅 720 宽，手机稿统一 720×300（左手机 + 右说明），面板稿 720×260。
- 全部使用浅色主题，与站点配色一致（主色 #1b4f8a，点缀 #0f7b6c，警示 #c0392b）。
- 只画「合规要点示意」，不还原任何具体 App 的真实界面元素与品牌标识。
"""
from html import escape

INK = "#1c2733"
MUTED = "#5b6b7c"
FAINT = "#8a99a8"
LINE = "#dde5ed"
BG = "#ffffff"
SOFT = "#f5f8fb"
BRAND = "#1b4f8a"
TEAL = "#0f7b6c"
WARN = "#c0392b"
AMBER = "#b45309"


def _phone(x, w=232, h=290, title="朴朴", sub=""):
    """手机外框。"""
    return f"""<g>
<rect x="{x}" y="14" width="{w}" height="{h}" rx="26" fill="#101820"/>
<rect x="{x+6}" y="20" width="{w-12}" height="{h-12}" rx="21" fill="{BG}"/>
<rect x="{x+6}" y="20" width="{w-12}" height="26" rx="21" fill="{SOFT}"/>
<rect x="{x+6}" y="38" width="{w-12}" height="8" fill="{SOFT}"/>
<text x="{x+w/2}" y="38" text-anchor="middle" font-size="11" fill="{MUTED}" font-family="system-ui,-apple-system,Segoe UI,PingFang SC,sans-serif">{escape(title)}</text>
</g>"""


def _note(lines, x=470, y=54, w=232, color=BRAND, title="合规要点"):
    """右侧说明。"""
    out = [f'<text x="{x}" y="{y}" font-size="12.5" font-weight="700" fill="{color}" '
           f'font-family="system-ui,-apple-system,Segoe UI,PingFang SC,sans-serif">{escape(title)}</text>']
    yy = y + 22
    for ln in lines:
        out.append(f'<circle cx="{x+5}" cy="{yy-4}" r="2.4" fill="{color}" opacity=".55"/>')
        out.append(f'<text x="{x+14}" y="{yy}" font-size="11.6" fill="{INK}" '
                   f'font-family="system-ui,-apple-system,Segoe UI,PingFang SC,sans-serif">{escape(ln)}</text>')
        yy += 21
    return "".join(out)


def _wrap(inner, h=320):
    return (f'<svg viewBox="0 0 720 {h}" xmlns="http://www.w3.org/2000/svg" '
            f'font-family="system-ui,-apple-system,Segoe UI,PingFang SC,sans-serif" '
            f'role="img">{inner}</svg>')


# ---------------- App 类 ----------------

def perm_dialog():
    """权限弹窗：场景触发时同步告知目的。"""
    x = 40
    inner = _phone(x, 232, 292, "下单页")
    # 场景说明浮层
    inner += f"""
<rect x="{x+6}" y="46" width="220" height="238" rx="21" fill="#0d141c" opacity=".38"/>
<rect x="{x+26}" y="96" width="180" height="132" rx="14" fill="{BG}"/>
<circle cx="{x+116}" cy="126" r="17" fill="#eaf3fb"/>
<path d="M{x+116} 118 a7 7 0 1 1 0 14 a7 7 0 1 1 0 -14 M{x+109} 133 h14 l-7 11 z" fill="{BRAND}"/>
<text x="{x+116}" y="158" text-anchor="middle" font-size="12.5" font-weight="700" fill="{INK}">获取位置信息</text>
<text x="{x+116}" y="175" text-anchor="middle" font-size="10.4" fill="{MUTED}">用于匹配最近门店与配送</text>
<text x="{x+116}" y="190" text-anchor="middle" font-size="10.4" fill="{MUTED}">仅下单时获取，不在后台读取</text>
<line x1="{x+26}" y1="199" x2="{x+206}" y2="199" stroke="{LINE}"/>
<text x="{x+79}" y="215" text-anchor="middle" font-size="11.4" fill="{MUTED}">不允许</text>
<text x="{x+153}" y="215" text-anchor="middle" font-size="11.4" font-weight="700" fill="{BRAND}">使用时允许</text>
"""
    inner += _note(["弹窗标题即写清用途", "说明频率与是否后台调用", "拒绝后不再反复弹窗", "基本功能不得捆绑授权"], 300, 60)
    return _wrap(inner)


def sdk_list():
    """第三方信息共享清单。"""
    x = 40
    inner = _phone(x, 232, 292, "设置 · 隐私")
    rows = [
        ("推送 SDK", "设备标识 · 网络", "消息推送"),
        ("支付 SDK", "订单 · 设备", "完成支付"),
        ("地图 SDK", "位置 · 设备", "配送轨迹"),
        ("统计 SDK", "设备 · 行为", "产品优化"),
    ]
    yy = 56
    inner += f'<text x="{x+22}" y="{yy}" font-size="11.6" font-weight="700" fill="{INK}">第三方信息共享清单</text>'
    yy += 8
    for nm, fld, use in rows:
        yy += 34
        inner += (f'<rect x="{x+20}" y="{yy}" width="192" height="30" rx="7" fill="{SOFT}" stroke="{LINE}"/>'
                  f'<text x="{x+28}" y="{yy+13}" font-size="10.2" font-weight="700" fill="{INK}">{nm}</text>'
                  f'<text x="{x+28}" y="{yy+25}" font-size="9" fill="{MUTED}">{fld}</text>'
                  f'<text x="{x+200}" y="{yy+19}" text-anchor="end" font-size="9" fill="{TEAL}">{use}</text>')
    inner += (f'<text x="{x+22}" y="{yy+52}" font-size="8.8" fill="{FAINT}">'
              f'每一项均可点击查看第三方隐私政策</text>')
    inner += _note(["清单覆盖技术实测到的全部 SDK", "标注敏感字段：IMEI/位置/应用列表", "附第三方官网隐私政策链接", "SDK 升级后同步更新"], 300, 60)
    return _wrap(inner)


def splash_ad():
    """开屏广告：一键关闭 / 可跳过。"""
    x = 40
    inner = _phone(x, 232, 292, "开屏")
    inner += f"""
<rect x="{x+6}" y="46" width="220" height="238" rx="0" fill="#e9eef4"/>
<rect x="{x+6}" y="46" width="220" height="196" fill="#dfe7ef"/>
<circle cx="{x+116}" cy="140" r="30" fill="#cdd9e6"/>
<text x="{x+116}" y="145" text-anchor="middle" font-size="10.5" fill="{MUTED}">广告内容区</text>
<rect x="{x+6}" y="242" width="220" height="42" fill="{BG}"/>
<text x="{x+116}" y="268" text-anchor="middle" font-size="10.4" fill="{FAINT}">品牌标识</text>
<rect x="{x+176}" y="56" width="42" height="22" rx="11" fill="{BG}" stroke="{LINE}"/>
<text x="{x+197}" y="71" text-anchor="middle" font-size="10" fill="{MUTED}">跳过 3s</text>
<circle cx="{x+224}" cy="122" r="9" fill="{BG}" stroke="{LINE}"/>
<path d="M{x+220} 118 l8 8 M{x+228} 118 l-8 8" stroke="{MUTED}" stroke-width="1.5"/>
"""
    inner += _note(["关闭标志显著、可清晰辨识", "一次点击即关，不得需两次以上", "不得计时结束才能关闭", "关闭后同页面不再弹出"], 300, 60)
    return _wrap(inner)


def shake_ad():
    """摇一摇广告：常驻提示 + 独立关闭。"""
    x = 40
    inner = _phone(x, 232, 292, "首页")
    inner += f"""
<rect x="{x+6}" y="46" width="220" height="238" fill="#f2f5f9"/>
<rect x="{x+6}" y="46" width="220" height="150" fill="#dfe7ef"/>
<circle cx="{x+116}" cy="120" r="26" fill="#cdd9e6"/>
<g transform="rotate(-18 {x+116} 120)">
<rect x="{x+112}" y="98" width="8" height="44" rx="4" fill="#9fb2c6"/>
<rect x="{x+104}" y="106" width="24" height="28" rx="3" fill="none" stroke="#9fb2c6" stroke-width="1.4"/>
</g>
<text x="{x+116}" y="164" text-anchor="middle" font-size="10.4" fill="{MUTED}">摇动手机可查看详情</text>
<rect x="{x+56}" y="200" width="120" height="30" rx="15" fill="{BG}" stroke="{LINE}"/>
<text x="{x+116}" y="219" text-anchor="middle" font-size="10.6" fill="{BRAND}">跳过本条广告</text>
<text x="{x+116}" y="252" text-anchor="middle" font-size="9" fill="{FAINT}">提示条常驻，非浮层一闪而过</text>
"""
    inner += _note(["摇动提示在广告全程可见", "需明显甩动才触发", "（加速度≥15m/s²·角≥35°·≥3s）", "提供独立关闭，非只能摇进落地页"], 300, 60)
    return _wrap(inner)


def auto_renew():
    """自动续费：价格显著 + 提前提醒 + 便捷取消。"""
    inner = _phone(40, 232, 292, "会员 · 连续包月")
    inner += f"""
<rect x="46" y="52" width="220" height="60" rx="10" fill="{SOFT}" stroke="{LINE}"/>
<text x="60" y="72" font-size="10.4" fill="{MUTED}">连续包月</text>
<text x="60" y="94" font-size="19" font-weight="800" fill="{WARN}">¥9.9</text>
<text x="104" y="94" font-size="10" fill="{MUTED}">/月 · 每月 8 日自动扣费</text>
<text x="60" y="128" font-size="10.2" fill="{INK}">扣费前 5 日将提醒你</text>
<text x="60" y="146" font-size="10.2" fill="{INK}">可随时关闭，关闭后当期可用至到期日</text>
<rect x="60" y="160" width="192" height="30" rx="15" fill="{BRAND}"/>
<text x="156" y="180" text-anchor="middle" font-size="11" fill="#fff">同意并开通</text>
<line x1="46" y1="208" x2="266" y2="208" stroke="{LINE}"/>
<text x="60" y="228" font-size="10" fill="{MUTED}">设置 › 支付设置 › 自动续费</text>
<text x="60" y="248" font-size="10.6" font-weight="700" fill="{TEAL}">[ 一键关闭 ]</text>
<text x="60" y="270" font-size="9" fill="{FAINT}">取消路径不深于开通路径</text>
"""
    inner += _note(["首期价与续期价同等显著", "提前 5 日双通道提醒（含金额/扣款日）", "取消入口不深于开通路径", "关闭后明确告知有效期"], 300, 60)
    return _wrap(inner)


def personalization_off():
    """个性化推荐关闭开关。"""
    inner = _phone(40, 232, 292, "设置 · 隐私")
    inner += f"""
<rect x="46" y="56" width="220" height="72" rx="10" fill="#f7f9fc" stroke="{LINE}"/>
<text x="60" y="76" font-size="11.6" font-weight="700" fill="{INK}">个性化推荐</text>
<text x="60" y="92" font-size="9.4" fill="{MUTED}">根据浏览与购买记录推荐商品</text>
<text x="60" y="108" font-size="9.4" fill="{MUTED}">关闭后仅看非个性化通用内容</text>
<rect x="214" y="72" width="38" height="20" rx="10" fill="{TEAL}"/>
<circle cx="241" cy="82" r="8" fill="#fff"/>
<rect x="46" y="140" width="220" height="34" rx="8" fill="{SOFT}" stroke="{LINE}"/>
<text x="60" y="161" font-size="10.4" fill="{INK}">清除已生成的兴趣标签</text>
<text x="252" y="161" text-anchor="end" font-size="10" fill="{BRAND}">去清除 ›</text>
<rect x="46" y="182" width="220" height="34" rx="8" fill="{SOFT}" stroke="{LINE}"/>
<text x="60" y="203" font-size="10.4" fill="{INK}">单条内容「减少此类推荐」</text>
<text x="252" y="203" text-anchor="end" font-size="10" fill="{BRAND}">已开启 ›</text>
<text x="60" y="238" font-size="9" fill="{FAINT}">关闭须真实生效，不得仅隐藏入口</text>
"""
    inner += _note(["总开关 + 单条反馈双通道", "支持清除已生成标签", "关闭后须有通用内容兜底", "自动化决策需另提供说明与拒绝"], 300, 60)
    return _wrap(inner)


def privacy_policy():
    """隐私政策摘要表。"""
    inner = _phone(40, 232, 292, "隐私政策 · 摘要")
    inner += f"""
<text x="46" y="62" font-size="11.6" font-weight="700" fill="{INK}">我们收集什么、为什么、是否共享</text>
<rect x="46" y="72" width="220" height="22" rx="4" fill="{BRAND}" opacity=".08"/>
<text x="52" y="87" font-size="9" fill="{BRAND}">信息类型</text>
<text x="120" y="87" font-size="9" fill="{BRAND}">使用场景</text>
<text x="262" y="87" text-anchor="end" font-size="9" fill="{BRAND}">是否共享</text>
"""
    rows = [("手机号", "登录·配送联系", "配送商"), ("位置", "门店匹配", "不共享"),
            ("设备信息", "风控防刷", "安全商"), ("订单", "履约售后", "不共享")]
    yy = 94
    for a, b, c in rows:
        yy += 24
        inner += (f'<line x1="46" y1="{yy+8}" x2="266" y2="{yy+8}" stroke="{LINE}"/>'
                  f'<text x="52" y="{yy}" font-size="9.6" fill="{INK}">{a}</text>'
                  f'<text x="120" y="{yy}" font-size="9" fill="{MUTED}">{b}</text>'
                  f'<text x="262" y="{yy}" text-anchor="end" font-size="9" fill="{MUTED}">{c}</text>')
    inner += (f'<text x="46" y="{yy+34}" font-size="9" fill="{FAINT}">每项均标注保存期限，可展开完整版</text>')
    inner += _note(["简明摘要 + 完整版双形态", "区分「必需 / 可选」", "逐项写明保存期限", "敏感信息触发时单独告知"], 300, 60)
    return _wrap(inner)


# ---------------- 面板类 ----------------

def _panel(title, rows, note, h=250, note_color=BRAND):
    inner = f'<rect x="24" y="18" width="404" height="{h-40}" rx="10" fill="{BG}" stroke="{LINE}"/>'
    inner += (f'<rect x="24" y="18" width="404" height="34" rx="10" fill="{SOFT}"/>'
              f'<rect x="24" y="44" width="404" height="8" fill="{SOFT}"/>'
              f'<text x="42" y="40" font-size="12" font-weight="700" fill="{INK}">{escape(title)}</text>')
    yy = 74
    for k, v, tone in rows:
        inner += (f'<text x="42" y="{yy}" font-size="10.6" fill="{MUTED}">{escape(k)}</text>'
                  f'<text x="150" y="{yy}" font-size="10.8" fill="{tone}">{escape(v)}</text>')
        yy += 24
    inner += _note(note, 452, 46, w=250, color=note_color)
    return _wrap(inner, h)


def algo_filing():
    return _panel("算法备案公示 · 设置 › 关于 › 算法备案",
                  [("备案编号", "网信算备 00000000 号", INK),
                   ("算法类型", "生成合成类 / 个性化推送类", INK),
                   ("应用形态", "[App] 智能客服 · 商品推荐", INK),
                   ("公示日期", "2026-09-10", INK),
                   ("用户权益", "关闭个性化推荐 · 删除兴趣标签", TEAL),
                   ("投诉入口", "已公示邮箱与电话", TEAL)],
                  ["公示内容须与实际运行算法一致", "须同时提供「关闭推荐」入口", "模型/用途变更后 10 日内更新备案", "备案号在产品内可查"])


def ai_badge():
    """AI 生成内容标识：显式角标 + 隐式元数据。"""
    inner = f"""
<rect x="24" y="18" width="200" height="132" rx="10" fill="#dfe7ef"/>
<circle cx="124" cy="82" r="26" fill="#cdd9e6"/>
<rect x="170" y="130" width="46" height="18" rx="4" fill="#101820" opacity=".72"/>
<text x="193" y="143" text-anchor="middle" font-size="9.6" fill="#fff">AI 生成</text>
<text x="124" y="172" text-anchor="middle" font-size="10.4" fill="{MUTED}">① 显式标识 · 首屏可见</text>

<rect x="248" y="18" width="200" height="132" rx="10" fill="{SOFT}" stroke="{LINE}"/>
<text x="266" y="42" font-size="10" font-weight="700" fill="{INK}">元数据（隐式标识）</text>
<text x="266" y="64" font-size="9.4" font-family="ui-monospace,Menlo,monospace" fill="{MUTED}">AIGC: true</text>
<text x="266" y="82" font-size="9.4" font-family="ui-monospace,Menlo,monospace" fill="{MUTED}">Generator: [服务名]</text>
<text x="266" y="100" font-size="9.4" font-family="ui-monospace,Menlo,monospace" fill="{MUTED}">ProducedAt: [时间]</text>
<text x="266" y="126" font-size="9" fill="{FAINT}">压缩 / 二次编辑后仍须保留</text>
<text x="348" y="172" text-anchor="middle" font-size="10.4" fill="{MUTED}">② 隐式标识 · 文件元数据</text>

<rect x="24" y="188" width="424" height="42" rx="8" fill="#fff7f0" stroke="#f2d9c0"/>
<text x="40" y="206" font-size="10.4" fill="{AMBER}">③ 传播平台三档判定</text>
<text x="40" y="222" font-size="9.6" fill="{MUTED}">属于 / 可能为 / 疑似 —— 措辞不得混用，去标识须留存日志 ≥6 个月</text>
"""
    return _wrap(inner, 244)


def self_operated():
    """自营 / 他营区分标识。"""
    inner = f"""
<rect x="24" y="20" width="200" height="196" rx="10" fill="{BG}" stroke="{LINE}"/>
<rect x="36" y="32" width="176" height="106" rx="8" fill="#eef3f9"/>
<circle cx="124" cy="80" r="26" fill="#d7e3f0"/>
<rect x="36" y="140" width="70" height="16" rx="3" fill="{BRAND}"/>
<text x="71" y="152" text-anchor="middle" font-size="9.4" fill="#fff">自营</text>
<text x="112" y="152" font-size="9.6" fill="{MUTED}">[商品名]</text>
<text x="36" y="172" font-size="10.4" font-weight="700" fill="{WARN}">¥35.80</text>
<text x="36" y="192" font-size="9.4" fill="{MUTED}">列表页即可区分，不得误导</text>

<rect x="248" y="20" width="200" height="196" rx="10" fill="{BG}" stroke="{LINE}"/>
<rect x="260" y="32" width="176" height="106" rx="8" fill="#eef3f9"/>
<circle cx="348" cy="80" r="26" fill="#d7e3f0"/>
<rect x="260" y="140" width="70" height="16" rx="3" fill="{TEAL}"/>
<text x="295" y="152" text-anchor="middle" font-size="9.4" fill="#fff">旗舰店</text>
<text x="336" y="152" font-size="9.6" fill="{MUTED}">[商家名]</text>
<text x="260" y="172" font-size="10.4" font-weight="700" fill="{WARN}">¥35.80</text>
<text x="260" y="192" font-size="9.4" fill="{MUTED}">须显著标明实际经营主体</text>

<rect x="24" y="228" width="424" height="40" rx="8" fill="#fff7f0" stroke="#f2d9c0"/>
<text x="40" y="245" font-size="10.2" fill="{AMBER}">生鲜不适用七日无理由退货</text>
<text x="40" y="261" font-size="9.4" fill="{MUTED}">须在下单前显著提示，而非仅在售后页说明</text>
"""
    return _wrap(inner, 280)


def price_tag():
    """价格标示：成交价 / 划线价依据 / 附加费前置。"""
    inner = f"""
<rect x="24" y="20" width="424" height="230" rx="10" fill="{BG}" stroke="{LINE}"/>
<text x="44" y="50" font-size="11.6" font-weight="700" fill="{INK}">有机小白菜 500g</text>

<text x="44" y="86" font-size="26" font-weight="800" fill="{WARN}">¥35.80</text>
<text x="140" y="86" font-size="11" fill="{MUTED}">／500g</text>
<text x="196" y="86" font-size="11.4" fill="{FAINT}">¥45.80</text>
<line x1="196" y1="82" x2="242" y2="82" stroke="{FAINT}"/>
<text x="44" y="106" font-size="9.4" fill="{MUTED}">划线价：本平台近 7 日最低成交价，2026-09-03 成交</text>

<rect x="44" y="118" width="384" height="34" rx="7" fill="{SOFT}" stroke="{LINE}"/>
<text x="58" y="133" font-size="10" fill="{MUTED}">配送费 ¥3.00</text>
<text x="152" y="133" font-size="10" fill="{MUTED}">包装费 ¥1.00</text>
<text x="58" y="147" font-size="9" fill="{TEAL}">加购前即展示，不在结算时出现</text>

<line x1="44" y1="168" x2="408" y2="168" stroke="{LINE}"/>
<text x="44" y="190" font-size="10.4" font-weight="700" fill="{WARN}">不合规示例</text>
<text x="44" y="210" font-size="9.6" fill="{MUTED}">「原价 ¥199」— 无本平台成交记录支撑</text>
<text x="44" y="226" font-size="9.6" fill="{MUTED}">「市场价 ¥299」— 无从比较</text>
<text x="252" y="210" font-size="9.6" fill="{MUTED}">结算时才出现的「包装费 ¥2」</text>
<text x="252" y="226" font-size="9.6" fill="{MUTED}">套餐价 = 单品价简单累加的虚假优惠</text>
"""
    return _wrap(inner, 262)


def food_label():
    """前置仓分装标签。"""
    inner = f"""
<rect x="24" y="20" width="300" height="230" rx="6" fill="#fff" stroke="{INK}" stroke-width="1.6"/>
<text x="174" y="48" text-anchor="middle" font-size="13" font-weight="800" fill="{INK}">有机小白菜</text>
<line x1="44" y1="58" x2="304" y2="58" stroke="{INK}" stroke-width="1"/>

<rect x="44" y="70" width="260" height="34" rx="4" fill="#f2f5f9" stroke="{LINE}"/>
<text x="56" y="84" font-size="9" fill="{MUTED}">生产日期 / 分装日期</text>
<text x="56" y="99" font-size="13" font-weight="800" fill="{INK}">2026-09-10</text>
<text x="292" y="84" text-anchor="end" font-size="9" fill="{MUTED}">保质期至</text>
<text x="292" y="99" text-anchor="end" font-size="13" font-weight="800" fill="{WARN}">2026-09-13</text>

<text x="44" y="124" font-size="9.6" fill="{MUTED}">原生产者　[名称] [地址]</text>
<text x="44" y="144" font-size="9.6" fill="{MUTED}">分装者　　[xx仓] [地址] [电话]</text>
<text x="44" y="164" font-size="9.6" fill="{MUTED}">贮存条件　0-4℃ 冷藏</text>
<text x="44" y="184" font-size="9.6" fill="{MUTED}">净含量　　称重计重</text>

<rect x="44" y="194" width="260" height="22" rx="3" fill="#fdecea" stroke="#f3cfc9"/>
<text x="56" y="209" font-size="9.6" font-weight="700" fill="{WARN}">致敏物质提示：含花生、乳制品</text>
<text x="174" y="238" text-anchor="middle" font-size="9" fill="{FAINT}">白底黑字 · 日期独立区域 · 字高 ≥3.0mm</text>

<rect x="348" y="20" width="100" height="230" rx="8" fill="{SOFT}" stroke="{LINE}"/>
<text x="398" y="44" text-anchor="middle" font-size="10.4" font-weight="700" fill="{BRAND}">为什么这样贴</text>
"""
    for i, t in enumerate(["拆箱称重已纳入", "预包装食品监管", "（GB 7718-2025）", "", "第 33 条第 2 款：", "须按散装食品", "标明全部信息", "", "委托方与受托方", "须并列标注"]):
        inner += (f'<text x="398" y="{66+i*17}" text-anchor="middle" font-size="9.4" '
                  f'fill="{MUTED}">{t}</text>')
    return _wrap(inner, 262)


MOCKUPS = {
    "perm_dialog": ("App 权限索取弹窗：场景触发 + 目的同步告知", perm_dialog),
    "sdk_list": ("第三方信息共享清单（隐私政策内）", sdk_list),
    "splash_ad": ("开屏广告：显著关闭标志 + 一键关闭", splash_ad),
    "shake_ad": ("摇一摇广告：常驻提示 + 独立跳过", shake_ad),
    "auto_renew": ("自动续费：价格显著 + 提前提醒 + 便捷取消", auto_renew),
    "personalization_off": ("个性化推荐：总开关 + 清除标签", personalization_off),
    "privacy_policy": ("隐私政策摘要：收集什么 / 为何 / 是否共享", privacy_policy),
    "algo_filing": ("算法备案公示页", algo_filing),
    "ai_badge": ("AI 生成内容标识：显式角标 + 隐式元数据", ai_badge),
    "self_operated": ("自营与他营区分标识", self_operated),
    "price_tag": ("商品页价格标示：成交价 / 划线价依据 / 附加费前置", price_tag),
    "food_label": ("前置仓分装标签版面", food_label),
}


def render(key):
    """返回 (标题, svg字符串)，key 不存在返回 None。"""
    if key not in MOCKUPS:
        return None
    title, fn = MOCKUPS[key]
    try:
        return title, fn()
    except Exception:
        return None
