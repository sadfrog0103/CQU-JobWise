<div align="center">

# 🎯 CQU JobWise

### 重庆大学求职智能 Agent

**基于 AI 的垂直招聘分析系统 · 自动爬取校招信息 · 智能简历匹配 · 可视化评分排序**

[![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.30+-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Powered by MiMo](https://img.shields.io/badge/Powered_by-MiMo--V2.5--Pro-orange)](https://github.com/XiaoMi/MiMo)

---

**CQU JobWise** 专为重庆大学求职场景打造，一站式完成从「招聘会信息抓取」到「AI 智能简历匹配」的全流程自动化。告别手动翻阅海量岗位，让 AI 帮你精准定位最佳机会！🚀

</div>

---

## 📑 目录

- [✨ 核心特性](#-核心特性)
- [📸 界面预览](#-界面预览)
- [📂 项目结构](#-项目结构)
- [🚀 快速开始](#-快速开始)
- [⚙️ 环境变量配置](#️-环境变量配置)
- [📖 使用说明](#-使用说明)
- [🔔 使用须知](#-使用须知)
- [🛠️ 技术栈](#️-技术栈)
- [🤝 开发指南](#-开发指南)
- [📜 免责声明](#-免责声明)
- [👨‍💻 开发者信息](#-开发者信息)
- [🙏 致谢](#-致谢)

---

## ✨ 核心特性

| 特性 | 说明 |
|:---:|:---|
| 🕷️ **自动爬取校招信息** | 基于 Playwright 浏览器自动化，实时爬取重庆大学就业网招聘会数据，三阶段全链路采集（列表 → 详情 → 深度要求） |
| 🤖 **MIMO 模型深度匹配** | 调用小米 MiMo-V2.5-Pro 大模型，从专业匹配度、技能匹配度、学历、经验、地域等 5 个维度对简历与岗位进行综合评分 |
| 📊 **可视化打分排序** | 匹配结果按分数降序排列，通过 🟢🟡🔴 三色标识直观展示匹配程度，一目了然 |
| 🔍 **多维硬性筛选** | 支持按招聘会场次、单位性质、单位规模等硬性条件快速过滤，大幅缩小关注范围 |
| 📄 **申请日志导出** | 一键生成求职申请日志文件，支持下载，方便追踪投递记录 |
| 🛡️ **智能容错** | 自动重试、JSON 断尾修复、Markdown 围栏清理，保障 AI 返回结果的稳定解析 |

---

## 📸 界面预览

> 启动后浏览器将自动打开 Streamlit 应用界面。

---

## 📂 项目结构

```
CQUJobHunterAgent/
├── 📄 app.py                  # 🎯 Streamlit 主界面（入口文件）
├── 📄 jobfair.py              # 第一阶段：招聘会列表爬虫
├── 📄 jobfair_detail.py       # 第二阶段：招聘会岗位详情爬虫
├── 📄 jobfair_full.py         # 第三阶段：职位要求深度爬虫
├── 🖼️ CQU JobWise.png         # 侧边栏 Logo 图片
├── 📄 resume.pdf              # ⚠️ 用户简历（需自行准备，已 gitignore）
├── 📄 requirements.txt        # Python 依赖清单
├── 📄 .env.example            # 环境变量配置模板
├── 📄 .gitignore              # Git 忽略规则
└── 📄 README.md               # 项目说明文档（本文件）
```

---

## 🚀 快速开始

### 📋 环境要求

| 依赖 | 版本要求 |
|:---:|:---:|
| 🐍 Python | **3.9+**（推荐 3.11） |
| 🌐 Edge 浏览器 | 系统已安装 Microsoft Edge |
| 💻 操作系统 | Windows 10/11 |

### 1️⃣ 克隆项目

```bash
git clone https://github.com/Sadfrog0103/CQUJobHunterAgent.git
cd CQUJobHunterAgent
```

### 2️⃣ 创建虚拟环境并安装依赖

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境（Windows）
venv\Scripts\activate

# 安装 Python 依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器驱动（仅首次需要）
playwright install msedge
```

### 3️⃣ 准备简历文件 ⚠️

> **核心要求：必须准备「文字型 PDF 格式」的简历！**

- 将你的简历 PDF 文件命名为 **`resume.pdf`**
- 放置在项目**根目录**下（与 `app.py` 同级）
- ⚠️ **必须是文字型 PDF**（可复制文字），扫描件/图片型 PDF 将无法解析

```
CQUJobHunterAgent/
└── resume.pdf    ← 放在这里
```

### 4️⃣ 配置环境变量

```bash
# 复制配置模板
cp .env.example .env

# 编辑 .env 文件，填入你的 API Key
# 将 MIMO_API_KEY=your_api_key_here 替换为你的真实密钥
```

### 5️⃣ 启动应用

```bash
streamlit run app.py
```

🎉 浏览器将自动打开 `http://localhost:8501`，开始使用！

---

## ⚙️ 环境变量配置

本项目通过环境变量管理 API 密钥，支持两种配置方式（优先级从高到低）：

### 方式一：`.env` 文件（推荐 ✅）

在项目根目录创建 `.env` 文件：

```env
MIMO_API_KEY=your_api_key_here
```

### 方式二：系统环境变量

```bash
# Windows CMD
set MIMO_API_KEY=your_api_key_here

# Windows PowerShell
$env:MIMO_API_KEY="your_api_key_here"

# Linux / macOS
export MIMO_API_KEY=your_api_key_here
```

> 💡 **提示**：`.env` 文件已被 `.gitignore` 排除，不会被提交到代码仓库，安全无忧。

---

## 📖 使用说明

### 🔹 第一步：招聘会初筛

- 启动后系统自动实时抓取重庆大学就业网最新招聘会数据（约 3-10 分钟）
- 在列表中**勾选**你感兴趣的招聘会场次

### 🔹 第二步：岗位级精细过滤

- 通过侧边栏的**硬性筛选器**设置单位性质、单位规模等条件
- 点击 **🔍 提取详细岗位** 按钮，系统按条件过滤并展示匹配岗位
- 从过滤结果中**勾选**你感兴趣的岗位（建议不超过 10 个）

### 🔹 第三步：AI 智能匹配

- 点击 **🚀 开始 AI 简历匹配** 按钮
- 系统调用 MiMo-V2.5-Pro 模型，对简历与每个岗位进行 5 维度综合评分
- 匹配结果按分数降序排列，三色标识一目了然：
  - 🟢 **80 分及以上**：高度匹配
  - 🟡 **60-79 分**：较为匹配
  - 🔴 **60 分以下**：匹配度较低

### 🔹 第四步：生成申请日志

- 勾选你最终决定投递的岗位
- 点击 **📄 生成日志** 按钮，系统生成结构化的求职申请日志
- 支持一键下载日志文件

---

## 🔔 使用须知

> ⚠️ **重要提示**
>
> - 🆓 本工具目前处于 **限时免费测试阶段**（Powered by MiMo-V2.5-Pro），API 调用配额有限，建议用户在个人设置中配置**自定义 API** 以获得更稳定的体验。
> - 📄 简历必须是 **文字型 PDF**（非扫描件），否则无法正确解析简历内容。
> - ⏱️ 首次启动时数据抓取需要 **3-10 分钟**，请耐心等待。数据抓取完成后会缓存在内存中，后续操作无需重复抓取。
> - 🌐 使用前请确保能够正常访问 **重庆大学就业网**（`cqu.cqbys.com`）。
> - 🔄 如需获取最新数据，可点击侧边栏的 **🔄 刷新实时数据** 按钮。

---

## 🛠️ 技术栈

| 技术 | 用途 |
|:---:|:---|
| 🐍 Python 3.9+ | 主要开发语言 |
| 🎈 Streamlit | Web 交互界面框架 |
| 🤖 OpenAI SDK | AI 模型调用接口 |
| 🔭 Playwright | 浏览器自动化爬虫引擎 |
| 📑 pdfplumber | PDF 文本提取 |
| 🧠 MiMo-V2.5-Pro | 小米大语言模型（核心 AI 引擎） |

---

## 🤝 开发指南

### 独立运行各阶段爬虫

每个爬虫模块都可以独立运行：

```bash
# 第一阶段：爬取招聘会列表 → 输出 cqu_jobfair.csv
python jobfair.py

# 第二阶段：爬取岗位详情 → 输出 jobs_with_details.csv
python jobfair_detail.py

# 第三阶段：深度爬取职位要求 → 输出 full_job_database.csv
python jobfair_full.py
```

### 代码架构

```
用户启动 app.py
    │
    ├── 第一阶段：jobfair.py          → 爬取招聘会列表
    ├── 第二阶段：jobfair_detail.py   → 爬取各招聘会的企业/岗位表格
    ├── 第三阶段：jobfair_full.py     → 深度爬取每个职位的详细要求
    │
    ├── 简历解析（pdfplumber）
    ├── AI 匹配评分（MiMo-V2.5-Pro）
    └── 申请日志导出
```

---

## 📜 免责声明

- 本工具基于 AI 模型生成建议，**仅供求职参考**，不代表校方官方立场。
- 匹配评分结果为算法自动生成，**可能存在偏差**，请结合实际情况综合判断。
- 使用本工具爬取数据时，请遵守相关网站的使用条款和 robots.txt 规则。
- **用户的简历文件不会被上传或分享**，所有处理均在本地完成。

---

## 👨‍💻 开发者信息

<table>
  <tr>
    <td align="center">
      <a href="https://github.com/Sadfrog0103">
        <img src="https://github.com/Sadfrog0103.png" width="100px;" alt="Sadfrog0103"/>
        <br /><sub><b>🐸 Sadfrog0103</b></sub>
      </a>
      <br />
      <sub>全栈开发 · 项目设计</sub>
      <br />
      📧 <a href="mailto:2281939844@qq.com">2281939844@qq.com</a>
    </td>
  </tr>
</table>

---

## 🙏 致谢

<div align="center">

特别感谢 **[小米 MIMO 百万亿 Token 激励计划](https://github.com/XiaoMi/MiMo)** 提供的算力支持 💪

本项目的核心 AI 匹配能力由 **MiMo-V2.5-Pro** 大模型驱动，感谢小米在开源大模型领域的持续贡献！

---

<sub>⭐ 如果觉得这个项目对你有帮助，欢迎点个 Star 支持一下！</sub>

</div>