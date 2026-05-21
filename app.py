"""
CQU 求职智能 Agent - Streamlit 主界面 (v4 - 无痕运行版)

交互流程：
  启动自检 → 简历不存在时引导上传 → 自动实时抓取招聘会数据（存入 Session State）
  第一步：招聘会初筛 → 列出未举办且有企业列表的招聘会，用户勾选场次
  第二步：岗位级精细过滤 → 按硬性条件过滤
  第三步：AI 智能匹配与排序 → 调用 mimo-v2.5-pro 评分并降序排列
  第四步：日志导出 → 用户勾选最终岗位，生成申请日志

启动命令：streamlit run app.py
"""

import json
import os
import re
import asyncio
import sys
from datetime import datetime

# Windows 下必须使用 ProactorEventLoop，否则 Playwright 的
# create_subprocess_exec 会抛出 NotImplementedError
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import pdfplumber
import streamlit as st
from openai import OpenAI

# ========================= 配置区 =========================

# OpenAI API 配置（严格按规范）
API_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
API_MODEL = "mimo-v2.5-pro"
API_MAX_COMPLETION_TOKENS = 2048
API_TEMPERATURE = 1.0
API_TOP_P = 0.95

# 简历路径（保持不变）
RESUME_PATH = "resume.pdf"
LOG_PATH = "job_matching_log.txt"

# 时间格式
TIME_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2})")

# ========================= 配置区结束 =========================


# ─────────────────── 数据实时抓取 ───────────────────

def fetch_data_live() -> dict:
    """
    实时抓取招聘会数据（三阶段全链路），返回完整数据集。
    
    返回格式：
    {
        "fairs": [...],       # 招聘会列表（第一阶段）
        "jobs": [...]         # 完整岗位数据（第三阶段输出）
    }
    
    如果任一阶段失败，返回 None 并在 session_state 中记录错误。
    """
    # 第一阶段：抓取招聘会列表
    from jobfair import fetch_fair_list
    fairs = fetch_fair_list()
    if not fairs:
        st.error("❌ 招聘会列表抓取失败，请检查网络连接或就业网是否可访问。")
        return None

    # 第二阶段：抓取岗位详情
    from jobfair_detail import scrape_all_details
    import asyncio
    jobs_with_details = asyncio.run(scrape_all_details(fairs, save_csv=False))
    if not jobs_with_details:
        st.error("❌ 岗位详情抓取失败，未提取到任何结构化岗位数据。")
        return None

    # 第三阶段：深度爬取职位要求
    from jobfair_full import enrich_all_jobs
    full_jobs = asyncio.run(enrich_all_jobs(jobs_with_details, save_csv=False))
    if not full_jobs:
        st.error("❌ 职位深度信息爬取失败。")
        return None

    return {
        "fairs": fairs,
        "jobs": full_jobs,
    }


def ensure_data_loaded() -> bool:
    """
    确保 session_state 中已有数据。如果没有，则自动触发实时抓取。
    返回 True 表示数据就绪，False 表示抓取失败。
    """
    if "all_jobs" in st.session_state and st.session_state.all_jobs:
        return True

    # 首次加载：自动抓取
    with st.spinner("🌐 正在实时连接重庆大学就业网获取最新岗位，请耐心等待（约 3-10 分钟）..."):
        data = fetch_data_live()

    if data is None:
        return False

    st.session_state.all_jobs = data["jobs"]
    st.session_state.fair_list = data["fairs"]
    st.session_state.fetch_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return True


# ─────────────────── 工具函数 ───────────────────

def get_api_key() -> str:
    """
    获取 API Key，优先级：
    1. 环境变量 MIMO_API_KEY
    2. 当前目录下 .env 文件中的 MIMO_API_KEY
    返回空字符串表示未配置。
    """
    key = os.environ.get("MIMO_API_KEY", "")
    if key:
        return key

    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("MIMO_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")

    return ""


def parse_fair_time(time_str: str) -> datetime | None:
    """
    从举办时间字符串中提取开始时间。
    示例输入："2026-05-28 14:30-17:30 （周四）"
    提取结果："2026-05-28 14:30" → datetime 对象
    """
    match = TIME_PATTERN.search(time_str)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M")
        except ValueError:
            return None
    return None


def is_fair_upcoming(time_str: str) -> bool:
    """判断招聘会是否尚未举办（开始时间晚于当前时间）"""
    fair_time = parse_fair_time(time_str)
    if fair_time is None:
        return False
    return fair_time > datetime.now()


# ─────────────────── 简历解析 ───────────────────

def load_resume(pdf_path: str) -> str:
    """
    使用 pdfplumber 解析 PDF 简历，返回纯文本内容。
    如果文件不存在或解析失败，返回空字符串。
    """
    if not os.path.exists(pdf_path):
        return ""
    try:
        text_parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n".join(text_parts)
    except Exception as e:
        st.error(f"简历解析失败: {e}")
        return ""


# ─────────────────── 招聘会提取 ───────────────────

def extract_unique_fairs(jobs: list[dict]) -> list[dict]:
    """
    从职位列表中提取去重的招聘会场次信息。
    返回列表，按时间升序排列。
    """
    fair_map = {}
    for job in jobs:
        name = job.get("招聘会名称", "").strip()
        if not name:
            continue
        if name not in fair_map:
            fair_map[name] = {
                "name": name,
                "venue": job.get("举办地点", ""),
                "time": job.get("举办时间", ""),
                "time_parsed": parse_fair_time(job.get("举办时间", "")),
                "job_count": 0,
            }
        fair_map[name]["job_count"] += 1

    fairs = list(fair_map.values())
    fairs.sort(key=lambda f: f["time_parsed"] or datetime.max)
    return fairs


# ─────────────────── 岗位过滤 ───────────────────

def filter_jobs_by_criteria(
    jobs: list[dict],
    fair_names: set[str],
    selected_natures: list[str],
    selected_scales: list[str],
) -> list[dict]:
    """
    从全量岗位中筛选出：
    1. 属于用户选中的招聘会场次
    2. 满足硬性条件（单位性质、单位规模）
    
    "见详情"/"无法判断"/空值 → 默认保留，不予筛除。
    """
    skip_values = {"见详情", "无法判断", "", "未知"}

    filtered = []
    for job in jobs:
        if job.get("招聘会名称", "").strip() not in fair_names:
            continue

        nature = job.get("单位性质", "").strip()
        if nature not in skip_values and nature not in selected_natures:
            continue

        scale = job.get("单位规模", "").strip()
        if scale not in skip_values and scale not in selected_scales:
            continue

        filtered.append(job)

    return filtered


# ─────────────────── AI 匹配核心逻辑 ───────────────────

# 截断阈值（字符数）
RESUME_TRUNCATE_LIMIT = 1500   # 简历截断较短，给 AI 留足输出空间
JOB_REQ_TRUNCATE_LIMIT = 2000  # 职位要求截断


SYSTEM_PROMPT = (
    "You are a professional job-candidate matching evaluation system. "
    "You MUST return ONLY a raw JSON object. "
    "Do NOT include any Markdown blocks, backticks (```), "
    "or explanatory text before or after the JSON."
)


def _strip_markdown_fences(text: str) -> str:
    """移除 AI 可能返回的 Markdown 代码块标记（```json ... ```）"""
    text = re.sub(r"```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```", "", text)
    return text.strip()


def _extract_json_object(raw: str) -> str | None:
    """
    从原始 AI 返回中稳健提取 JSON 对象字符串。
    
    步骤：
    1. 先移除 Markdown 围栏标记
    2. 用正则匹配第一个 { 到最后一个 } 之间的内容
    3. Fallback: find/rfind
    """
    cleaned = _strip_markdown_fences(raw)

    # 正则：贪婪匹配最外层的 {...}
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        return match.group(0)

    # Fallback: find / rfind
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start != -1 and end > start:
        return cleaned[start:end]

    return None


def _repair_truncated_json(raw: str) -> dict | None:
    """
    断尾修复：当 JSON 被截断（缺少闭合括号）时，尝试手动提取 score。
    
    场景：AI 返回了 {"score": 85, "reason": "专业高度...  但没写完最后一个 }
    策略：如果包含 "score": 则用字符串切割提取分数，reason 填默认提示。
    """
    cleaned = _strip_markdown_fences(raw)

    # 尝试提取 score 值
    score_match = re.search(r'"score"\s*:\s*(\d+)', cleaned)
    if not score_match:
        return None

    score = int(score_match.group(1))

    # 尝试提取 reason（可能不完整）
    reason = "（理由生成中途截断，请点击详情查看）"
    reason_match = re.search(r'"reason"\s*:\s*"((?:[^"\\]|\\.)*)', cleaned)
    if reason_match:
        partial_reason = reason_match.group(1).strip()
        if partial_reason:
            reason = partial_reason + "…（截断）"

    return {"score": score, "reason": reason}


def _call_api_once(client: OpenAI, prompt: str) -> str:
    """
    执行一次 API 调用，返回原始文本。
    异常由调用方捕获。
    """
    response = client.chat.completions.create(
        model=API_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_completion_tokens=API_MAX_COMPLETION_TOKENS,
        temperature=API_TEMPERATURE,
        top_p=API_TOP_P,
    )
    return response.choices[0].message.content.strip()


def call_ai_match(client: OpenAI, resume_text: str, job_info: dict) -> dict:
    """
    调用 AI API 对简历与单个职位进行匹配评分。
    
    严格使用规范参数：
    - model="mimo-v2.5-pro"
    - max_completion_tokens=2048
    - temperature=1.0
    - top_p=0.95
    
    特性：
    - 自动重试：如果首次返回为空或 JSON 解析失败，自动发起第二次请求
    - Robust JSON 提取：先剥离 Markdown 围栏，再正则匹配
    - Fallback：解析失败时返回原始文本而非直接打 0 分
    
    返回格式：
        {"score": 85, "reason": "专业高度对口，且具备..."}
    """
    # 截断机制：防止内容过长导致 API 异常
    # 简历截断更短（1500字），给 AI 留足输出空间完成 JSON
    truncated_resume = resume_text[:RESUME_TRUNCATE_LIMIT]
    job_requirement = job_info.get("职位要求", "无")
    if len(job_requirement) > JOB_REQ_TRUNCATE_LIMIT:
        job_requirement = job_requirement[:JOB_REQ_TRUNCATE_LIMIT] + "..."

    prompt = f"""你是一位资深的求职顾问。请根据以下简历内容和职位信息，评估该求职者与职位的匹配程度。

## 求职者简历
{truncated_resume}

## 职位信息
- 单位名称：{job_info.get('单位全称', '未知')}
- 职位名称：{job_info.get('职位名称', '未知')}
- 需求人数：{job_info.get('需求人数', '未知')}
- 需求专业：{job_info.get('需求专业', '未知')}
- 单位性质：{job_info.get('单位性质', '未知')}
- 单位规模：{job_info.get('单位规模', '未知')}
- 工作地点：{job_info.get('工作地点', '未知')}
- 职位要求：{job_requirement}

## 评分规则
请从以下维度综合评估（满分100分）：
1. 专业匹配度（30分）
2. 技能匹配度（30分）
3. 学历匹配度（15分）
4. 经验匹配度（15分）
5. 地域偏好（10分）

## 输出要求
请 **只返回** 一个合法的 JSON 对象，**不要** 添加任何 Markdown 代码块标记（如 ```json）、注释或其他多余文字。
格式如下（reason 不超过150字）：
{{"score": <0-100的整数>, "reason": "<150字以内的简要评价>"}}"""

    max_attempts = 2  # 最多重试 1 次（共 2 次尝试）
    last_raw = ""
    last_error = ""

    for attempt in range(1, max_attempts + 1):
        try:
            raw = _call_api_once(client, prompt)
            last_raw = raw

            json_str = _extract_json_object(raw)

            if json_str:
                result = json.loads(json_str)
                score = int(result.get("score", 0))
                reason = str(result.get("reason", "无评价"))
                return {"score": score, "reason": reason, "raw": raw}

            # 无法提取完整 JSON — 尝试断尾修复
            repaired = _repair_truncated_json(raw)
            if repaired:
                return {"score": repaired["score"], "reason": repaired["reason"], "raw": raw}

            # 断尾修复也失败 — 记录并决定是否重试
            last_error = "未找到 JSON 对象"
            if attempt < max_attempts:
                continue  # 重试一次
            # 已用完重试次数，返回 fallback（保留原始文本）
            return {
                "score": -1,
                "reason": f"解析失败（{last_error}）",
                "raw": raw,
            }

        except json.JSONDecodeError as e:
            last_error = f"JSONDecodeError: {str(e)[:80]}"
            last_raw = last_raw if last_raw else "(空)"

            # JSON 解析失败前先尝试断尾修复
            repaired = _repair_truncated_json(last_raw)
            if repaired:
                return {"score": repaired["score"], "reason": repaired["reason"], "raw": last_raw}

            if attempt < max_attempts:
                continue  # 重试一次
            return {
                "score": -1,
                "reason": f"解析失败（{last_error}）",
                "raw": last_raw,
            }

        except Exception as e:
            # API 调用级别的异常（网络超时、鉴权失败等）— 不重试
            error_type = type(e).__name__
            error_detail = str(e)[:120]
            return {"score": 0, "reason": f"[{error_type}] {error_detail}", "raw": ""}

    # 理论上不会到这里，作为保底
    return {"score": 0, "reason": f"未知错误", "raw": last_raw}


# ─────────────────── 导出申请日志 ───────────────────

def export_log(selected_jobs: list[dict], log_path: str) -> str:
    """
    将用户最终选择的岗位信息、AI 评分和理由写入日志文件。
    返回日志文件路径。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "=" * 70,
        "  CQU 求职智能 Agent - 申请日志",
        f"  匹配时间：{now}",
        "=" * 70,
        "",
    ]

    for i, job in enumerate(selected_jobs, start=1):
        lines.append(f"━━━ 【{i}】{job.get('职位名称', '未知')} ━━━")
        lines.append(f"  所属招聘会：{job.get('招聘会名称', '未知')}")
        lines.append(f"  单位全称：{job.get('单位全称', '未知')}")
        lines.append(f"  单位性质：{job.get('单位性质', '未知')}")
        lines.append(f"  单位规模：{job.get('单位规模', '未知')}")
        lines.append(f"  职位名称：{job.get('职位名称', '未知')}")
        lines.append(f"  需求人数：{job.get('需求人数', '未知')}")
        lines.append(f"  需求专业：{job.get('需求专业', '未知')}")
        lines.append(f"  工作地点：{job.get('工作地点', '未知')}")
        lines.append(f"  举办时间：{job.get('举办时间', '未知')}")
        lines.append(f"  举办地点：{job.get('举办地点', '未知')}")
        lines.append(f"  AI 评分：{job.get('ai_score', '未评分')} 分")
        lines.append(f"  AI 推荐建议：{job.get('ai_reason', '无')}")
        lines.append(f"  详情链接：{job.get('详情链接', '无')}")
        req = job.get("职位要求", "无")
        if len(req) > 500:
            req = req[:500] + "..."
        lines.append(f"  职位要求：{req}")
        lines.append("")

    lines.append("=" * 70)
    lines.append(f"  共 {len(selected_jobs)} 个岗位 | 祝求职顺利！")
    lines.append("=" * 70)

    content = "\n".join(lines)

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(content)

    return log_path


# ─────────────────── Streamlit 主界面 ───────────────────

def main():
    # 页面配置
    st.set_page_config(
        page_title="CQU JobWise 求职智能 Agent",
        page_icon="🎯",
        layout="wide",
    )

    # ===================== 自定义 CSS =====================
    st.markdown(
        """
        <style>
        /* ── 全局字体与间距微调 ── */
        .block-container {
            padding-bottom: 4rem;
        }

        /* ── 侧边栏品牌标识 ── */
        .sidebar-brand {
            text-align: center;
            padding: 0.8rem 0.4rem 0.4rem 0.4rem;
        }
        .sidebar-brand img {
            max-width: 100%;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
        }
        .sidebar-brand-fallback {
            font-size: 1.4rem;
            font-weight: 700;
            color: #1a73e8;
            letter-spacing: 2px;
            padding: 1.2rem 0;
        }

        /* ── 匹配结果卡片优化 ── */
        div[data-testid="stContainer"][border="true"] {
            padding: 1.1rem 1.2rem 0.8rem 1.2rem !important;
            margin-bottom: 0.8rem !important;
            border-radius: 10px !important;
            border: 1px solid rgba(128,128,128,0.25) !important;
            transition: box-shadow 0.2s ease;
        }
        div[data-testid="stContainer"][border="true"]:hover {
            box-shadow: 0 2px 12px rgba(0,0,0,0.10);
        }

        /* ── 页脚样式 ── */
        .app-footer {
            position: fixed;
            bottom: 0;
            left: 0;
            width: 100%;
            padding: 0.5rem 1.5rem;
            text-align: center;
            font-size: 0.78rem;
            color: rgba(128,128,128,0.7);
            background: transparent;
            z-index: 999;
            pointer-events: none;
        }
        .app-footer a {
            color: rgba(100,149,237,0.7);
            text-decoration: none;
        }
        .app-footer a:hover {
            text-decoration: underline;
        }
        /* 深色模式适配 */
        @media (prefers-color-scheme: dark) {
            .app-footer {
                color: rgba(200,200,200,0.5);
            }
            .app-footer a {
                color: rgba(130,170,255,0.6);
            }
        }
        /* Streamlit 深色主题适配 */
        [data-theme="dark"] .app-footer {
            color: rgba(200,200,200,0.5);
        }
        [data-theme="dark"] .app-footer a {
            color: rgba(130,170,255,0.6);
        }

        /* ── 免责声明样式 ── */
        .disclaimer-text {
            font-size: 0.78rem;
            color: rgba(128,128,128,0.85);
            line-height: 1.6;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ===================== 页脚 =====================
    st.markdown(
        """
        <div class="app-footer">
            © 2026 CQU JobWise | Designed by <strong>Sadfrog0103</strong>
            &nbsp;|&nbsp; 核心驱动：Powered by <strong>MiMo-V2.5-Pro</strong>
            &nbsp;|&nbsp; 联系方式：<a href="mailto:2281939844@qq.com">2281939844@qq.com</a>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ===================== 侧边栏品牌标识 =====================
    with st.sidebar:
        logo_path = os.path.join(os.path.dirname(__file__), "CQU JobWise.png")
        if os.path.exists(logo_path):
            st.markdown('<div class="sidebar-brand">', unsafe_allow_html=True)
            st.image(logo_path, use_column_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.markdown(
                '<div class="sidebar-brand"><span class="sidebar-brand-fallback">🎯 CQU JobWise</span></div>',
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)

    st.title("🎯 CQU 求职智能 Agent")
    st.caption("重庆大学就业网招聘会 → AI 智能匹配 → 精准投递")

    # ===================== 启动自检 =====================

    resume_exists = os.path.exists(RESUME_PATH)

    # ── 简历自检：自动检测 + 上传组件 ──
    if not resume_exists:
        st.warning("⚠️ 未检测到简历文件 `resume.pdf`，请上传你的简历 PDF：")
        uploaded_file = st.file_uploader(
            "上传简历 PDF",
            type=["pdf"],
            key="resume_upload",
            label_visibility="collapsed",
        )
        if uploaded_file is not None:
            with open(RESUME_PATH, "wb") as f:
                f.write(uploaded_file.getvalue())
            st.success("✅ 简历已保存为 `resume.pdf`")
            st.rerun()
        st.stop()

    # ===================== 数据加载（Session State 驱动） =====================

    resume_text = load_resume(RESUME_PATH)
    resume_loaded = bool(resume_text.strip())

    # 确保数据已加载到 session_state
    data_ready = ensure_data_loaded()
    if not data_ready:
        st.stop()

    all_jobs = st.session_state.all_jobs
    fetch_time = st.session_state.get("fetch_time", "未知")

    if not all_jobs:
        st.error("❌ 实时抓取完成但未获取到任何职位数据，请检查就业网状态。")
        st.stop()

    unique_fairs = extract_unique_fairs(all_jobs)

    upcoming_fairs = [
        f for f in unique_fairs
        if is_fair_upcoming(f["time"]) and f["job_count"] > 0
    ]

    # ── 提取筛选选项 ──
    all_nature_values = sorted(
        set(
            j.get("单位性质", "")
            for j in all_jobs
            if j.get("单位性质", "") and j.get("单位性质", "") != "见详情"
        )
    )
    all_scale_values = sorted(
        set(
            j.get("单位规模", "")
            for j in all_jobs
            if j.get("单位规模", "") and j.get("单位规模", "") != "见详情"
        )
    )
    scale_order = {
        "少于50人": 1, "50-150人": 2, "150-500人": 3,
        "500-1000人": 4, "1000-5000人": 5,
        "5000-10000人": 6, "10000人以上": 7,
    }

    api_key = get_api_key()

    # ===================== 侧边栏 =====================
    with st.sidebar:
        st.header("📄 简历状态")
        if resume_loaded:
            st.success("✅ 简历已加载")
            with st.expander("查看简历文本预览"):
                st.text(resume_text[:500] + ("..." if len(resume_text) > 500 else ""))
        else:
            st.error(f"❌ 简历文本为空（PDF 可能无法解析）")

        st.divider()

        # ── 刷新实时数据按钮 ──
        st.header("🔄 数据管理")
        st.caption(f"⏰ 数据抓取时间：{fetch_time}")
        if st.button("🔄 刷新实时数据", type="secondary", use_container_width=True):
            # 清空 session_state 中的旧数据和相关缓存
            keys_to_clear = [
                "all_jobs", "fair_list", "fetch_time",
                "selected_fair_names", "extracted_jobs", "match_results",
            ]
            for key in keys_to_clear:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()

        st.divider()
        st.header("📋 硬性筛选器")
        st.caption('勾选你接受的条件。"见详情"默认保留。')

        st.subheader("单位性质")
        selected_natures = []
        for nature in all_nature_values:
            if st.checkbox(nature, value=True, key=f"nature_{nature}"):
                selected_natures.append(nature)

        st.subheader("单位规模")
        sorted_scales = sorted(
            all_scale_values, key=lambda s: scale_order.get(s, 99)
        )
        selected_scales = []
        for scale in sorted_scales:
            if st.checkbox(scale, value=True, key=f"scale_{scale}"):
                selected_scales.append(scale)

        st.divider()
        st.header("⚙️ AI 配置")
        if api_key:
            st.success("✅ API Key 已配置")
            st.caption(f"Key: {api_key[:8]}...{api_key[-4:]}")
        else:
            st.warning("⚠️ 未检测到 API Key")
            st.caption("请设置环境变量 MIMO_API_KEY 或创建 .env 文件")
        st.text(f"模型：{API_MODEL}")
        st.text(f"接口：{API_BASE_URL}")

        st.divider()

        # ── 免责声明 ──
        with st.expander("📜 免责声明"):
            st.markdown(
                '<p class="disclaimer-text">'
                "本工具基于 AI 模型生成建议，仅供求职参考，不代表校方官方立场。"
                "匹配评分结果为算法自动生成，可能存在偏差，请结合实际情况综合判断。"
                "</p>",
                unsafe_allow_html=True,
            )

    # ===================== 主界面 =====================

    # 初始化 session_state
    if "selected_fair_names" not in st.session_state:
        st.session_state.selected_fair_names = set()
    if "extracted_jobs" not in st.session_state:
        st.session_state.extracted_jobs = []
    if "match_results" not in st.session_state:
        st.session_state.match_results = {}

    # ━━━━━━━━━━ 第一步：招聘会初筛 ━━━━━━━━━━
    st.header("第一步：选择招聘会场次")
    st.caption("以下为尚未举办且包含企业岗位信息的招聘会，请勾选你感兴趣的场次。")

    if not upcoming_fairs:
        st.info("📭 当前没有即将举办的招聘会数据。")
        st.stop()

    fair_selected_names = set()
    for idx, fair in enumerate(upcoming_fairs):
        col_check, col_info = st.columns([0.05, 0.95])
        with col_check:
            checked = st.checkbox(
                "选择",
                key=f"fair_{idx}",
                label_visibility="collapsed",
            )
        with col_info:
            time_display = fair["time"] if fair["time"] else "时间待定"
            venue_display = fair["venue"] if fair["venue"] else "地点待定"

            st.markdown(f"### 📢 {fair['name']}")
            st.caption(
                f"📍 {venue_display}  |  🕐 {time_display}  |  "
                f"📋 共 **{fair['job_count']}** 个岗位"
            )

        if checked:
            fair_selected_names.add(fair["name"])

    st.session_state.selected_fair_names = fair_selected_names

    # ━━━━━━━━━━ 第二步：岗位级精细过滤 ━━━━━━━━━━
    st.divider()

    col_extract, _ = st.columns([1, 3])
    with col_extract:
        extract_clicked = st.button(
            "🔍 提取详细岗位",
            type="primary",
            use_container_width=True,
            disabled=len(fair_selected_names) == 0,
        )

    if extract_clicked:
        if not fair_selected_names:
            st.warning("请先勾选至少一个招聘会场次！")
        else:
            filtered = filter_jobs_by_criteria(
                all_jobs,
                fair_selected_names,
                selected_natures,
                selected_scales,
            )
            st.session_state.extracted_jobs = filtered
            st.session_state.match_results = {}

            st.success(
                f"✅ 从 {len(fair_selected_names)} 个场次中提取到 "
                f"**{len(filtered)}** 个符合硬性条件的岗位"
            )

    # ━━━━━━━━━━ 第二步续：岗位二次勾选 ━━━━━━━━━━
    extracted_jobs = st.session_state.extracted_jobs

    if extracted_jobs:
        st.divider()
        st.header("第二步：选择感兴趣的岗位")
        st.info(
            f"📋 共提取到 **{len(extracted_jobs)}** 个符合硬性条件的岗位。\n\n"
            "请在下方勾选您最感兴趣的岗位进行 AI 深度匹配"
            "（**建议不超过 10 个**），以确保匹配速度和准确度。"
        )

        # 展示过滤后的岗位列表，每个岗位带 Checkbox + 可点击的详情链接
        selected_job_indices = []
        for idx, job in enumerate(extracted_jobs):
            nature = job.get("单位性质", "")
            scale = job.get("单位规模", "")
            location = job.get("工作地点", "")
            detail_link = job.get("详情链接", "").strip()

            detail_parts = []
            if nature and nature not in ("见详情", "", "未知"):
                detail_parts.append(nature)
            if scale and scale not in ("见详情", "", "未知"):
                detail_parts.append(scale)
            if location and location not in ("见详情", "", "未知"):
                detail_parts.append(location)
            detail_str = " | ".join(detail_parts) if detail_parts else "详情见原链接"

            label = (
                f"**{job.get('单位全称', '未知')}** — "
                f"{job.get('职位名称', '未知')}  "
                f"({detail_str})"
            )

            col_check, col_link = st.columns([0.92, 0.08])
            with col_check:
                if st.checkbox(
                    label,
                    key=f"job_select_{idx}",
                    value=False,
                ):
                    selected_job_indices.append(idx)
            with col_link:
                if detail_link:
                    st.link_button("🔗 详情", detail_link, use_container_width=True)

        # 匹配触发按钮
        st.divider()
        col_ai, col_hint = st.columns([1, 2])
        with col_ai:
            ai_clicked = st.button(
                "🚀 开始 AI 简历匹配",
                type="primary",
                use_container_width=True,
                disabled=not resume_loaded or not api_key,
            )

        if not resume_loaded:
            st.warning("⚠️ 简历文本为空，请确认 PDF 可正常解析。")
        if not api_key:
            st.warning(
                "⚠️ 请配置 API Key：设置环境变量 `MIMO_API_KEY` "
                "或在项目根目录创建 `.env` 文件写入 `MIMO_API_KEY=你的key`"
            )

        # ━━━━━━━━━━ 第三步：AI 智能匹配（仅对已勾选岗位） ━━━━━━━━━━
        if ai_clicked:
            if not selected_job_indices:
                st.warning("⚠️ 请先勾选至少一个您感兴趣的岗位，再开始 AI 匹配！")
            else:
                try:
                    client = OpenAI(
                        api_key=api_key,
                        base_url=API_BASE_URL,
                    )
                except Exception as e:
                    st.error(f"创建 API 客户端失败: {e}")
                    st.stop()

                # 仅对用户勾选的岗位进行 AI 匹配
                jobs_to_match = [extracted_jobs[i] for i in selected_job_indices]
                total = len(jobs_to_match)

                st.session_state.match_results = {}

                st.info(
                    f"🤖 正在为 **{total}** 个已选岗位进行 AI 匹配评估，请稍候..."
                )

                progress_bar = st.progress(0)
                progress_text = st.empty()

                for i, job in enumerate(jobs_to_match):
                    original_idx = selected_job_indices[i]
                    job_label = f"{job.get('单位全称', '')} - {job.get('职位名称', '')}"

                    with st.spinner(f"🤖 AI 正在深度分析第 {i + 1}/{total} 个岗位：{job_label} ..."):
                        result = call_ai_match(client, resume_text, job)

                    # 使用原始 extracted_jobs 中的索引作为 key
                    st.session_state.match_results[original_idx] = result

                    progress_bar.progress((i + 1) / total)

                progress_text.text("✅ AI 匹配完成！")
                st.rerun()

        # ━━━━━━━━━━ 展示匹配结果（按分数降序） ━━━━━━━━━━
        if st.session_state.match_results:
            st.divider()
            st.header("🏆 AI 匹配结果排名")

            sorted_results = sorted(
                st.session_state.match_results.items(),
                key=lambda x: x[1]["score"],
                reverse=True,
            )

            for rank, (idx, result) in enumerate(sorted_results, start=1):
                job = extracted_jobs[idx]
                score = result["score"]
                reason = result["reason"]
                link = job.get("详情链接", "")

                raw_text = result.get("raw", "")

                if score == -1:
                    badge_color = "gray"
                    emoji = "⚠️"
                    score_display = "解析失败"
                elif score >= 80:
                    badge_color = "green"
                    emoji = "🟢"
                    score_display = f"{score}分"
                elif score >= 60:
                    badge_color = "orange"
                    emoji = "🟡"
                    score_display = f"{score}分"
                else:
                    badge_color = "red"
                    emoji = "🔴"
                    score_display = f"{score}分"

                with st.container(border=True):
                    st.markdown(
                        f"{emoji} **第{rank}名** &nbsp; "
                        f":{badge_color}[**{score_display}**] &nbsp; "
                        f"**{job.get('单位全称', '未知')}** — "
                        f"**{job.get('职位名称', '未知')}**"
                    )

                    if score == -1:
                        st.markdown(f"> 💬 **AI 评价：** {reason}")
                        if raw_text:
                            with st.expander("🔍 查看 AI 原始返回（调试用）"):
                                st.code(raw_text, language="text")
                    else:
                        st.markdown(f"> 💬 **AI 评价：** {reason}")

                    info_parts = []
                    if job.get("单位性质", "见详情") not in ("见详情", "", "未知"):
                        info_parts.append(f"性质: {job['单位性质']}")
                    if job.get("单位规模", "见详情") not in ("见详情", "", "未知"):
                        info_parts.append(f"规模: {job['单位规模']}")
                    if job.get("工作地点", "见详情") not in ("见详情", "", "未知"):
                        info_parts.append(f"地点: {job['工作地点']}")
                    if job.get("需求专业", ""):
                        info_parts.append(f"专业: {job['需求专业'][:60]}")
                    info_parts.append(f"招聘会: {job.get('招聘会名称', '')[:30]}")

                    st.caption("  |  ".join(info_parts))

                    if link:
                        st.link_button("🔗 查看详情页", link)

        # ━━━━━━━━━━ 第四步：日志导出（仅导出 AI 匹配过的岗位） ━━━━━━━━━━
        if st.session_state.match_results:
            st.divider()
            st.header("第三步：生成申请日志")
            st.caption("在 AI 匹配结果中，勾选你最终决定投递的岗位：")

            sorted_for_export = sorted(
                st.session_state.match_results.items(),
                key=lambda x: x[1]["score"],
                reverse=True,
            )

            export_indices = []
            for idx, result in sorted_for_export:
                job = extracted_jobs[idx]
                score = result["score"]
                if score == -1:
                    label = f":gray[⚠️ 解析失败] {job.get('单位全称', '未知')} — {job.get('职位名称', '未知')}"
                else:
                    label = (
                        f":{ 'green' if score >= 80 else 'orange' if score >= 60 else 'red'}"
                        f"[{score}分] "
                        f"{job.get('单位全称', '未知')} — {job.get('职位名称', '未知')}"
                    )
                if st.checkbox(
                    label,
                    key=f"export_{idx}",
                    value=score >= 70,
                ):
                    export_indices.append(idx)

            st.divider()
            col_export, _ = st.columns([1, 3])
            with col_export:
                export_clicked = st.button(
                    "📄 生成日志",
                    type="secondary",
                    use_container_width=True,
                    disabled=len(export_indices) == 0,
                )

            if export_clicked:
                if not export_indices:
                    st.warning("请先勾选至少一个要导出的岗位！")
                else:
                    export_data = []
                    for idx in export_indices:
                        job = extracted_jobs[idx].copy()
                        result = st.session_state.match_results[idx]
                        job["ai_score"] = result["score"]
                        job["ai_reason"] = result["reason"]
                        export_data.append(job)

                    log_path = export_log(export_data, LOG_PATH)
                    st.success(
                        f"✅ 申请日志已生成：`{log_path}`（共 {len(export_data)} 个岗位）"
                    )

                    with open(log_path, "r", encoding="utf-8") as f:
                        log_content = f.read()
                    st.download_button(
                        label="⬇️ 下载申请日志",
                        data=log_content,
                        file_name="job_matching_log.txt",
                        mime="text/plain",
                    )


# ========================= 程序入口 =========================
if __name__ == "__main__":
    main()