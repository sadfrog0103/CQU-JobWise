"""
重庆大学就业网 - 职位详情页深度爬虫（第三阶段）
读取第二阶段生成的 jobs_with_details.csv，逐个访问职位详情页，
提取：单位性质、单位规模、职位要求、工作地点。
最终生成终极版 full_job_database.csv。

依赖：pip install playwright && playwright install msedge
"""

import csv
import re
import asyncio
import random
from urllib.parse import urljoin

from playwright.async_api import async_playwright


# ========================= 配置区 =========================

BASE_URL = "https://cqu.cqbys.com"

# 第二阶段输出文件（输入）
DETAILS_CSV = "jobs_with_details.csv"

# 第三阶段最终输出
OUTPUT_CSV = "full_job_database.csv"

# 最终 CSV 表头
OUTPUT_HEADERS = [
    "招聘会名称", "举办地点", "举办时间",
    "单位全称", "职位名称", "需求人数", "需求专业",
    "单位性质", "单位规模", "工作地点",
    "职位要求", "详情链接",
]

# 并发控制（用户要求 ≤ 5）
MAX_CONCURRENCY = 5

# 超时设置（毫秒）
PAGE_TIMEOUT = 30_000
DETAIL_WAIT_TIMEOUT = 8_000

# 随机 User-Agent 列表
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

# 默认占位文本（当字段不存在时使用）
DEFAULT_TEXT = "见详情"

# ========================= 配置区结束 =========================


def get_random_ua() -> str:
    """返回一个随机 User-Agent。"""
    return random.choice(USER_AGENTS)


def clean_text(text: str) -> str:
    """清理文本：去除多余空白、换行符等。"""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def read_details_csv(filepath: str) -> list[dict]:
    """
    读取第二阶段的 jobs_with_details.csv。
    返回字典列表。
    """
    rows = []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


async def enrich_all_jobs(all_jobs: list[dict], save_csv: bool = True) -> list[dict]:
    """
    第三阶段主流程（可被 app.py 调用）：
    1. 接收第二阶段的岗位列表
    2. 去重链接（同一 URL 只访问一次，结果共享）
    3. 并发访问各职位详情页
    4. 合并数据
    5. 可选保存终极版 CSV

    参数:
        all_jobs: 第二阶段输出的岗位列表
        save_csv: 是否同时保存 CSV 文件（standalone 模式为 True）

    返回:
        list[dict]: 包含完整信息的岗位列表
    """
    if not all_jobs:
        print("[错误] 职位列表为空。")
        return []

    print(f"[信息] 共 {len(all_jobs)} 条职位待深度爬取")

    # ---- 链接去重 ----
    url_to_indices: dict[str, list[int]] = {}
    for idx, job in enumerate(all_jobs):
        url = job.get("职位原链接", "").strip()
        if url:
            if url not in url_to_indices:
                url_to_indices[url] = []
            url_to_indices[url].append(idx)

    unique_urls = list(url_to_indices.keys())
    print(f"[信息] 去重后需访问 {len(unique_urls)} 个独立详情页（节省 {len(all_jobs) - len(unique_urls)} 次请求）")

    # ---- 并发爬取详情页 ----
    async with async_playwright() as pw:
        print("[信息] 正在启动 Edge 浏览器...")
        browser = await pw.chromium.launch(channel="msedge", headless=True)

        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

        context = await browser.new_context(
            user_agent=get_random_ua(),
            viewport={"width": 1920, "height": 1080},
        )

        print(f"[信息] 开始并发爬取详情页（并发数: {MAX_CONCURRENCY}）...")

        async def fetch_detail(url: str) -> dict:
            page = await context.new_page()
            try:
                temp_info = {
                    "职位原链接": url,
                    "单位全称": "",
                    "职位名称": "",
                }
                first_idx = url_to_indices[url][0]
                temp_info["单位全称"] = all_jobs[first_idx].get("单位全称", "")
                temp_info["职位名称"] = all_jobs[first_idx].get("职位名称", "")
                detail = await scrape_job_detail(page, temp_info, semaphore)
                return detail
            finally:
                await page.close()

        tasks = [fetch_detail(url) for url in unique_urls]
        detail_results = await asyncio.gather(*tasks, return_exceptions=True)

        await context.close()
        await browser.close()
        print("[信息] 浏览器已关闭。")

    # ---- 合并数据 ----
    url_to_detail: dict[str, dict] = {}
    for result in detail_results:
        if isinstance(result, Exception):
            print(f"  [错误] 任务异常: {result}")
            continue
        url = result.get("职位原链接", "").strip()
        if url:
            url_to_detail[url] = result

    final_records = []
    for job in all_jobs:
        url = job.get("职位原链接", "").strip()
        detail = url_to_detail.get(url, {})
        final_records.append({
            "招聘会名称": job.get("招聘会名称", ""),
            "举办地点": job.get("举办地点", ""),
            "举办时间": job.get("举办时间", ""),
            "单位全称": job.get("单位全称", ""),
            "职位名称": job.get("职位名称", ""),
            "需求人数": job.get("需求人数", ""),
            "需求专业": job.get("需求专业", ""),
            "单位性质": detail.get("单位性质", DEFAULT_TEXT),
            "单位规模": detail.get("单位规模", DEFAULT_TEXT),
            "工作地点": detail.get("工作地点", DEFAULT_TEXT),
            "职位要求": detail.get("职位要求", DEFAULT_TEXT),
            "详情链接": url if url else DEFAULT_TEXT,
        })

    # ---- 可选保存 ----
    if save_csv:
        print(f"\n[信息] 共 {len(final_records)} 条记录准备写入")
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_HEADERS)
            writer.writeheader()
            writer.writerows(final_records)
        print(f"[信息] 终极版数据库已保存至: {OUTPUT_CSV}")

    return final_records


async def scrape_job_detail(page, job_info: dict, semaphore: asyncio.Semaphore) -> dict:
    """
    访问单个职位详情页，提取核心信息。

    提取目标：
    1. 单位性质：包含"单位性质："文本的 span 标签
    2. 单位规模：包含"单位规模："文本的 span 标签
    3. 职位要求：class 为 aContent 的 div 容器内的所有文本
    4. 工作地点：页面底部显示具体地址的 p 标签

    参数:
        page: Playwright Page 实例
        job_info: 第二阶段的职位信息字典
        semaphore: 并发信号量

    返回:
        dict: 合并了原始信息和详情信息的完整字典
    """
    url = job_info.get("职位原链接", "")
    company = job_info.get("单位全称", "未知")
    position = job_info.get("职位名称", "未知")

    # 初始化详情字段（默认值）
    result = {
        **job_info,
        "单位性质": DEFAULT_TEXT,
        "单位规模": DEFAULT_TEXT,
        "工作地点": DEFAULT_TEXT,
        "职位要求": DEFAULT_TEXT,
        "详情链接": url if url else DEFAULT_TEXT,
    }

    if not url:
        print(f"  [跳过] '{company} - {position}' 无详情链接")
        return result

    async with semaphore:
        # 随机延迟，避免瞬时大量请求
        await asyncio.sleep(random.uniform(0.5, 2.0))

        print(f"  [开始] '{company} - {position}'")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)

            # 等待页面内容区域加载
            try:
                await page.wait_for_selector(
                    "div.aContent, span, p",
                    timeout=DETAIL_WAIT_TIMEOUT,
                )
            except Exception:
                pass  # 超时后继续尝试提取

            # 额外等待一小段时间，确保动态内容渲染完成
            await asyncio.sleep(1)

            # ---- 1. 提取单位性质 ----
            # 页面结构：<label>单位性质：</label> <span>具体值</span>
            # 策略：找到包含"单位性质"的 label，取其相邻的 span 兄弟元素
            try:
                nature_label = page.locator("label:has-text('单位性质')")
                if await nature_label.count() > 0:
                    # 获取 label 的下一个兄弟 span
                    nature_span = nature_label.locator("+ span")
                    if await nature_span.count() > 0:
                        val = (await nature_span.first.inner_text()).strip()
                        if val:
                            result["单位性质"] = clean_text(val)
                    else:
                        # 备用：从 label 的父 div 中查找 span
                        parent = nature_label.locator("xpath=..")
                        nature_span = parent.locator("span")
                        if await nature_span.count() > 0:
                            val = (await nature_span.first.inner_text()).strip()
                            if val:
                                result["单位性质"] = clean_text(val)
            except Exception:
                pass

            # ---- 2. 提取单位规模 ----
            # 同样结构：<label>单位规模：</label> <span>具体值</span>
            try:
                scale_label = page.locator("label:has-text('单位规模')")
                if await scale_label.count() > 0:
                    scale_span = scale_label.locator("+ span")
                    if await scale_span.count() > 0:
                        val = (await scale_span.first.inner_text()).strip()
                        if val:
                            result["单位规模"] = clean_text(val)
                    else:
                        parent = scale_label.locator("xpath=..")
                        scale_span = parent.locator("span")
                        if await scale_span.count() > 0:
                            val = (await scale_span.first.inner_text()).strip()
                            if val:
                                result["单位规模"] = clean_text(val)
            except Exception:
                pass

            # ---- 3. 提取职位要求（div.aContent 内的所有文本） ----
            try:
                a_content = page.locator("div.aContent")
                if await a_content.count() > 0:
                    content_text = await a_content.first.inner_text()
                    result["职位要求"] = clean_text(content_text)
                else:
                    # 备用：尝试其他常见选择器
                    for selector in [
                        "div.job-detail", "div.job-desc",
                        "div.position-detail", "div.content",
                        "div.a-content",
                    ]:
                        alt_elem = page.locator(selector)
                        if await alt_elem.count() > 0:
                            content_text = await alt_elem.first.inner_text()
                            result["职位要求"] = clean_text(content_text)
                            break
            except Exception:
                pass

            # ---- 4. 提取工作地点 ----
            # 页面结构：<h5>工作地址</h5> 后紧跟 <p>具体地址</p>
            # 策略一：找到 h5 标签中的"工作地址"，取其后的 p 兄弟元素
            # 策略二：查找包含地址特征的短文本 p 标签（排除页脚长文本）
            try:
                # 策略一：通过 h5 "工作地址" 定位
                addr_heading = page.locator("h5:has-text('工作地址'), h4:has-text('工作地址'), h3:has-text('工作地址')")
                if await addr_heading.count() > 0:
                    # 获取 h5 后面紧跟的 p 兄弟元素
                    addr_p = addr_heading.locator("+ p")
                    if await addr_p.count() > 0:
                        addr_text = (await addr_p.first.inner_text()).strip()
                        if addr_text and len(addr_text) > 2:
                            result["工作地点"] = clean_text(addr_text)

                # 策略二：如果策略一失败，从 p 标签中按特征匹配
                if result["工作地点"] == DEFAULT_TEXT:
                    p_tags = page.locator("p")
                    p_count = await p_tags.count()
                    for i in range(p_count):
                        p_text = (await p_tags.nth(i).inner_text()).strip()
                        # 匹配短地址文本（< 100字符），包含地址关键字但排除页脚
                        if p_text and 4 < len(p_text) < 100:
                            if any(kw in p_text for kw in ["区", "路", "号", "栋", "园区", "大厦"]):
                                # 排除页脚文本
                                if "校园" not in p_text and "邮箱" not in p_text and "办公" not in p_text:
                                    result["工作地点"] = clean_text(p_text)
                                    break

                # 策略三：查找 div 中包含"工作地点"文字的元素
                if result["工作地点"] == DEFAULT_TEXT:
                    addr_divs = page.locator("div:has-text('工作地点'), div:has-text('工作地址')")
                    d_count = await addr_divs.count()
                    for i in range(min(d_count, 10)):
                        try:
                            div_text = (await addr_divs.nth(i).inner_text()).strip()
                            if "工作地点" in div_text or "工作地址" in div_text:
                                val = div_text.split("：", 1)[-1].strip()
                                if not val:
                                    val = div_text.split(":", 1)[-1].strip()
                                if val and 3 < len(val) < 100:
                                    result["工作地点"] = clean_text(val)
                                    break
                        except Exception:
                            continue
            except Exception:
                pass

            # 去除职位要求中的过长文本（限制为 2000 字符，避免 CSV 过大）
            if len(result["职位要求"]) > 2000:
                result["职位要求"] = result["职位要求"][:2000] + "...(已截断)"

            print(f"  [完成] '{company} - {position}' | 性质={result['单位性质']} | 规模={result['单位规模']} | 地点={result['工作地点']}")

        except Exception as e:
            print(f"  [错误] '{company} - {position}' 爬取失败: {e}")

    return result


async def main() -> None:
    """
    独立运行入口：读取 CSV 并执行深度爬取。
    """
    print("[信息] 正在读取职位列表...")
    all_jobs = read_details_csv(DETAILS_CSV)
    if not all_jobs:
        print("[错误] 职位列表为空，请先运行第二阶段脚本。")
        return
    await enrich_all_jobs(all_jobs, save_csv=True)


# ========================= 程序入口 =========================
if __name__ == "__main__":
    print("=" * 60)
    print("  重庆大学就业网 - 职位详情深度爬虫（第三阶段）")
    print("=" * 60)
    asyncio.run(main())
    print("=" * 60)
    print("  全部爬取完成！")
    print("=" * 60)
