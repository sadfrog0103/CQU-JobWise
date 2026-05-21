"""
重庆大学就业网招聘会信息爬虫（Playwright 异步版）
目标网址：https://cqu.cqbys.com/jobfair
功能：抓取尚未举办的招聘会信息，并保存为 CSV 文件。
依赖：pip install playwright && playwright install msedge
"""

import csv
import re
import asyncio
from datetime import datetime
from urllib.parse import urljoin

from playwright.async_api import async_playwright


# ========================= 配置区 =========================

# 目标网址
BASE_URL = "https://cqu.cqbys.com"
TARGET_URL = f"{BASE_URL}/jobfair"

# 输出文件名
OUTPUT_CSV = "cqu_jobfair.csv"

# CSV 表头
CSV_HEADERS = ["方式", "名称", "地点", "举办时间", "链接"]

# 元素等待超时时间（毫秒），Playwright 默认单位为毫秒
ELEMENT_TIMEOUT = 15_000

# 时间格式（根据网页实际的时间格式进行调整）
# 格式示例：2026-05-19 14:00
TIME_FORMAT = "%Y-%m-%d %H:%M"

# ========================= 配置区结束 =========================


def parse_time(time_str: str) -> datetime | None:
    """
    从多种格式的时间字符串中提取起始时间，返回 datetime 对象。
    支持的格式示例：
      - "2026-05-19 14:00-17:00 （周二）"        → 取 2026-05-19 14:00
      - "2026-05-19 — 2026-05-31"                → 取 2026-05-19 00:00
      - "2026-05-19 14:00"                        → 取 2026-05-19 14:00
      - "举办时间"（表头）                          → 返回 None

    参数:
        time_str (str): 原始时间字符串

    返回:
        datetime | None: 解析成功返回 datetime 对象；失败返回 None
    """
    time_str = time_str.strip()

    # 策略 1：匹配 "YYYY-MM-DD HH:MM" 格式（精确到分钟的起始时间）
    # 例如 "2026-05-19 14:00-17:00 （周二）" → 提取 "2026-05-19 14:00"
    match = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", time_str)
    if match:
        try:
            return datetime.strptime(match.group(1), TIME_FORMAT)
        except ValueError:
            pass

    # 策略 2：匹配 "YYYY-MM-DD" 格式（仅有日期，无具体时间）
    # 例如 "2026-05-19 — 2026-05-31" → 提取 "2026-05-19"，默认 00:00
    match = re.search(r"(\d{4}-\d{2}-\d{2})", time_str)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%d")
        except ValueError:
            pass

    print(f"  [警告] 无法解析时间字符串: '{time_str}'")
    return None


async def scrape_jobfairs(save_csv: bool = True) -> list[dict[str, str]]:
    """
    主爬虫协程：
    1. 启动 Edge 浏览器（Playwright async_playwright）
    2. 访问招聘会页面
    3. 利用 Playwright locator 自动等待机制，确保元素加载完成
    4. 逐行提取招聘会信息
    5. 过滤掉已过期的招聘会
    6. 可选保存为 CSV 文件（standalone 模式）
    
    参数:
        save_csv: 是否同时保存 CSV 文件（独立运行时为 True，被 app.py 调用时为 False）
    
    返回:
        list[dict[str, str]]: 招聘会信息列表
    """
    results: list[dict[str, str]] = []

    async with async_playwright() as pw:
        # ---- 第一步：启动 Edge 浏览器 ----
        # channel="msedge" 会调用系统上已安装的 Edge 浏览器
        # headless=True 为无头模式（不弹出浏览器窗口），调试时可改为 False
        print("[信息] 正在启动 Edge 浏览器（Playwright headless 模式）...")
        browser = await pw.chromium.launch(
            channel="msedge",
            headless=True,
        )

        # 创建浏览器上下文，模拟真实 User-Agent
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0"
            ),
            viewport={"width": 1920, "height": 1080},
        )

        page = await context.new_page()

        try:
            # ---- 第二步：访问目标页面 ----
            print(f"[信息] 正在访问: {TARGET_URL}")
            await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30_000)

            # ---- 第三步：等待页面核心元素加载 ----
            # Playwright 的 locator 内置 auto-wait，会在操作前自动等待元素可见/可用
            # 这里先用 wait_for 确保至少一个 li.span8 出现，说明列表已渲染
            print("[信息] 正在等待页面元素加载...")
            await page.locator("li.span8").first.wait_for(
                state="attached", timeout=ELEMENT_TIMEOUT
            )

            # ---- 第四步：定位所有招聘会行 ----
            # 策略：获取所有 li.span8 元素，再通过 xpath("..") 回到父级容器
            # 父级容器中应包含 a 标签、span.status-text、li.span4、li.span8
            span8_locators = page.locator("li.span8")
            count = await span8_locators.count()
            print(f"[信息] 共找到 {count} 条招聘会条目")

            if count == 0:
                print("[警告] 未找到任何招聘会条目，请检查页面结构或网络连接。")
                # 输出页面源码片段便于调试
                content = await page.content()
                print("[调试] 页面源码片段：")
                print(content[:2000])
                return results

            # ---- 第五步：逐条提取信息 ----
            now = datetime.now()
            print(f"[信息] 当前系统时间: {now.strftime(TIME_FORMAT)}")

            for idx in range(count):
                # 跳过表头行：如果 li.span8 的文本与表头文字一致则跳过
                raw_text = (await span8_locators.nth(idx).inner_text()).strip()
                if raw_text == "举办时间":
                    print(f"  [跳过] 第 {idx + 1} 条: 表头行")
                    continue
                try:
                    # 获取当前 li.span8 的定位器
                    span8 = span8_locators.nth(idx)

                    # 回到父级容器（每条招聘会的根元素）
                    row = span8.locator("xpath=..")

                    # 5.1 提取"方式/状态"：span.status-text 的文字
                    status_locator = row.locator("span.status-text")
                    if await status_locator.count() > 0:
                        status_text = (await status_locator.first.inner_text()).strip()
                    else:
                        # 备用选择器
                        alt_status = row.locator("span.label, span.badge, span.tag")
                        if await alt_status.count() > 0:
                            status_text = (await alt_status.first.inner_text()).strip()
                        else:
                            status_text = "未知"

                    # 5.2 提取"招聘会名称"：a 标签的文本
                    # 注意：a 标签的文本可能带有方式前缀（如"组团 XXX"），需去除以避免与"方式"列重复
                    a_locator = row.locator("a")
                    if await a_locator.count() > 0:
                        name = (await a_locator.first.inner_text()).strip()
                        # 去除名称中的方式前缀（如 "组团 "、"网络 "）
                        for prefix in ["组团 ", "网络 ", "线上 ", "线下 "]:
                            if name.startswith(prefix):
                                name = name[len(prefix):]
                                break
                    else:
                        name = "未知"

                    # 5.3 提取"详情页链接"：a 标签的 href 属性
                    # 如果是相对路径（如 /jobfair/123），拼接完整域名
                    link = ""
                    if await a_locator.count() > 0:
                        href = await a_locator.first.get_attribute("href")
                        if href:
                            link = urljoin(BASE_URL, href)

                    # 5.4 提取"举办地点"：li.span4 的文本
                    span4_locator = row.locator("li.span4")
                    if await span4_locator.count() > 0:
                        location = (await span4_locator.first.inner_text()).strip()
                    else:
                        # 备用选择器
                        alt_loc = row.locator(".location, .venue, .span4")
                        if await alt_loc.count() > 0:
                            location = (await alt_loc.first.inner_text()).strip()
                        else:
                            location = "未知"

                    # 5.5 提取"举办时间"：li.span8 的文本
                    time_text = (await span8.inner_text()).strip()

                    # ---- 第六步：时间过滤 ----
                    fair_time = parse_time(time_text)

                    if fair_time is None:
                        print(f"  [跳过] 第 {idx + 1} 条: 时间解析失败 - '{time_text}'")
                        continue

                    if fair_time <= now:
                        print(f"  [跳过] 第 {idx + 1} 条: '{name}' 已过期 ({time_text})")
                        continue

                    # 保留该条信息
                    results.append({
                        "方式": status_text,
                        "名称": name,
                        "地点": location,
                        "举办时间": time_text,
                        "链接": link,
                    })
                    print(f"  [保留] 第 {idx + 1} 条: '{name}' - {time_text}")

                except Exception as e:
                    print(f"  [错误] 第 {idx + 1} 条提取失败: {e}")
                    continue

            # ---- 第七步：分页扩展（可选） ----
            # 当前版本仅抓取第一页数据
            # 如需翻页，可在此处添加：
            # while True:
            #     next_btn = page.locator("a.next-page")
            #     if await next_btn.count() == 0:
            #         break
            #     await next_btn.click()
            #     await page.wait_for_timeout(2000)
            #     # 重复提取逻辑...

            print(f"\n[信息] 过滤后共 {len(results)} 条即将举办的招聘会")

            # ---- 第八步：可选保存为 CSV 文件 ----
            if save_csv and results:
                with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
                    writer.writeheader()
                    writer.writerows(results)
                print(f"[信息] 结果已保存至: {OUTPUT_CSV}")
            elif save_csv:
                print("[信息] 没有即将举办的招聘会，未生成文件。")

            return results

        except Exception as e:
            print(f"[错误] 爬虫运行异常: {e}")
            return []

        finally:
            # ---- 关闭浏览器 ----
            await context.close()
            await browser.close()
            print("[信息] 浏览器已关闭。")


def fetch_fair_list() -> list[dict]:
    """
    同步封装：调用 scrape_jobfairs() 抓取招聘会列表并返回结果（不写文件）。
    返回字典列表，每条包含：方式、名称、地点、举办时间、链接。
    """
    return asyncio.run(scrape_jobfairs(save_csv=False))


# ========================= 程序入口 =========================
if __name__ == "__main__":
    print("=" * 60)
    print("  重庆大学就业网 - 招聘会信息爬虫（Playwright 版）")
    print("=" * 60)
    asyncio.run(scrape_jobfairs())
    print("=" * 60)
    print("  爬取完成！")
    print("=" * 60)
