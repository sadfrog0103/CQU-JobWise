"""
重庆大学就业网 - 招聘会岗位详情深度爬虫（第二阶段）
读取第一阶段生成的 cqu_jobfair.csv，逐个访问招聘会详情页，
提取参会企业的岗位信息（单位全称、职位名称、需求人数、需求专业）。
依赖：pip install playwright && playwright install msedge
"""

import csv
import re
import asyncio
import random
from datetime import datetime
from urllib.parse import urljoin

from playwright.async_api import async_playwright, Page, BrowserContext


# ========================= 配置区 =========================

BASE_URL = "https://cqu.cqbys.com"

# 第一阶段输出文件（输入）
FAIR_CSV = "cqu_jobfair.csv"

# 第二阶段输出文件
DETAILS_CSV = "jobs_with_details.csv"       # 有结构化岗位表格的招聘会
SIMPLE_CSV = "simple_announcements.csv"     # 无结构化表格的招聘会

# 详情页 CSV 表头
DETAILS_HEADERS = ["招聘会名称", "举办地点", "举办时间", "单位全称", "职位名称", "需求人数", "需求专业", "职位原链接"]

# 简单公告 CSV 表头
SIMPLE_HEADERS = ["招聘会名称", "举办地点", "举办时间", "链接", "备注"]

# 并发控制：同时打开的页面数（防止被防火墙拦截）
MAX_CONCURRENCY = 4

# 元素等待超时时间（毫秒）
PAGE_TIMEOUT = 30_000
TABLE_WAIT_TIMEOUT = 10_000

# 随机 User-Agent 列表
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (Windows 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]

# ========================= 配置区结束 =========================


def get_random_ua() -> str:
    """返回一个随机 User-Agent 字符串。"""
    return random.choice(USER_AGENTS)


def read_fair_csv(filepath: str) -> list[dict]:
    """
    读取第一阶段生成的招聘会 CSV 文件。
    返回字典列表，每条包含：名称、地点、举办时间、链接
    """
    rows = []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 字段映射：CSV 列名 → 内部键名
            rows.append({
                "名称": row.get("名称", "").strip(),
                "地点": row.get("地点", "").strip(),
                "举办时间": row.get("举办时间", "").strip(),
                "链接": row.get("链接", "").strip(),
            })
    return rows


def clean_text(text: str) -> str:
    """清理文本：去除多余空白、换行符等。"""
    if not text:
        return ""
    # 将换行符替换为空格，去除首尾空白
    text = re.sub(r"\s+", " ", text)
    return text.strip()


async def extract_table_jobs(page: Page, fair_info: dict) -> tuple[list[dict], bool]:
    """
    从招聘会详情页中提取岗位表格数据。

    返回:
        (jobs, has_table):
            - jobs: 岗位信息列表（可能为空列表）
            - has_table: 是否存在结构化的岗位表格
    """
    jobs = []

    # ---- 尝试定位岗位表格 ----
    # 策略 1：查找包含 "单位全称" 和 "职位名称" 文本的 table
    tables = page.locator("table")
    table_count = await tables.count()

    target_table = None
    for i in range(table_count):
        table = tables.nth(i)
        table_text = clean_text(await table.inner_text())
        # 检查表格是否包含岗位信息的关键字段
        if "单位全称" in table_text and "职位名称" in table_text:
            target_table = table
            break

    if target_table is None:
        # 策略 2：在 div 容器中查找包含岗位信息的表格结构
        # 有些网站用 div 模拟 table（如 Bootstrap 的 table-responsive）
        containers = page.locator("div.table-responsive, div.table-container, div.fair-detail, div.job-list")
        container_count = await containers.count()
        for i in range(container_count):
            container = containers.nth(i)
            container_text = clean_text(await container.inner_text())
            if "单位全称" in container_text and "职位名称" in container_text:
                # 在容器内查找 table 或行级元素
                inner_table = container.locator("table")
                if await inner_table.count() > 0:
                    target_table = inner_table.first
                    break

    if target_table is None:
        # 没有找到结构化表格
        return [], False

    # ---- 获取所有行（包含 thead 和 tbody） ----
    all_rows = target_table.locator("tr")
    all_row_count = await all_rows.count()

    if all_row_count == 0:
        return [], True

    # ---- 解析表头，确定列数和各列的索引位置 ----
    # 典型表头：序号 | 单位全称 | 职位名称 | 需求人数 | 需求专业 | 投递简历
    header_row = all_rows.first
    header_cells = header_row.locator("th")
    header_count = await header_cells.count()

    # 如果没有 th，尝试用第一行的 td 作为表头
    if header_count == 0:
        header_cells = header_row.locator("td")
        header_count = await header_cells.count()

    # 读取表头文本，建立列名→索引映射
    header_texts = []
    for i in range(header_count):
        header_texts.append(clean_text(await header_cells.nth(i).inner_text()))

    print(f"    [调试] 表头列({header_count}): {header_texts}")

    # 定位关键列的索引（根据表头文本匹配）
    col_company = -1   # 单位全称
    col_position = -1  # 职位名称
    col_headcount = -1 # 需求人数
    col_major = -1     # 需求专业
    col_apply = -1     # 投递简历（可用于区分操作列）

    for i, h in enumerate(header_texts):
        if "单位" in h:
            col_company = i
        elif "职位" in h:
            col_position = i
        elif "人数" in h or "需求人数" in h:
            col_headcount = i
        elif "专业" in h or "需求专业" in h:
            col_major = i
        elif "投递" in h or "操作" in h:
            col_apply = i

    # 如果没匹配到表头，使用默认列映射（兼容无表头情况）
    if col_company < 0:
        col_company = 1
    if col_position < 0:
        col_position = 2
    if col_headcount < 0:
        col_headcount = 3
    if col_major < 0:
        col_major = 4

    print(f"    [调试] 列映射: 单位={col_company}, 职位={col_position}, 人数={col_headcount}, 专业={col_major}")

    # ---- 用于跟踪合并单元格的上一个单位名称 ----
    last_company = ""
    # 数据行从第 1 行开始（跳过表头）
    data_start = 1 if header_count > 0 else 0

    for idx in range(data_start, all_row_count):
        try:
            row = all_rows.nth(idx)
            cells = row.locator("td")
            cell_count = await cells.count()

            if cell_count < 2:
                continue  # 数据不完整的行，跳过

            # ---- 判断是否为"父行"（包含所有列）或"子行"（合并了前N列） ----
            # 父行：cell_count >= header_count（所有列都有，包含序号+单位）
            # 子行：cell_count < header_count（序号+单位被 rowspan 合并，从职位列开始）
            is_parent_row = (cell_count >= header_count)

            company = ""
            position = ""
            headcount = ""
            major = ""
            position_link = ""

            if is_parent_row:
                # ---- 父行：按表头列索引直接提取 ----
                # 单位全称
                if col_company < cell_count:
                    cell_company = cells.nth(col_company)
                    a_in_company = cell_company.locator("a")
                    if await a_in_company.count() > 0:
                        company = clean_text(await a_in_company.first.inner_text())
                        href = await a_in_company.first.get_attribute("href")
                        if href:
                            position_link = urljoin(BASE_URL, href)
                    else:
                        company = clean_text(await cell_company.inner_text())

                last_company = company  # 更新上一个单位名称

                # 职位名称
                if col_position < cell_count:
                    cell_pos = cells.nth(col_position)
                    a_in_pos = cell_pos.locator("a")
                    if await a_in_pos.count() > 0:
                        position = clean_text(await a_in_pos.first.inner_text())
                        if not position_link:
                            href = await a_in_pos.first.get_attribute("href")
                            if href:
                                position_link = urljoin(BASE_URL, href)
                    else:
                        position = clean_text(await cell_pos.inner_text())

                # 需求人数
                if col_headcount < cell_count:
                    headcount = clean_text(await cells.nth(col_headcount).inner_text())

                # 需求专业
                if col_major < cell_count:
                    major = clean_text(await cells.nth(col_major).inner_text())

            else:
                # ---- 子行（合并单元格）：前 N 列被 rowspan 合并 ----
                # 计算偏移量：缺少的列数 = header_count - cell_count
                offset = header_count - cell_count

                # 沿用上一个单位名称
                company = last_company

                # 子行中的列对应原始表头的 offset 列之后
                # 职位名称 → 原 col_position 列，在子行中索引 = col_position - offset
                pos_in_child = col_position - offset
                if 0 <= pos_in_child < cell_count:
                    cell_pos = cells.nth(pos_in_child)
                    a_in_pos = cell_pos.locator("a")
                    if await a_in_pos.count() > 0:
                        position = clean_text(await a_in_pos.first.inner_text())
                        href = await a_in_pos.first.get_attribute("href")
                        if href:
                            position_link = urljoin(BASE_URL, href)
                    else:
                        position = clean_text(await cell_pos.inner_text())

                # 需求人数
                hc_in_child = col_headcount - offset
                if 0 <= hc_in_child < cell_count:
                    headcount = clean_text(await cells.nth(hc_in_child).inner_text())

                # 需求专业
                mj_in_child = col_major - offset
                if 0 <= mj_in_child < cell_count:
                    major = clean_text(await cells.nth(mj_in_child).inner_text())

            # 如果没有获取到链接，用招聘会详情页链接作为备用
            if not position_link:
                position_link = fair_info.get("链接", "")

            # 清理：需求人数应为数字，去除多余文字
            if headcount and not headcount.replace(" ", "").isdigit():
                # 尝试提取数字部分
                num_match = re.search(r"\d+", headcount)
                if num_match:
                    headcount = num_match.group()

            # 至少要有单位名称或职位名称才记录
            if company or position:
                jobs.append({
                    "招聘会名称": fair_info.get("名称", ""),
                    "举办地点": fair_info.get("地点", ""),
                    "举办时间": fair_info.get("举办时间", ""),
                    "单位全称": company,
                    "职位名称": position,
                    "需求人数": headcount,
                    "需求专业": major,
                    "职位原链接": position_link,
                })

        except Exception as e:
            print(f"    [错误] 解析表格第 {idx} 行失败: {e}")
            continue

    return jobs, True


async def scrape_detail_page(
    page: Page, fair_info: dict, semaphore: asyncio.Semaphore
) -> tuple[list[dict], bool]:
    """
    爬取单个招聘会详情页。

    参数:
        page: Playwright Page 实例
        fair_info: 招聘会基本信息（名称、地点、时间、链接）
        semaphore: 并发信号量

    返回:
        (jobs, has_table): 岗位列表 和 是否有结构化表格
    """
    url = fair_info.get("链接", "")
    fair_name = fair_info.get("名称", "未知")

    if not url:
        print(f"  [跳过] '{fair_name}' 无链接")
        return [], False

    async with semaphore:
        print(f"  [开始] 正在爬取: {fair_name}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)

            # 等待页面主体内容加载
            # 先等 table 出现，如果超时则认为没有表格
            try:
                await page.locator("table").first.wait_for(
                    state="attached", timeout=TABLE_WAIT_TIMEOUT
                )
            except Exception:
                # 超时：可能没有 table，继续尝试提取
                pass

            jobs, has_table = await extract_table_jobs(page, fair_info)

            if has_table and jobs:
                print(f"  [完成] '{fair_name}' → 提取到 {len(jobs)} 条岗位信息")
            elif has_table:
                print(f"  [完成] '{fair_name}' → 存在表格但无有效岗位数据")
            else:
                print(f"  [完成] '{fair_name}' → 无结构化岗位表格")

            return jobs, has_table

        except Exception as e:
            print(f"  [错误] '{fair_name}' 爬取失败: {e}")
            return [], False


async def scrape_all_details(fair_list: list[dict], save_csv: bool = True) -> list[dict]:
    """
    第二阶段主流程（可被 app.py 调用）：
    1. 接收第一阶段的招聘会列表
    2. 并发访问各招聘会详情页
    3. 提取岗位信息
    4. 可选保存结果到 CSV（standalone 模式）

    参数:
        fair_list: 招聘会列表，每条包含：名称、地点、举办时间、链接
        save_csv: 是否同时保存 CSV 文件
    
    返回:
        list[dict]: 有结构化表格的岗位列表
    """
    print(f"[信息] 共 {len(fair_list)} 个招聘会待爬取")

    if not fair_list:
        print("[错误] 招聘会列表为空。")
        return []

    # 将 fair_list 的字段名映射为内部键名（兼容 app.py 中的字典格式）
    normalized = []
    for f in fair_list:
        normalized.append({
            "名称": f.get("名称", f.get("name", "")).strip(),
            "地点": f.get("地点", f.get("venue", "")).strip(),
            "举办时间": f.get("举办时间", f.get("time", "")).strip(),
            "链接": f.get("链接", f.get("link", "")).strip(),
        })
    fair_list = normalized

    # 结果容器
    all_jobs: list[dict] = []        # 有结构化表格的岗位
    simple_fairs: list[dict] = []    # 无结构化表格的招聘会

    async with async_playwright() as pw:
        print("[信息] 正在启动 Edge 浏览器...")
        browser = await pw.chromium.launch(channel="msedge", headless=True)

        # 并发信号量：限制同时打开的页面数
        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

        # 为每个招聘会创建独立的页面上下文（各自独立的 User-Agent）
        tasks = []
        for fair_info in fair_list:
            # 每个任务使用独立的 context（模拟不同用户）
            context = await browser.new_context(
                user_agent=get_random_ua(),
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()
            tasks.append((page, context, fair_info))

        # ---- 第二步：并发爬取详情页 ----
        print(f"[信息] 开始并发爬取（并发数: {MAX_CONCURRENCY}）...")

        async def process_fair(page, context, fair_info):
            """处理单个招聘会的协程包装。"""
            try:
                jobs, has_table = await scrape_detail_page(page, fair_info, semaphore)
                return fair_info, jobs, has_table
            finally:
                await context.close()

        # 创建所有异步任务
        coroutines = [
            process_fair(page, ctx, info) for page, ctx, info in tasks
        ]
        results = await asyncio.gather(*coroutines, return_exceptions=True)

        # ---- 第三步：分类汇总结果 ----
        for result in results:
            if isinstance(result, Exception):
                print(f"  [错误] 任务异常: {result}")
                continue

            fair_info, jobs, has_table = result

            if has_table and jobs:
                all_jobs.extend(jobs)
            elif has_table:
                # 有表格但无数据，仍算作简单公告
                simple_fairs.append({
                    "招聘会名称": fair_info.get("名称", ""),
                    "举办地点": fair_info.get("地点", ""),
                    "举办时间": fair_info.get("举办时间", ""),
                    "链接": fair_info.get("链接", ""),
                    "备注": "存在岗位表格但无有效数据",
                })
            else:
                simple_fairs.append({
                    "招聘会名称": fair_info.get("名称", ""),
                    "举办地点": fair_info.get("地点", ""),
                    "举办时间": fair_info.get("举办时间", ""),
                    "链接": fair_info.get("链接", ""),
                    "备注": "无结构化岗位表格",
                })

    # ---- 第四步：关闭浏览器 ----
        await browser.close()
        print("[信息] 浏览器已关闭。")

    # ---- 第五步：可选保存结果 ----
    print(f"\n[信息] 汇总：共提取 {len(all_jobs)} 条岗位，{len(simple_fairs)} 个无表格招聘会")

    if save_csv:
        # 保存岗位详情
        if all_jobs:
            with open(DETAILS_CSV, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=DETAILS_HEADERS)
                writer.writeheader()
                writer.writerows(all_jobs)
            print(f"[信息] 岗位详情已保存至: {DETAILS_CSV}")
        else:
            print("[信息] 无结构化岗位数据，未生成 details 文件。")

        # 保存简单公告
        if simple_fairs:
            with open(SIMPLE_CSV, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=SIMPLE_HEADERS)
                writer.writeheader()
                writer.writerows(simple_fairs)
            print(f"[信息] 简单公告已保存至: {SIMPLE_CSV}")
        else:
            print("[信息] 所有招聘会均有结构化数据，未生成 simple 文件。")

    return all_jobs


async def main() -> None:
    """
    独立运行入口：读取 CSV 并执行爬取。
    """
    print("[信息] 正在读取招聘会列表...")
    fair_list = read_fair_csv(FAIR_CSV)
    if not fair_list:
        print("[错误] 招聘会列表为空，请先运行第一阶段脚本。")
        return
    await scrape_all_details(fair_list, save_csv=True)


# ========================= 程序入口 =========================
if __name__ == "__main__":
    print("=" * 60)
    print("  重庆大学就业网 - 招聘会岗位详情深度爬虫（第二阶段）")
    print("=" * 60)
    asyncio.run(main())
    print("=" * 60)
    print("  深度爬取完成！")
    print("=" * 60)