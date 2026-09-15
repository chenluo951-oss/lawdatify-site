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


# ---------------- 通用版式：面板 / 步骤 / 卡片 / 证照 ----------------

def _panel_block(title, h, tone=None, w=424):
    """左侧面板外框 + 标题条。h 为面板高度（自 y=18 起）。"""
    inner = (f'<rect x="24" y="18" width="{w}" height="{h}" rx="10" fill="{BG}" stroke="{LINE}"/>'
             f'<rect x="24" y="18" width="{w}" height="34" rx="10" fill="{SOFT}"/>'
             f'<rect x="24" y="44" width="{w}" height="8" fill="{SOFT}"/>'
             f'<text x="42" y="40" font-size="12" font-weight="700" fill="{INK}">{escape(title)}</text>')
    if tone:
        inner += f'<rect x="24" y="18" width="3" height="{h}" rx="1.5" fill="{tone}"/>'
    return inner


def _steps(title, steps, note, tone=BRAND, note_title="合规要点"):
    """编号纵向步骤面板。steps = [(标题, 说明)]。"""
    n = len(steps)
    ph = 76 + n * 38
    inner = _panel_block(title, ph - 18, tone=tone)
    y = 74
    for i, item in enumerate(steps):
        t = item[0]
        d = item[1] if len(item) > 1 else ""
        inner += (f'<circle cx="42" cy="{y-4}" r="9.5" fill="{tone}" opacity=".12"/>'
                  f'<text x="42" y="{y-0.5}" text-anchor="middle" font-size="10" '
                  f'font-weight="700" fill="{tone}">{i+1}</text>'
                  f'<text x="60" y="{y-0.5}" font-size="10.8" font-weight="700" fill="{INK}">{escape(t)}</text>')
        if d:
            inner += f'<text x="60" y="{y+14.5}" font-size="9.6" fill="{MUTED}">{escape(d)}</text>'
        y += 38
    inner += _note(note, 452, 46, w=250, color=tone, title=note_title)
    return _wrap(inner, ph + 30)


def _cards(title, cards, note, tone=BRAND, note_title="合规要点"):
    """两列卡片面板。cards = [(标题, 行1, 行2)]。"""
    rows = (len(cards) + 1) // 2
    ph = 66 + rows * 84
    inner = _panel_block(title, ph - 18, tone=tone)
    for i, c in enumerate(cards):
        t = c[0]
        l1 = c[1] if len(c) > 1 else ""
        l2 = c[2] if len(c) > 2 else ""
        cx = 42 + (i % 2) * 206
        cy = 62 + (i // 2) * 84
        inner += (f'<rect x="{cx}" y="{cy}" width="194" height="74" rx="8" fill="{SOFT}" stroke="{LINE}"/>'
                  f'<text x="{cx+12}" y="{cy+22}" font-size="10.6" font-weight="700" fill="{INK}">{escape(t)}</text>')
        if l1:
            inner += f'<text x="{cx+12}" y="{cy+41}" font-size="9.4" fill="{MUTED}">{escape(l1)}</text>'
        if l2:
            inner += f'<text x="{cx+12}" y="{cy+57}" font-size="9.4" fill="{MUTED}">{escape(l2)}</text>'
    inner += _note(note, 452, 46, w=250, color=tone, title=note_title)
    return _wrap(inner, ph + 30)


def _doc(kicker, name, fields, foot, side_title, side_lines, h=232):
    """证照 / 标签 / 票证版面。fields = [(左侧标签, 右侧值)]，标签为空则整行左对齐。"""
    inner = (f'<rect x="24" y="18" width="300" height="{h}" rx="6" fill="#ffffff" '
             f'stroke="{INK}" stroke-width="1.6"/>'
             f'<text x="174" y="42" text-anchor="middle" font-size="9.6" fill="{MUTED}">{escape(kicker)}</text>'
             f'<text x="174" y="64" text-anchor="middle" font-size="13" font-weight="800" fill="{INK}">'
             f'{escape(name)}</text>'
             f'<line x1="44" y1="76" x2="304" y2="76" stroke="{INK}"/>')
    y = 96
    for f in fields:
        if f[0]:
            inner += (f'<text x="44" y="{y}" font-size="9.2" fill="{MUTED}">{escape(f[0])}</text>'
                      f'<text x="304" y="{y}" text-anchor="end" font-size="10.2" fill="{INK}">{escape(f[1])}</text>')
        else:
            inner += f'<text x="44" y="{y}" font-size="10.2" fill="{INK}">{escape(f[1])}</text>'
        y += 22
    if foot:
        inner += (f'<rect x="44" y="{y-8}" width="260" height="24" rx="3" fill="#fdecea" stroke="#f3cfc9"/>'
                  f'<text x="56" y="{y+9}" font-size="9.4" font-weight="700" fill="{WARN}">{escape(foot)}</text>')
    inner += (f'<rect x="348" y="18" width="100" height="{h}" rx="8" fill="{SOFT}" stroke="{LINE}"/>'
              f'<text x="398" y="42" text-anchor="middle" font-size="10.4" font-weight="700" '
              f'fill="{BRAND}">{escape(side_title)}</text>')
    for i, t in enumerate(side_lines):
        inner += (f'<text x="398" y="{64+i*17}" text-anchor="middle" font-size="9.4" '
                  f'fill="{MUTED}">{escape(t)}</text>')
    return _wrap(inner, h + 32)


def _board(title, rows, note, tone=BRAND):
    """键值面板（同 _panel，但可指定主色）。rows = [(键, 值, 色)]。"""
    ph = 74 + len(rows) * 24 + 16
    inner = _panel_block(title, ph - 18, tone=tone)
    y = 76
    for k, v, c in rows:
        inner += (f'<text x="42" y="{y}" font-size="10.4" fill="{MUTED}">{escape(k)}</text>'
                  f'<text x="150" y="{y}" font-size="10.6" fill="{c}">{escape(v)}</text>')
        y += 24
    inner += _note(note, 452, 46, w=250, color=tone)
    return _wrap(inner, ph + 30)


# ---------------- App：分发备案 / 自启动 / 自检 / 未成年人 ----------------

def self_start():
    """自启动与关联启动：默认关闭 + 用户可控。"""
    return _steps("自启动 · 关联启动治理",
                  [("开箱默认关闭", "自启动、关联启动、后台唤醒一律默认关闭，不随安装静默开启"),
                   ("触发场景白名单", "仅保留推送到达、扫码支付等确有必要的场景，逐项说明"),
                   ("用户可查可关", "「设置-应用管理-自启动」逐 App 展示状态与开关"),
                   ("拒绝不降功能", "关闭后基本功能不得受限，不得反复引导重新开启")],
                  ["是否默认关闭而非默认开启", "关闭自启动后推送是否仍可达（须走系统通道）",
                   "是否存在「关闭后功能不可用」的变相胁迫", "「优先使用前方应用」须与自启动分列"],
                  tone=TEAL)


def app_filing():
    """应用分发 / 备案 / 整改响应台账。"""
    return _board("应用分发与备案台账",
                  [("分发渠道", "应用商店 / 官网 / 企业内部分发", INK),
                   ("备案状态", "已完成 ICP 备案 · 编号已公示", TEAL),
                   ("分发备案", "应用商店分发者备案与 App 备案一致", INK),
                   ("版本比对", "上架版本 = 送检版本（含 SDK）", INK),
                   ("整改响应", "收到通报 [3] 个工作日内完成整改并回函", WARN),
                   ("留痕", "整改前后版本、检测报告归档", MUTED)],
                  ["分发渠道变化须同步更新备案", "不得出现「送检版干净、上架版夹带」",
                   "整改须留存前后版本与检测报告", "SDK 变更属重大变更，须重新自查"])


def pi_selfcheck():
    """个人信息收集使用检测与自查。"""
    return _steps("自查与检测机制",
                  [("工具化检测", "对权限调用、SDK 报送、后台采集做自动化抓包与静态扫描"),
                   ("上线前门禁", "新版本发布前必须过检测项，未通过不得提审"),
                   ("季度复核", "每季度按 GB/T 35273 与检测规范复核一次，出报告"),
                   ("整改闭环", "问题项登记 → 定责 → 修复 → 复测 → 关闭")],
                  ["是否有自动化检测而非人工抽查", "检测项是否随监管通报口径更新",
                   "问题项是否闭环（有复测记录）", "报告留存 ≥3 年备查"],
                  tone=TEAL)


def teen_mode():
    """未成年人模式：一键切换 + 时长与消费限制。"""
    x = 40
    inner = _phone(x, 232, 292, "设置 · 未成年人模式")
    inner += f"""
<rect x="{x+20}" y="54" width="192" height="52" rx="10" fill="#eef7f4" stroke="#cfe6df"/>
<text x="{x+32}" y="74" font-size="10.8" font-weight="700" fill="{TEAL}">未成年人模式</text>
<text x="{x+32}" y="90" font-size="9.2" fill="{MUTED}">一键开启 · 家长可设置监护密码</text>
<rect x="{x+186}" y="68" width="20" height="20" rx="10" fill="{TEAL}"/>
<text x="{x+22}" y="126" font-size="9.6" fill="{INK}">单日使用时长上限　[40] 分钟</text>
<text x="{x+22}" y="146" font-size="9.6" fill="{INK}">消费限额　单笔 [50] 元 · 单日 [100] 元</text>
<text x="{x+22}" y="166" font-size="9.6" fill="{INK}">直播与充值　关闭</text>
<text x="{x+22}" y="186" font-size="9.6" fill="{INK}">个性化推荐　关闭</text>
<text x="{x+22}" y="206" font-size="9.6" fill="{INK}">22:00—06:00 禁用</text>
<rect x="{x+20}" y="222" width="192" height="30" rx="15" fill="{BRAND}"/>
<text x="{x+116}" y="241" text-anchor="middle" font-size="10.6" fill="#fff">进入未成年人模式</text>
<text x="{x+116}" y="272" text-anchor="middle" font-size="8.8" fill="{FAINT}">退出需监护密码，不得仅凭一次点击</text>
"""
    inner += _note(["模式入口在首屏可达（非埋设置深层）", "退出须验证，防未成年人自行关闭",
                    "不满 14 周岁个人信息按敏感信息处理", "不得向未成年人推送诱导消费内容"], 300, 60)
    return _wrap(inner)


# ---------------- AI：语料 / 服务商 / 应用方 / 未成年人 ----------------

def train_data():
    """训练数据与语料合规。"""
    return _steps("训练数据与语料合规",
                  [("来源合法性", "逐批记录来源、授权凭证与取得方式，禁用非法获取与侵权语料"),
                   ("内容过滤", "入库前过滤违法有害信息、个人信息与敏感信息"),
                   ("标注规范", "人工标注须有规则、培训与质检抽样记录"),
                   ("可追溯", "语料—模型—版本链路可回溯，能按语料定位影响范围")],
                  ["是否留存语料来源凭证与授权链", "是否做个人信息与敏感信息清洗",
                   "标注外包是否签保密与合规条款", "语料变更后是否留存版本对照"],
                  tone=TEAL)


def ai_vendor():
    """AI 服务商与智能体治理。"""
    return _board("AI 服务商与智能体台账",
                  [("服务清单", "客服问答 / 选品文案 / 智能补货", INK),
                   ("服务商", "[名称] · 已核验备案编号 [xxxx]", INK),
                   ("数据处理", "是否用于其模型训练：[否]（合同明确）", TEAL),
                   ("智能体权限", "只读商品库；禁写订单与资金", WARN),
                   ("输出审核", "对外输出须过敏感词与事实校验", INK),
                   ("责任划分", "合同约定内容责任与追偿条款", MUTED)],
                  ["是否核验服务商备案/登记状态", "合同是否禁止用我方数据训练",
                   "智能体是否最小权限、可回滚", "输出是否有人工复核与投诉通道"])


def ai_app_reg():
    """AI 应用方（调用已备案模型）的登记与责任。"""
    return _steps("应用方登记与责任",
                  [("用途登记", "按功能逐项登记所用模型、用途、面向人群与是否具舆论属性"),
                   ("备案与登记", "具舆论属性的生成式 AI 功能须完成备案或登记"),
                   ("产品公示", "在「关于」页公示所用模型与备案/登记编号"),
                   ("变更同步", "换模型、改用途、扩人群均须重新评估并更新登记")],
                  ["是否误以为「用了已备案模型就无需登记」", "面向未成年人或公开传播的须重点评估",
                   "公示编号须与实际一致", "境外模型服务须评估数据出境与合规性"])


def ai_teen():
    """AI 与未成年人：内容与时长双管控。"""
    return _cards("AI 功能面向未成年人的管控",
                  [("内容边界", "禁止生成诱导消费、暴力低俗内容", "健康类回答须标注非医疗建议"),
                   ("身份识别", "未成年人模式下限制 AI 陪伴类功能", "不得以拟人化诱导长时间互动"),
                   ("时长与提醒", "连续交互 [20] 分钟提示休息", "夜间时段限制使用"),
                   ("告知与监护", "首屏告知 AI 非真人", "向监护人提供使用概览")],
                  ["是否有年龄识别与模式联动", "是否明确告知非真人而非模糊处理",
                   "AI 是否劝导情感依赖或消费", "监护人能否查看与限制"],
                  tone=AMBER)


# ---------------- 算法：主体责任 / 自动化决策 / 备案变更 ----------------

def algo_duty():
    """算法安全主体责任。"""
    return _board("算法安全主体责任清单",
                  [("责任主体", "法定代表人为第一责任人 · 设算法安全负责人", INK),
                   ("机制建设", "覆盖设计、开发、部署、运行全流程", INK),
                   ("风险监测", "对偏见歧视、诱导沉迷、舆论属性风险常态监测", WARN),
                   ("信息公示", "公示算法基本原理、目的意图与主要运行机制", INK),
                   ("应急处置", "发现隐患立即整改，重大风险停止服务并报告", WARN),
                   ("留痕", "算法日志不少于 [6] 个月", MUTED)],
                  ["是否指定算法安全负责人并有履职记录", "是否对算法风险做常态监测而非一次性评估",
                   "日志留存是否满足 6 个月", "停止服务的触发条件与决策记录是否留存"])


def auto_decision():
    """自动化决策：透明度 + 拒绝权。"""
    inner = _phone(40, 232, 292, "我的 · 服务说明")
    inner += f"""
<text x="46" y="62" font-size="11.6" font-weight="700" fill="{INK}">自动化决策说明</text>
<rect x="46" y="72" width="220" height="72" rx="8" fill="{SOFT}" stroke="{LINE}"/>
<text x="58" y="90" font-size="9.4" fill="{MUTED}">决策场景（对你有重大影响）</text>
<text x="58" y="106" font-size="9.8" fill="{INK}">券与补贴发放 · 会员权益分级 · 配送时效承诺</text>
<text x="58" y="124" font-size="9.4" fill="{MUTED}">主要依据：历史下单频率、履约情况、所在门店</text>
<rect x="46" y="154" width="220" height="30" rx="8" fill="#fff" stroke="{LINE}"/>
<text x="58" y="173" font-size="10.2" fill="{BRAND}">要求人工复核（对结果有异议）</text>
<rect x="46" y="190" width="220" height="30" rx="8" fill="#fff" stroke="{LINE}"/>
<text x="58" y="209" font-size="10.2" fill="{BRAND}">拒绝仅由自动化决策作出</text>
<text x="58" y="242" font-size="9" fill="{FAINT}">说明须具体到场景，不得只写「我们可能使用自动化决策」</text>
"""
    inner += _note(["重大影响场景须单独说明", "提供便捷的拒绝与人工复核入口",
                    "不得因拒绝而拒绝提供基本服务", "决策依据不得含敏感个人信息"], 300, 60)
    return _wrap(inner)


def algo_change():
    """备案变更、注销与公示。"""
    return _steps("备案变更 · 注销 · 公示",
                  [("变更识别", "算法类型、应用形态、主要机制、服务人群变化均属变更"),
                   ("时限遵守", "变更之日起 [10] 个工作日内办理变更手续"),
                   ("注销义务", "终止服务须办理注销并同步撤下公示"),
                   ("对外公示", "公示备案与变更情况，含变更内容与生效时间")],
                  ["是否有变更识别清单（避免漏报）", "变更是否留有时点记录以证明守时",
                   "终止服务是否做了注销而非只下线", "公示信息是否与备案系统保持一致"])


# ---------------- 平台治理 ----------------

def merchant_access():
    """商家与供应商准入审核。"""
    return _steps("商家与供应商准入",
                  [("资质核验", "营业执照、许可（食品经营等）逐项核验并留存编号与有效期"),
                   ("实地与背景核查", "高风险品类加做实地或第三方核查"),
                   ("协议与承诺", "签署平台规则、质量安全承诺与食品安全责任协议"),
                   ("动态管理", "证照到期预警、抽检不合格退出、退出后公示")],
                  ["是否核对许可项目与经营范围（超范围经营高发）", "证照到期是否自动预警",
                   "是否有退出机制且实际执行过", "档案留存是否可随时调取"])


def content_mod():
    """内容治理与投诉举报。"""
    return _steps("内容治理与投诉举报",
                  [("事前规则", "公示内容规范与违规情形，商家可查可下载"),
                   ("事中处置", "机器初筛 + 人工复核，处置措施与理由告知发布者"),
                   ("申诉通道", "提供申诉入口，明确处理时限并反馈结果"),
                   ("报告留痕", "违规内容与处置记录留存，按要求报送主管部门")],
                  ["是否公示处置规则与措施梯度", "处置是否告知理由（不得静默删除）",
                   "申诉是否有时限承诺", "记录是否可用于向监管报送"])


def plat_compete():
    """平台竞争与公平交易。"""
    return _cards("平台竞争与公平交易",
                  [("不得二选一", "不得以限流、降权强制商家独家", "不得对交易价格做不合理限制"),
                   ("不得自我优待", "自营与他营规则一致", "搜索排序不得隐性偏袒自营"),
                   ("不得大数据杀熟", "同条件同价格", "差异化须可归因、可公示"),
                   ("不得恶意不兼容", "不得阻碍商家多渠道经营", "不得滥用平台规则排挤对手")],
                  ["排序规则是否有可解释说明", "自营/他营的佣金与流量是否差别对待",
                   "促销是否强制商家承担成本", "是否留存规则审批与执行记录"],
                  tone=AMBER)


def live_trade():
    """网络直播营销：口播与素材管控。"""
    x = 40
    inner = _phone(x, 232, 292, "直播间")
    inner += f"""
<rect x="{x+6}" y="46" width="220" height="120" fill="#e9eef4"/>
<circle cx="{x+116}" cy="106" r="26" fill="#cdd9e6"/>
<rect x="{x+14}" y="52" width="76" height="20" rx="10" fill="#101820" opacity=".72"/>
<text x="{x+52}" y="66" text-anchor="middle" font-size="9.4" fill="#fff">直播中</text>
<rect x="{x+150}" y="52" width="70" height="20" rx="10" fill="#fff7f0" stroke="#f2d9c0"/>
<text x="{x+185}" y="66" text-anchor="middle" font-size="9" fill="{AMBER}">广告标识</text>
<rect x="{x+6}" y="166" width="220" height="34" fill="{BG}"/>
<text x="{x+16}" y="180" font-size="9.2" fill="{MUTED}">带货主体：[商家名]（自营/他营已标注）</text>
<text x="{x+16}" y="194" font-size="9.2" fill="{MUTED}">口播禁用词已过滤 · 价格依据可查</text>
<rect x="{x+6}" y="200" width="220" height="34" fill="#f7f9fc"/>
<text x="{x+16}" y="214" font-size="9.2" fill="{INK}">「本平台近 7 日最低成交价 ¥35.80」</text>
<text x="{x+16}" y="228" font-size="9.2" fill="{INK}">「实证 [2000] 份评价 · 复购率 [38]%」</text>
<text x="{x+116}" y="256" text-anchor="middle" font-size="8.8" fill="{FAINT}">直播回放留存，可用于事后核查</text>
"""
    inner += _note(["是否标明广告与带货主体", "口播是否过违禁词与功效词",
                    "数据类宣称可溯源（样本/时间/口径）", "回放与口播记录留存备查"], 300, 60)
    return _wrap(inner)


def plat_boundary():
    """平台责任边界与义务范围。"""
    return _board("平台责任边界自查",
                  [("平台性质", "自营 + 第三方商家（平台内经营者）并存", INK),
                   ("自营责任人", "自营商品以平台自身为销售者", INK),
                   ("他营责任", "资质审核、公示、违规处置、先行赔付承诺", INK),
                   ("连带责任场景", "明知或应知违法未采取措施 · 未核验资质", WARN),
                   ("公示义务", "营业执照、许可、实际经营主体", INK),
                   ("留痕", "审核与处置记录留存不少于 [3] 年", MUTED)],
                  ["是否清晰区分自营与他营责任", "「应知」的认定标准是否写入内部制度",
                   "先行赔付承诺是否对外公示且可执行", "审核记录能否应对监管调取"])


def plat_penalty():
    """平台内违规处置与报告。"""
    return _steps("平台内违规处置与报告",
                  [("发现渠道", "投诉举报、抽检、监管通报、内部巡检"),
                   ("处置措施", "警示、限流、下架、暂停服务、终止合作，与违规程度相称"),
                   ("告知与申诉", "书面告知违规事实、依据与申诉方式"),
                   ("报告义务", "发现违法行为及时报告主管部门并配合调查")],
                  ["处置措施是否与规则一致（避免随意性）", "是否留存告知与申诉记录",
                   "报告是否及时（不得等结案才报）", "被处置商家的历史数据是否可追溯"])


# ---------------- 个人信息保护 ----------------

def entrust():
    """委托处理 / 共同处理 / 对外提供。"""
    return _board("数据处理关系台账",
                  [("委托处理", "[短信服务商] · 协议+审计条款 · 不超目的使用", INK),
                   ("共同处理", "[联合营销伙伴] · 约定各自权利义务与责任", INK),
                   ("对外提供", "配送履约必要的收件信息 · 单独告知", WARN),
                   ("安全评估", "提供前完成个人信息保护影响评估并留档", INK),
                   ("接收方约束", "合同禁止转委托、要求同等保护水平", INK),
                   ("记录", "处理目的、方式、种类、保存期限逐项登记", MUTED)],
                  ["是否区分委托/共同处理/提供三种关系", "委托是否做受托方监督（含审计权）",
                   "对外提供是否单独告知并取得同意", "影响评估报告是否随业务变更更新"])


def minor_pi():
    """不满十四周岁未成年人个人信息。"""
    return _steps("未成年人个人信息保护",
                  [("识别与告知", "识别未成年人用户，取得监护人同意并单独告知"),
                   ("专门规则", "制定专门的个人信息处理规则并显著易读地公开"),
                   ("最小必要", "禁采与服务无关信息，禁做用户画像与个性化推荐"),
                   ("留痕与响应", "监护人可查阅、更正、删除，响应有记录")],
                  ["是否真的有识别手段而非只挂声明", "监护人同意是否可核验、可撤回",
                   "是否关闭了面向未成年人的个性化推荐", "专门规则是否独立成文且易读"],
                  tone=AMBER)


def big_handler():
    """大型个人信息处理者特别义务。"""
    return _board("特别义务自查（达量主体）",
                  [("判定标准", "处理个人信息达规定数量（详见适用规定）", INK),
                   ("负责人", "指定个人信息保护负责人并公开联系方式", INK),
                   ("专门机构", "设立专门机构或指定专门人员", INK),
                   ("合规审计", "定期开展合规审计并报送审计报告", WARN),
                   ("影响评估", "敏感信息、自动化决策、对外提供等场景逐项评估", WARN),
                   ("报送", "按主管部门要求报送处理情况", MUTED)],
                  ["是否已按最新口径自查是否达量", "负责人信息是否对外公开可联系",
                   "审计是否由独立第三方或独立部门完成", "评估报告是否覆盖全部高风险场景"])


def pi_audit():
    """个人信息保护合规审计。"""
    return _steps("合规审计闭环",
                  [("计划与范围", "覆盖告知同意、最小必要、委托提供、权利响应、安全措施"),
                   ("实施方式", "制度查阅 + 系统验证 + 抽样测试（不只看文档）"),
                   ("问题定级", "按高/中/低分级，明确责任人与整改时限"),
                   ("复核与留档", "整改复测后出具审计报告，报告留存备查")],
                  ["审计是否独立于业务部门", "是否有系统抽样验证而非纯制度检查",
                   "高危问题是否限期整改并复测", "报告是否可提交监管检查"])


def pi_export():
    """个人信息出境路径选择。"""
    return _board("出境路径与判断要素",
                  [("出境场景", "[境外客服系统] / [境外云服务] / [集团内共享]", INK),
                   ("数量判断", "是否达安全评估阈值（按最新规定核对）", WARN),
                   ("路径选择", "安全评估 / 标准合同 / 认证 / 豁免", INK),
                   ("前置程序", "评估 → 备案/备案回执 → 生效后执行", INK),
                   ("告知同意", "告知境外接收方信息并取得单独同意", INK),
                   ("持续义务", "合同履行情况年度报告 · 变更重新评估", MUTED)],
                  ["是否先判断数量再选路径（勿凭感觉选）", "标准合同是否完成备案",
                   "告知中是否写明境外接收方与目的", "境外接收方变更是否重新评估"])


# ---------------- 数据安全 / 网络安全 ----------------

def data_lifecycle():
    """数据全生命周期安全。"""
    return _steps("数据全生命周期安全",
                  [("采集", "最小必要 · 来源合法 · 采集清单与目的对应"),
                   ("传输与存储", "通道加密 · 重要数据加密存储 · 密钥分离管理"),
                   ("使用与加工", "权限最小化 · 敏感操作双人复核 · 脱敏后用于分析"),
                   ("提供与销毁", "对外提供审批留痕 · 到期销毁有记录可核验")],
                  ["是否有覆盖全环节的安全制度", "密钥与数据是否分离保管",
                   "敏感操作是否双人复核", "销毁是否有不可恢复的验证记录"])


def risk_assess():
    """风险评估与合规审计。"""
    return _steps("风险评估机制",
                  [("年度评估", "每年至少一次全面评估，业务重大变更时专项评估"),
                   ("评估维度", "数据类别与量级、处理活动风险、安全措施有效性"),
                   ("报告与整改", "形成报告，明确风险等级、整改措施与责任人"),
                   ("复用与留档", "报告用于向监管说明，留存不少于 [3] 年")],
                  ["评估是否由业务与技术共同完成", "是否识别重要数据并单列",
                   "整改是否闭环", "报告是否与实际系统状态一致"])


def log_keep():
    """日志留存与安全监测。"""
    return _board("日志与监测要求",
                  [("日志类型", "登录、权限变更、数据导出、接口调用", INK),
                   ("留存期限", "网络日志不少于 [6] 个月", INK),
                   ("防篡改", "集中采集 · 只增不改 · 异地备份", WARN),
                   ("监测告警", "异常批量导出、非工作时间访问触发告警", WARN),
                   ("处置联动", "告警 → 核查 → 阻断 → 复盘，全流程留痕", INK),
                   ("审计可查", "支持按人、按数据项、按时段回溯", MUTED)],
                  ["日志是否集中存储而非散在各系统", "是否可防删除篡改",
                   "告警是否有处置闭环记录", "能否按监管要求快速导出"])


def net_level():
    """网络安全等级保护。"""
    return _board("等级保护工作项",
                  [("系统定级", "按业务受侵害客体与程度定级并备案", INK),
                   ("备案", "定级后向公安机关备案，取得备案证明", INK),
                   ("建设整改", "按对应等级要求做技术与管理整改", INK),
                   ("等级测评", "定期测评，三级及以上每年一次", WARN),
                   ("整改闭环", "测评发现的问题限期整改并复测", INK),
                   ("变更备案", "系统重大变更须重新定级或变更备案", MUTED)],
                  ["新增系统是否完成定级备案", "测评是否在有效期内",
                   "高危问题是否整改完成", "云上系统的责任划分是否书面明确"])


def vuln_mgmt():
    """漏洞与风险管理。"""
    return _steps("漏洞管理闭环",
                  [("发现", "漏洞扫描、众测、厂商通报、监管通报多渠道并行"),
                   ("定级", "按可利用性与影响范围定级，明确修复时限"),
                   ("修复与验证", "修复后须复测验证，不能只以「已修复」回执结案"),
                   ("上报义务", "按规定向主管部门报送漏洞与处置情况")],
                  ["是否区分「已发现未修复」与「已闭环」", "高危漏洞修复时限是否有制度约定",
                   "是否存在长期挂账的高危漏洞", "对外报送内容是否与内部台账一致"])


def supply_sec():
    """供应链与第三方安全。"""
    return _steps("供应链安全管理",
                  [("准入", "对第三方做安全能力与合规资质评估"),
                   ("合同约束", "安全责任、数据使用范围、审计权、事件通报义务"),
                   ("持续监测", "服务商安全事件影响评估，SDK/组件版本跟踪"),
                   ("退出", "合作终止时回收权限、删除数据并取得确认")],
                  ["是否掌握全部第三方组件清单", "合同是否含数据删除与审计条款",
                   "开源组件漏洞是否跟踪", "退出时是否有数据删除确认记录"])


def event_report():
    """网络数据安全事件报告与泄露通知。"""
    return _steps("事件报告与通知",
                  [("分级判定", "按影响范围与严重程度分级，对应不同报告时限"),
                   ("内部上报", "第一时间报安全负责人与法务，同步启动处置"),
                   ("外部报告", "按规定时限向主管部门报告，重大事件不得延迟"),
                   ("个人通知", "可能造成危害的须及时通知个人，说明影响与建议措施")],
                  ["是否预置分级标准与时限表", "是否有对外报告模板与联系人清单",
                   "个人通知是否含具体影响与补救建议", "事件复盘是否形成制度改进"])


# ---------------- 价格与消费者权益 ----------------

def promo_rule():
    """促销与补贴规则。"""
    return _board("促销合规要素",
                  [("活动信息", "名称、时间、范围与参与条件", INK),
                   ("优惠计算", "满减/折扣/券的叠加顺序与封顶", INK),
                   ("折价基准", "本平台活动前 [7] 日最低成交价", WARN),
                   ("限购规则", "限购数量、资格与失效条件", INK),
                   ("退款规则", "部分退款后优惠如何处理", INK),
                   ("留痕", "活动前后价格与库存快照留存", MUTED)],
                  ["是否存在先提价后打折", "宣传价与结算价是否一致",
                   "规则变动是否及时公示并通知", "价格快照能否应对监管核查"])


def consumer_right():
    """消费者权益保护。"""
    return _steps("消费者权益保障",
                  [("知情权", "价格、规格、产地、保质期、不适用无理由情形均下单前可见"),
                   ("公平交易", "不得强制搭售、不得默认勾选付费项"),
                   ("求偿权", "客服与投诉通道畅通，明确处理时限"),
                   ("个人信息", "营销短信与电话须可一键退订、拒接")],
                  ["关键信息是否在决策前展示而非售后页", "是否存在默认勾选",
                   "投诉响应是否可追踪", "退订是否真正生效"])


def subsidy():
    """补贴促销与低价策略。"""
    return _board("补贴与低价合规自查",
                  [("补贴来源", "平台自担 / 商家分担（须事前约定）", WARN),
                   ("成本归集", "不得低于成本价销售以排挤对手", WARN),
                   ("宣传口径", "「补贴」「直降」金额须与实际一致", INK),
                   ("大促披露", "「全年最低」类宣称须有依据与范围", INK),
                   ("商家知情", "强制商家承担促销成本属违规", WARN),
                   ("数据留痕", "补贴额度、参与门槛与结算记录留存", MUTED)],
                  ["是否强制商家承担促销成本", "补贴金额宣传是否与实际抵扣一致",
                   "是否存在持续低于成本销售", "低价策略是否留存审批依据"])


# ---------------- 食品与产品质量 ----------------

def license_wall():
    """经营资质与亮证：门店/线上双端公示。"""
    return _doc("食品经营许可 · 公示栏", "营业执照与许可证公示",
                [("主体名称", "[xx 网络科技有限公司]"),
                 ("统一社会信用代码", "[9131xxxxxxxxxxxx]"),
                 ("食品经营许可证", "[JY131xxxxxxxxxx]"),
                 ("许可项目", "预包装食品销售 · 散装食品销售 · 冷藏冷冻食品"),
                 ("有效期至", "[2027-08-31]"),
                 ("线上公示位置", "App「关于-资质证照」· 门店公示墙")],
                "超许可范围经营（如热食制售）属高频违法点",
                "为什么这样公示",
                ["证照须在", "线上一级入口", "可达", "", "许可项目须与", "实际经营一致", "",
                 "到期前 30 日", "预警换证", "", "门店与线上", "信息保持一致"])


def trace_chain():
    """进货查验与追溯。"""
    return _steps("进货查验与追溯链",
                  [("索证索票", "供货者许可证、营业执照、每批次合格证明文件"),
                   ("查验记录", "品名、规格、数量、生产日期/批号、供货者、联系方式"),
                   ("随货凭证", "肉禽蛋等附检疫合格证明，食用农产品附产地信息"),
                   ("追溯能力", "能在 [1] 小时内说清「这批货从哪来、到哪去」")],
                  ["是否每批次索证而非一次性备案", "记录是否含批号（无批号无法追溯）",
                   "检疫证明是否与批次对应", "追溯演练是否实际做过"])


def quick_test():
    """抽检、快检与不合格处置。"""
    return _steps("抽检与不合格处置",
                  [("计划与实施", "按品类风险制定快检与抽检计划，覆盖高风险品类与供应商"),
                   ("结果记录", "检测项目、结果、时间、批次、检测方完整留档"),
                   ("下架与公告", "不合格立即下架同批次，必要时公告召回"),
                   ("追责与复盘", "追溯供货者责任，分析原因并调整准入与抽检频次")],
                  ["快检设备与试剂是否在有效期内", "不合格品是否真下架（含在途与门店库存）",
                   "是否建立供货者退出机制", "处置时限是否有制度约束"],
                  tone=WARN)


def food_permit():
    """食品许可与备案（含前置仓新业态）。"""
    return _doc("食品经营主体信息", "许可与备案核对",
                [("经营方式", "网络经营 + 门店经营"),
                 ("主体业态", "食品销售经营者"),
                 ("许可范围", "预包装 / 散装 / 冷藏冷冻 / 特殊食品"),
                 ("网络经营", "已勾选「网络经营」并公示"),
                 ("平台备案", "已向省级市场监管部门备案"),
                 ("新业态判断", "前置仓是否需单独办证（按属地答复执行）")],
                "仅线下办证未做网络经营公示 → 平台侧被通报",
                "常见漏项",
                ["网络经营须在", "许可证上勾选", "", "第三方平台须", "完成备案", "",
                 "新增业态前", "先问属地监管", "", "许可变更须", "同步线上公示"])


def food_claim():
    """食品标签与宣称（含网络页宣称）。"""
    return _board("食品宣称合规比对",
                  [("营养声称", "「高钙」「低脂」须符合 GB 28050 条件", WARN),
                   ("功能声称", "仅可主张食品功能，禁医疗用语", WARN),
                   ("零添加宣称", "「0 添加」须真实且不贬低同类食品", WARN),
                   ("产地宣称", "「原产地直供」须有采购与产地证明", INK),
                   ("保健食品", "须有蓝帽子方可宣称保健功能", WARN),
                   ("广告审查", "保健食品广告须经审查批准", MUTED)],
                  ["是否逐条比对营养声称的量化条件", "是否出现治愈/预防等医疗用语",
                   "「0 添加」是否留得住生产记录", "详情页与直播口播口径是否一致"])


def food_new_reg():
    """食品标识新规过渡期准备（2027-03-16）。"""
    return _steps("新规过渡期准备（2027-03-16 施行）",
                  [("盘点包材", "清点在库与在产标签数量，评估可消耗周期"),
                   ("版式改造", "按新规调整日期标示、致敏物质、净含量与字号"),
                   ("分装标签重制", "前置仓分装标签须同步改版（含分装者信息）"),
                   ("切换与留样", "设定切换时点，旧包装用尽后不得再用；留存样板")],
                  ["旧包材库存是否能在施行前用尽", "日期标示是否改为新规要求的表述",
                   "致敏物质提示是否已加入", "分装标签是否纳入改造范围"],
                  tone=AMBER)


# ---------------- 即时零售与网络交易 ----------------

def net_license():
    """网络交易主体登记与亮照。"""
    return _doc("线上公示 · 关于我们", "主体登记信息公示",
                [("经营者名称", "[xx 网络科技有限公司]"),
                 ("登记机关", "[xx 市市场监督管理局]"),
                 ("注册号 / 统一代码", "[9131xxxxxxxxxxxx]"),
                 ("经营地址", "[xx 市 xx 区 xx 路 x 号]"),
                 ("联系方式", "[客服电话] · [邮箱]"),
                 ("公示位置", "首页底部 + 「关于」页，一级入口可达")],
                "未亮照或亮照信息与登记不一致属高频通报点",
                "亮照要求",
                ["一级入口", "可达，非埋", "深层页面", "", "信息须与", "登记一致", "",
                 "无需登录", "即可查看", "", "变更后须", "及时更新"])


def qual_review():
    """平台内经营者资质审核。"""
    return _steps("平台内经营者资质审核",
                  [("登记核验", "核验身份、地址、联系方式与行政许可，建档并定期核验"),
                   ("许可核对", "核对许可项目与实际经营范围是否匹配"),
                   ("信息公示", "在商家页面显著位置公示主体与许可信息"),
                   ("信息报送", "按规定向监管部门报送平台内经营者身份信息")],
                  ["是否只做了首次审核而无定期复核", "许可项目是否被忽略（超范围经营）",
                   "入驻资料是否可追溯调取", "报送是否按口径完成"])


def info_publish():
    """商品信息与交易规则公示。"""
    return _board("商品与规则公示要素",
                  [("商品信息", "名称、规格、产地、保质期、贮存条件", INK),
                   ("价格信息", "成交价、划线价依据、附加费用", INK),
                   ("服务条款", "配送时效、缺货处理、退换规则", INK),
                   ("规则公示", "服务协议与交易规则可查可下载", INK),
                   ("变更公示", "规则修订公示不少于 [7] 日并征求意见", WARN),
                   ("版本留痕", "保留历史版本与生效时间", MUTED)],
                  ["关键条款是否在决策前可见", "规则修改是否有公示期与意见征集",
                   "历史版本能否调取", "表述是否与实际履约一致"])


def online_food_filing():
    """网络食品与线上日销品经营备案。"""
    return _steps("网络经营备案与公示",
                  [("主体备案", "自建网站或平台内经营的食品经营者按规定备案"),
                   ("信息公示", "在经营活动主页面公示许可与备案信息"),
                   ("变更同步", "许可或备案信息变更后同步更新公示内容"),
                   ("平台协同", "向平台提供真实信息，配合平台核验与报送")],
                  ["备案是否覆盖全部经营渠道", "公示位置是否在主页而非二级页面",
                   "变更是否有同步记录", "平台核验是否留存回执"])


def dark_store_ops():
    """前置仓与即时零售平台化经营。"""
    return _cards("前置仓平台化经营合规",
                  [("场所资质", "仓库与加工区分设", "分装须有相应许可或按属地要求办证"),
                   ("用工与配送", "自营骑手与第三方骑手分类管理", "用工性质须如实公示"),
                   ("商品与标签", "分装标签信息完整", "日期与致敏物质独立标示"),
                   ("平台责任", "自营商品自担责", "他营商品尽审核与处置义务")],
                  ["前置仓是否被认定为需办证场所（问属地）", "分装环节是否有资质与卫生条件",
                   "骑手关系与宣传口径是否一致", "自营/他营责任划分是否落到合同"])


# ---------------- 即时配送与骑手权益 ----------------

def delivery_food():
    """配送环节食品安全：封签与温控。"""
    return _steps("配送环节食安管控",
                  [("出仓封签", "餐食与直接入口食品使用一次性封签，破损可拒收"),
                   ("温控配送", "冷藏冷冻商品全程冷链，配送箱定期清洗消毒"),
                   ("混放防控", "生熟分开、化学品与食品分箱，禁与食品同箱"),
                   ("交付与投诉", "交付核验、超时与破损处理规则对外公示")],
                  ["封签是否全覆盖直接入口食品", "配送箱清洗消毒是否有记录",
                   "冷链商品是否用保温箱与冰袋并记录温度", "骑手健康证是否有效并核验"],
                  tone=WARN)


def rider_rights():
    """骑手用工与新就业形态权益。"""
    return _cards("骑手权益保障要点",
                  [("用工性质", "劳动合同 / 书面协议如实告知", "不得以承揽名义规避劳动保障"),
                   ("劳动报酬", "计件单价与结算周期公开", "不得无故克扣与拖延"),
                   ("休息与安全", "连续接单时长上限与强制休息", "恶劣天气停派机制"),
                   ("职业伤害", "按规定参加职业伤害保障", "商业保险不得替代法定保障")],
                  ["用工模式与宣传口径是否一致", "报酬规则是否事前告知并公示",
                   "是否有超时接单的强制干预", "算法考核是否以罚款为主要手段"],
                  tone=AMBER)


def dispatch_rule():
    """派单算法与规则公示。"""
    return _board("派单规则公示要素",
                  [("规则公示", "派单依据、考核指标与奖惩规则对外公示", INK),
                   ("算法要素", "距离、时效、骑手负荷、时段等要素及其权重", INK),
                   ("透明度", "骑手可查询本人派单结果与考核明细", INK),
                   ("申诉通道", "对派单与扣罚有异议可申诉并限时答复", WARN),
                   ("安全优先", "恶劣天气与超时风险时放宽时效要求", WARN),
                   ("留痕", "规则版本与调整记录留存", MUTED)],
                  ["公示是否具体到要素而非笼统描述", "骑手能否看到自己的考核明细",
                   "申诉是否真的能改判", "安全指标是否高于时效指标"])


def rider_safety():
    """配送安全与培训。"""
    return _steps("配送安全与培训",
                  [("准入核验", "车辆合规、健康证、驾驶资质（如需）核验"),
                   ("培训", "入职培训 + 定期安全培训，内容含交通与食安"),
                   ("装备保障", "反光装备、头盔、保温箱卫生与消毒要求"),
                   ("事故处置", "事故报告、救助与保险理赔流程明确并告知")],
                  ["培训是否有记录与考核", "装备发放是否留痕",
                   "事故处置流程骑手是否知晓", "交通安全指标是否纳入考核"])


# ---------------- 网络餐饮与线下餐饮 ----------------

def cater_platform():
    """网络餐饮第三方平台责任。"""
    return _steps("网络餐饮平台责任",
                  [("入网审核", "核验许可证与实体门店，登记并建档"),
                   ("公示义务", "公示许可与量化分级信息，无证不得上线"),
                   ("抽查监测", "对入网商家定期抽查，发现违法停止服务并报告"),
                   ("送餐要求", "送餐人员培训与管理，容器安全无害")],
                  ["是否核验实体门店（照片与实际一致性）", "公示信息是否与实际一致",
                   "抽查是否有记录与处置结果", "停止服务是否有留痕"])


def cater_shop():
    """入网餐饮服务提供者义务。"""
    return _steps("入网餐饮经营者义务",
                  [("资质", "具备实体经营门店并取得食品经营许可"),
                   ("信息一致", "线上信息与许可信息一致，不得超范围经营"),
                   ("过程控制", "原料采购、加工制作、清洗消毒符合规范"),
                   ("包装与配送", "使用合规容器，需封签的按规封签")],
                  ["是否存在「无实体店上线」", "线上宣称的菜品是否在许可范围内",
                   "后厨卫生与从业人员健康证是否在有效期", "封签是否落实"])


def offline_cater():
    """线下餐饮门店合规。"""
    return _steps("门店经营规范",
                  [("许可与健康", "许可公示上墙，从业人员持有效健康证明"),
                   ("场所与设备", "功能分区、防蝇防鼠、专间专用设施齐备"),
                   ("过程管理", "留样、清洗消毒、废弃物处置按要求执行"),
                   ("记录台账", "采购查验、消毒、留样、晨检记录齐全可查")],
                  ["健康证是否真在有效期（超期高发）", "留样是否规范（量、时间、温度）",
                   "消毒记录是否事后补填", "明厨亮灶是否实际可用"])


def tableware():
    """餐饮具与包装材料。"""
    return _doc("食品相关产品核查", "包装材料合规核对",
                [("接触材料", "[PP] 材质 · 食品接触用"),
                 ("合格证明", "检验报告 / 符合性声明（索证留存）"),
                 ("标签标识", "「食品接触用」字样或调羹叉子标识"),
                 ("使用范围", "不得超温度或超用途使用"),
                 ("一次性用品", "不得使用不可降解的禁限塑料制品"),
                 ("替代方案", "可降解或可循环包装清单与成本核算")],
                "「食品级」需有检验报告支撑，不可仅凭供方口头承诺",
                "核查要点",
                ["索证须逐", "供应商留存", "", "标签须有", "食品接触用", "标识", "",
                 "用途温度", "不得超范围", "", "禁限塑料", "须有替代品"])


# ---------------- 前置仓与仓储冷链 ----------------

def store_qual():
    """前置仓经营资质与场所。"""
    return _doc("前置仓经营信息", "场所与资质核对",
                [("场所性质", "[仓储 + 分拣 + 分装] 一体"),
                 ("场所条件", "与经营品种、数量相适应，环境整洁、分区明确"),
                 ("许可判断", "是否需另办许可：以属地监管答复为准"),
                 ("设备设施", "冷藏冷冻设备、温度监测、防虫防鼠设施"),
                 ("人员", "从业人员健康证明 · 操作规范培训"),
                 ("记录", "温控、清洗消毒、虫害防治记录留档")],
                "未与属地确认即新增分装/加工业务 → 无证经营风险",
                "核查要点",
                ["新增业态先", "问属地监管", "", "仓储与加工", "须分区", "",
                 "温控设备须", "可记录可追溯", "", "健康证须", "在有效期内"])


def cold_chain():
    """冷链贮存与温控。"""
    inner = f"""
<rect x="24" y="18" width="424" height="234" rx="10" fill="{BG}" stroke="{LINE}"/>
<text x="42" y="42" font-size="12" font-weight="700" fill="{INK}">冷链温控记录（自动采集 · 不可补录）</text>

<text x="42" y="66" font-size="9.6" fill="{MUTED}">冷藏库 A · 目标 0—4℃</text>
<polyline points="42,110 92,104 142,108 192,96 242,102 292,88 342,94 392,90 442,86"
 fill="none" stroke="{TEAL}" stroke-width="2"/>
<line x1="42" y1="84" x2="442" y2="84" stroke="{WARN}" stroke-dasharray="4 3"/>
<text x="42" y="80" font-size="8.8" fill="{WARN}">上限 4℃</text>
<text x="42" y="124" font-size="8.6" fill="{FAINT}">00:00　　06:00　　12:00　　18:00　　24:00</text>

<rect x="42" y="136" width="384" height="44" rx="7" fill="#fdecea" stroke="#f3cfc9"/>
<text x="56" y="154" font-size="10" font-weight="700" fill="{WARN}">超限告警：[2026-09-12 14:20] 达 7.4℃ · 持续 [12] 分钟</text>
<text x="56" y="170" font-size="9.4" fill="{MUTED}">处置：自动推送仓管 → 复检商品 → 隔离 [8] 箱 → 记录归档</text>

<rect x="42" y="190" width="384" height="44" rx="7" fill="{SOFT}" stroke="{LINE}"/>
<text x="56" y="208" font-size="10" fill="{INK}">禁止事项：手工补录 · 批量填写 · 事后倒填记录</text>
<text x="56" y="224" font-size="9.4" fill="{MUTED}">采集频率不低于每 30 分钟一次，记录保存期不少于保质期后 [6] 个月</text>
"""
    inner += _note(["温湿度须自动采集，不得人工补录", "超限自动告警并留处置记录",
                    "冷藏冷冻设备须有备用与应急方案", "记录保存期覆盖保质期后 6 个月"], 452, 46, w=250)
    return _wrap(inner, 264)


def expiry_zone():
    """临期、过期与不合格品处置。"""
    return _steps("临期 · 过期 · 不合格品处置",
                  [("临期识别", "按剩余保质期分档，剩 ≤1/3 进入临期专区并明示剩余天数"),
                   ("专区销售", "临期商品单独标识、单独标价，不得混入正常货架"),
                   ("到期下架", "到期当日系统强制下架，无法人工绕过"),
                   ("不合格品", "隔离存放、物理区分、按规销毁并留存处置记录")],
                  ["临期分档标准是否制度化", "到期下架是否系统强制",
                   "不合格品是否与正常品物理隔离", "销毁是否有第三方或双人见证记录"],
                  tone=WARN)


def agri_trace():
    """食用农产品进货查验与追溯。"""
    return _steps("食用农产品追溯",
                  [("产地信息", "索取产地证明或购货凭证，记录生产者名称与地址"),
                   ("检验检疫", "肉禽类查验检疫合格证明，蔬果类按规索取合格证明"),
                   ("批批记录", "按批次登记名称、数量、进货日期与供货者"),
                   ("追溯演练", "能在 [1] 小时内提供批次—供应商—销售去向对照")],
                  ["是否按批次而非按月记录", "检疫证明与采购批次是否一一对应",
                   "产地信息是否具体到生产者", "追溯演练是否实际开展过"])


# ---------------- 计量与商品量 ----------------

def scale_check():
    """计量器具与强制检定。"""
    return _doc("强制检定计量器具", "检定合格标识",
                [("器具名称", "电子计价秤 [编号 xxx]"),
                 ("检定机构", "[xx 市计量检定所]"),
                 ("检定结论", "合格"),
                 ("检定日期", "[2026-03-12]"),
                 ("有效期至", "[2027-03-11]"),
                 ("使用场所", "[xx 前置仓 · 分拣台 3]")],
                "使用未经检定或超期未检器具 → 可依法处罚",
                "管理要点",
                ["逐台建档", "含编号与", "检定周期", "", "到期前 30 日", "预约检定", "",
                 "铅封破损", "须停用", "", "自校记录", "每月留存"])


def net_content():
    """定量包装与净含量。"""
    return _doc("定量包装商品标注", "净含量标注核对",
                [("品名", "[有机小白菜]"),
                 ("净含量", "[500] g"),
                 ("标注位置", "与品名同版面显著位置"),
                 ("字符高度", "符合定量包装商品计量监督管理办法要求"),
                 ("去皮方式", "单价与总价均按净含量计"),
                 ("偏差", "在允差范围内，不得短秤少量")],
                "标「500g」实测不足，或按毛重计价 → 计量违法",
                "核对要点",
                ["净含量须与", "实际一致", "", "计价须按", "净含量", "",
                 "同一包装内", "多件商品", "须标总净含量", "", "去皮称重", "须留记录"])


def price_calc():
    """计价与标价规范。"""
    return _board("计价与标价规范",
                  [("计价单位", "按标价单位计价（元/500g 等），不得换算加价", INK),
                   ("标价一致", "标价签、价目表与结算价三者一致", WARN),
                   ("称重计价", "去皮后按净含量计价，小票显示单价与重量", INK),
                   ("附加费", "配送费、包装费在下单前展示", INK),
                   ("促销标注", "促销价同时标注促销期限与条件", INK),
                   ("记录", "调价记录与价签更换记录留存", MUTED)],
                  ["是否存在低价招徕高价结算", "称重是否去皮并按净含量计价",
                   "附加费是否结算时才出现", "调价是否有记录可查"])


# ---------------- 零售与会员 ----------------

def return_policy():
    """七日无理由退货适用性与例外提示。"""
    inner = _phone(40, 232, 292, "商品详情")
    inner += f"""
<text x="46" y="62" font-size="11.6" font-weight="700" fill="{INK}">有机小白菜 500g</text>
<text x="46" y="84" font-size="9.6" fill="{INK}">七日无理由退货：<tspan fill="{WARN}" font-weight="700">不适用</tspan></text>
<text x="46" y="102" font-size="9.2" fill="{MUTED}">理由：生鲜商品保质期短，属法定例外情形</text>
<text x="46" y="118" font-size="9.2" fill="{MUTED}">依据：《消费者权益保护法》第二十五条</text>
<rect x="46" y="132" width="220" height="52" rx="8" fill="#f7f9fc" stroke="{LINE}"/>
<text x="58" y="150" font-size="9.4" fill="{INK}">质量问题怎么办</text>
<text x="58" y="166" font-size="9.2" fill="{MUTED}">签收后 [24] 小时内拍照联系客服，可退可换</text>
<text x="58" y="180" font-size="9.2" fill="{MUTED}">客服入口：订单页「申请售后」</text>
<text x="46" y="208" font-size="9.4" fill="{MUTED}">其他商品：七日无理由退货（拆封不影响）</text>
<text x="46" y="226" font-size="9.4" fill="{MUTED}">退货运费：质量问题商家承担</text>
<text x="46" y="252" font-size="8.8" fill="{FAINT}">例外情形须在下单前提示，不能只写在售后页</text>
"""
    inner += _note(["不适用情形须在下单前显著提示", "例外情形要写具体，不能笼统「部分商品除外」",
                    "质量问题退换不得设置不合理门槛", "退货进度须可查询"], 300, 60)
    return _wrap(inner)


def member_prepay():
    """会员与预付式消费。"""
    inner = _phone(40, 232, 292, "会员中心")
    inner += f"""
<rect x="46" y="54" width="220" height="66" rx="10" fill="{SOFT}" stroke="{LINE}"/>
<text x="58" y="74" font-size="10.4" fill="{MUTED}">会员余额（可用于本平台消费）</text>
<text x="58" y="98" font-size="20" font-weight="800" fill="{WARN}">¥128.60</text>
<text x="58" y="114" font-size="9" fill="{MUTED}">有效期：长期有效（无自动过期条款）</text>
<text x="46" y="140" font-size="9.6" fill="{INK}">余额与权益说明</text>
<text x="46" y="158" font-size="9.2" fill="{MUTED}">· 余额仅限本平台消费，不可提现</text>
<text x="46" y="174" font-size="9.2" fill="{MUTED}">· 退款原路退回，含赠送金额按比例扣回</text>
<text x="46" y="190" font-size="9.2" fill="{MUTED}">· 会员权益内容与有效期事前公示</text>
<rect x="46" y="204" width="220" height="30" rx="8" fill="#fff" stroke="{LINE}"/>
<text x="58" y="223" font-size="10.2" fill="{BRAND}">申请退余额（[15] 个工作日内到账）</text>
<text x="46" y="256" font-size="8.8" fill="{FAINT}">不得设「过期作废」「不可退」等加重消费者责任的条款</text>
"""
    inner += _note(["余额不得设不合理有效期", "退卡退余额路径须真实可用",
                    "权益内容变更须提前告知并给选择权", "格式条款不得不合理地免除自身责任"], 300, 60)
    return _wrap(inner)


def gift_lottery():
    """促销、赠品与有奖销售。"""
    return _board("促销与有奖销售合规",
                  [("促销规则", "时间、范围、条件、数量上限事前公示", INK),
                   ("赠品", "赠品须符合质量要求并承担质量责任", WARN),
                   ("有奖销售", "奖品种类、数量、中奖概率、兑奖方式一并公示", WARN),
                   ("最高奖金额", "不得超过法定上限", WARN),
                   ("兑奖", "不得设置不合理兑奖条件或无故拖延", INK),
                   ("记录", "抽奖过程与结果可追溯、可核验", MUTED)],
                  ["赠品是否被当作免责品", "中奖概率是否真实公示",
                   "兑奖条件是否含附加消费门槛", "抽奖结果是否可核验"])


# ---------------- 绿色包装与反食品浪费 ----------------

def plastic_ban():
    """一次性塑料制品禁限。"""
    return _board("一次性塑料制品禁限清单",
                  [("禁用", "不可降解塑料袋（门店/配送）", WARN),
                   ("禁用", "不可降解一次性塑料餐具（堂食）", WARN),
                   ("禁用", "不可降解一次性塑料吸管", WARN),
                   ("限用", "有替代方案时不得提供一次性塑料制品", AMBER),
                   ("替代", "可降解 / 可循环包装清单与成本核算", TEAL),
                   ("记录", "替代品采购与使用量台账", MUTED)],
                  ["禁限目录是否按属地最新要求核对", "替代方案是否真实可用而非纸面",
                   "是否有采购与使用量台账", "配送与门店场景是否分别覆盖"])


def over_pack():
    """过度包装：层数、空隙率、成本比。"""
    return _doc("包装合规核算", "过度包装三项指标",
                [("包装层数", "≤ [3] 层（按包装空隙率要求执行）"),
                 ("空隙率", "在标准限值内（按净含量区间分档）"),
                 ("包装成本", "不超过商品销售价的 [20]%"),
                 ("必要空间", "为食品保鲜、防挤压的必需空间除外"),
                 ("材质", "优先单一材质便于回收，减少复合材料"),
                 ("核查方式", "按标准方法实测或按台账核算")],
                "三项任一超限即属过度包装，可处责令改正与罚款",
                "核查要点",
                ["层数须按", "标准计数", "（含礼盒）", "", "成本核定", "须留核算", "依据", "",
                 "电商快递", "另计包装", "要求", "", "替代方案", "须成本可比"])


def anti_waste():
    """反食品浪费。"""
    return _steps("反食品浪费措施",
                  [("按需采购", "按销量预测采购，设置合理安全库存，减少损耗"),
                   ("临期处置", "临期商品优先打折、捐赠或员工内购，禁直接丢弃"),
                   ("提示义务", "醒目提示「按需购买、避免浪费」，餐食可提供小份"),
                   ("记录与改进", "记录损耗率与处置方式，按季度复盘改进")],
                  ["损耗率是否有统计与目标", "临期处置是否有台账而非直接报损",
                   "是否有诱导超量购买的营销（如凑单）", "捐赠是否留存接收方凭证"],
                  tone=TEAL)


MOCKUPS = {
    # App
    "perm_dialog": ("App 权限索取弹窗：场景触发 + 目的同步告知", perm_dialog),
    "sdk_list": ("第三方信息共享清单（隐私政策内）", sdk_list),
    "teen_mode": ("未成年人模式：时长 / 消费 / 时段三重限制", teen_mode),
    "self_start": ("自启动与关联启动：默认关闭 + 用户可控", self_start),
    "app_filing": ("应用分发与备案台账", app_filing),
    "pi_selfcheck": ("个人信息收集使用自查与检测闭环", pi_selfcheck),
    # 广告与营销
    "splash_ad": ("开屏广告：显著关闭标志 + 一键关闭", splash_ad),
    "shake_ad": ("摇一摇广告：常驻提示 + 独立跳过", shake_ad),
    "auto_renew": ("自动续费：价格显著 + 提前提醒 + 便捷取消", auto_renew),
    "personalization_off": ("个性化推荐：总开关 + 清除标签", personalization_off),
    # AI
    "ai_badge": ("AI 生成内容标识：显式角标 + 隐式元数据", ai_badge),
    "train_data": ("训练数据与语料合规要点", train_data),
    "ai_vendor": ("AI 服务商与智能体台账", ai_vendor),
    "ai_app_reg": ("AI 应用方登记与责任", ai_app_reg),
    "ai_teen": ("AI 功能面向未成年人的管控", ai_teen),
    # 算法
    "algo_filing": ("算法备案公示页", algo_filing),
    "algo_duty": ("算法安全主体责任清单", algo_duty),
    "auto_decision": ("自动化决策：说明 + 拒绝权 + 人工复核", auto_decision),
    "algo_change": ("算法备案变更 · 注销 · 公示", algo_change),
    # 平台治理
    "merchant_access": ("商家与供应商准入审核", merchant_access),
    "content_mod": ("内容治理与投诉举报闭环", content_mod),
    "plat_compete": ("平台竞争与公平交易四条红线", plat_compete),
    "live_trade": ("网络直播营销：口播与素材管控", live_trade),
    "plat_boundary": ("平台责任边界自查", plat_boundary),
    "plat_penalty": ("平台内违规处置与报告", plat_penalty),
    "self_operated": ("自营与他营区分标识", self_operated),
    # 个人信息
    "privacy_policy": ("隐私政策摘要：收集什么 / 为何 / 是否共享", privacy_policy),
    "entrust": ("委托处理 / 共同处理 / 对外提供台账", entrust),
    "minor_pi": ("未成年人个人信息保护", minor_pi),
    "big_handler": ("大型个人信息处理者特别义务自查", big_handler),
    "pi_audit": ("个人信息保护合规审计闭环", pi_audit),
    "pi_export": ("个人信息出境路径与判断要素", pi_export),
    # 数据安全 / 网络安全
    "data_lifecycle": ("数据全生命周期安全", data_lifecycle),
    "risk_assess": ("数据安全风险评估机制", risk_assess),
    "log_keep": ("日志留存与安全监测要求", log_keep),
    "net_level": ("网络安全等级保护工作项", net_level),
    "vuln_mgmt": ("漏洞管理闭环", vuln_mgmt),
    "supply_sec": ("供应链与第三方安全管理", supply_sec),
    "event_report": ("数据安全事件报告与泄露通知", event_report),
    # 价格与消费者权益
    "price_tag": ("商品页价格标示：成交价 / 划线价依据 / 附加费前置", price_tag),
    "promo_rule": ("促销合规要素", promo_rule),
    "consumer_right": ("消费者权益保障四项", consumer_right),
    "subsidy": ("补贴促销与低价策略自查", subsidy),
    # 食品与产品质量
    "food_label": ("前置仓分装标签版面", food_label),
    "license_wall": ("营业执照与食品经营许可公示", license_wall),
    "trace_chain": ("进货查验与追溯链", trace_chain),
    "quick_test": ("抽检、快检与不合格处置", quick_test),
    "food_permit": ("食品经营许可与备案核对", food_permit),
    "food_claim": ("食品营养与功能宣称比对", food_claim),
    "food_new_reg": ("食品标识新规过渡期准备（2027-03-16）", food_new_reg),
    # 即时零售与网络交易
    "net_license": ("网络交易主体登记信息公示（亮照）", net_license),
    "qual_review": ("平台内经营者资质审核", qual_review),
    "info_publish": ("商品信息与交易规则公示要素", info_publish),
    "online_food_filing": ("网络食品经营备案与公示", online_food_filing),
    "dark_store_ops": ("前置仓平台化经营合规四维", dark_store_ops),
    # 即时配送与骑手权益
    "delivery_food": ("配送环节食安：封签与温控", delivery_food),
    "rider_rights": ("骑手权益保障要点", rider_rights),
    "dispatch_rule": ("派单规则公示要素", dispatch_rule),
    "rider_safety": ("配送安全与培训", rider_safety),
    # 网络餐饮与线下餐饮
    "cater_platform": ("网络餐饮第三方平台责任", cater_platform),
    "cater_shop": ("入网餐饮服务提供者义务", cater_shop),
    "offline_cater": ("线下餐饮门店经营规范", offline_cater),
    "tableware": ("餐饮具与包装材料合规核对", tableware),
    # 前置仓与仓储冷链
    "store_qual": ("前置仓场所与资质核对", store_qual),
    "cold_chain": ("冷链温控记录（自动采集 · 不可补录）", cold_chain),
    "expiry_zone": ("临期 · 过期 · 不合格品处置", expiry_zone),
    "agri_trace": ("食用农产品进货查验与追溯", agri_trace),
    # 计量与商品量
    "scale_check": ("强制检定计量器具标识", scale_check),
    "net_content": ("定量包装商品净含量标注核对", net_content),
    "price_calc": ("计价与标价规范", price_calc),
    # 零售与会员权益
    "return_policy": ("七日无理由退货适用性与例外提示", return_policy),
    "member_prepay": ("会员余额与预付式消费说明", member_prepay),
    "gift_lottery": ("促销、赠品与有奖销售合规", gift_lottery),
    # 绿色包装与反食品浪费
    "plastic_ban": ("一次性塑料制品禁限清单", plastic_ban),
    "over_pack": ("过度包装三项指标核算", over_pack),
    "anti_waste": ("反食品浪费措施", anti_waste),
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
