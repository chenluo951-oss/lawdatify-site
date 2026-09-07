# 云端合规简报流水线

完全脱离本地设备：**GitHub Actions 定时 → 联网检索 → LLM 生成 → 渲染 PDF/DOCX/HTML → 入仓 → Netlify 自动部署**。
本机关机、断网、WorkBuddy 额度耗尽，均不影响出报告。

## 目录

| 路径 | 作用 |
|---|---|
| `cloud/generate_report.py` | 主程序：检索 → 生成数据模块 → 渲染 → 校验 |
| `cloud/template_daily.py` / `template_weekly.py` | 数据模块模板（LLM 照此结构输出） |
| `cloud/README.md` | 本说明 |
| `generator/` | 渲染引擎副本（reportlab / python-docx），输出目录与字体均可配置 |
| `.github/workflows/cloud-report.yml` | 每天 09:30 日报、每周一 09:35 周报 |
| `.github/workflows/site-sync.yml` | 站点页面重建兜底（每 6 小时 + 每次 push） |

## 需要的密钥（优先免费档）

| 配置项 | 位置 | 说明 |
|---|---|---|
| `LLM_API_KEY` | Secrets | **必填**。推荐 Google Gemini（`gemini-2.5-flash` 免费 1440 次/天，且自带 Google 搜索联网能力，一个 Key 搞定检索+生成） |
| `LLM_PROVIDER` | Variables | 默认 `gemini`；可选 `glm`（智谱，GLM-4-Flash 永久免费、国内直连）、`siliconflow`、`openai` |
| `LLM_MODEL` | Variables | 可选，默认按 provider 取免费模型 |
| `TAVILY_API_KEY` | Secrets | 仅 `LLM_PROVIDER != gemini` 时需要，Tavily 每月 1000 次免费 |

获取地址：Gemini → https://aistudio.google.com/apikey ；智谱 → https://open.bigmodel.cn/ ；硅基流动 → https://cloud.siliconflow.cn/ ；Tavily → https://tavily.com/

## 启用步骤

1. 仓库 Settings → Secrets and variables → Actions，添加上表的 Secrets / Variables
2. 把 `.github/workflows/*.yml` 推到 GitHub（需 PAT 带 `workflow` scope；或在 GitHub 网页端 Actions → New workflow 粘贴创建）
3. Actions 页手动 Run workflow 验证一次；之后每天自动跑

## 本地手动跑

```bash
cd lawdatify-site
pip install reportlab python-docx fonttools pypdf
mkdir -p .fonts && cd .fonts
curl -sSL -o song.ttf  "https://github.com/google/fonts/raw/main/ofl/notoserifsc/NotoSerifSC%5Bwght%5D.ttf"
curl -sSL -o heiti.ttf "https://github.com/google/fonts/raw/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf"
cp song.ttf kaiti.ttf && cp song.ttf songb.ttf && cp heiti.ttf qihei.ttf
cd ..
export LLM_PROVIDER=gemini LLM_API_KEY=xxx CBR_FONT_DIR=$PWD/.fonts CBR_OUT_DIR=$PWD/out
python3 cloud/generate_report.py --kind daily
```

## 关键设计

- **字体**：本机用 WPS 商业字体（不可分发），云端改用 Noto Sans/Serif SC（SIL OFL）。引擎通过 `CBR_FONT_DIR` 或 `CBR_FONT_SONG` 等环境变量覆盖，本机行为不变。
- **输出目录**：`CBR_OUT_DIR` 覆盖，云端产物落到 `out/` 后再复制进 `news/reports/`。
- **质量门禁**：生成的数据模块会先做 import + 字段校验，失败自动重试一次；渲染后由 `qa_strict.py` 检查缺字/tofu/根链接/页数。
- **链接硬约束**：prompt 明确要求发布机构官网具体深链，禁止官网首页，找不到深链的条目直接丢弃。
