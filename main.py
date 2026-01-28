#!/usr/bin/env python3
"""
加密政策 RSS -> 企业微信推送工具
支持多源聚合、关键词过滤、中文翻译、自动去重
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from functools import wraps
from typing import Any, Callable, Optional
from pathlib import Path

import feedparser
import requests
from dateutil import parser as date_parser
import translators as ts

# ============== 配置 ==============

BASE_DIR = Path(__file__).parent
FEEDS_FILE = BASE_DIR / "feeds.json"
CONFIG_FILE = BASE_DIR / "config.json"
STATE_FILE = BASE_DIR / "state.json"

# 环境变量
WECOM_WEBHOOK_URL = os.getenv("WECOM_WEBHOOK_URL", "")  # 企业微信 Webhook
DRY_RUN = os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ============== 日志配置 ==============

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ============== 数据类 ==============

@dataclass
class FeedSource:
    """RSS 源配置"""
    name: str
    full_name: str
    url: str
    tags: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class FeedEntry:
    """RSS 条目"""
    id: str
    title: str
    title_zh: str
    link: str
    summary: str
    summary_zh: str
    published: datetime
    source: str
    source_full: str
    tags: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    """应用配置"""
    keywords_allow: list[str] = field(default_factory=list)
    keywords_deny: list[str] = field(default_factory=list)
    http_timeout: int = 30
    max_entries_per_feed: int = 50
    state_retention_days: int = 30
    max_retries: int = 3
    retry_backoff_base: int = 2
    message_batch_size: int = 5
    message_delay: float = 1.0
    summary_max_length: int = 200
    tags_filter_enabled: bool = False
    tags_include: list[str] = field(default_factory=list)
    tags_exclude: list[str] = field(default_factory=list)


# ============== 简易中英翻译 ==============

# 常见金融/加密术语中英对照
TRANSLATION_DICT = {
    # 机构名
    "Bank for International Settlements": "国际清算银行",
    "International Monetary Fund": "国际货币基金组织",
    "Federal Reserve": "美联储",
    "European Central Bank": "欧洲央行",
    "Securities and Exchange Commission": "美国证券交易委员会",
    "Financial Conduct Authority": "英国金融行为监管局",
    "Monetary Authority of Singapore": "新加坡金融管理局",
    "Hong Kong Monetary Authority": "香港金融管理局",
    "Bank of England": "英格兰银行",
    "Financial Stability Board": "金融稳定委员会",
    "People's Bank of China": "中国人民银行",
    # 术语
    "cryptocurrency": "加密货币",
    "crypto": "加密",
    "bitcoin": "比特币",
    "ethereum": "以太坊",
    "stablecoin": "稳定币",
    "central bank digital currency": "央行数字货币",
    "CBDC": "央行数字货币",
    "digital currency": "数字货币",
    "digital asset": "数字资产",
    "blockchain": "区块链",
    "decentralized finance": "去中心化金融",
    "DeFi": "去中心化金融",
    "token": "代币",
    "virtual asset": "虚拟资产",
    "virtual currency": "虚拟货币",
    "NFT": "非同质化代币",
    "mining": "挖矿",
    "exchange": "交易所",
    "wallet": "钱包",
    "custody": "托管",
    "anti-money laundering": "反洗钱",
    "AML": "反洗钱",
    "know your customer": "了解你的客户",
    "KYC": "了解你的客户",
    "fintech": "金融科技",
    "payment": "支付",
    "settlement": "结算",
    "clearing": "清算",
    "regulation": "监管",
    "compliance": "合规",
    "enforcement": "执法",
    "sanctions": "制裁",
    "risk": "风险",
    "financial stability": "金融稳定",
    "monetary policy": "货币政策",
    "interest rate": "利率",
    "inflation": "通胀",
    "liquidity": "流动性",
    "capital": "资本",
    "asset": "资产",
    "securities": "证券",
    "derivatives": "衍生品",
    "futures": "期货",
    "options": "期权",
    "trading": "交易",
    "market": "市场",
    "investor": "投资者",
    "consumer protection": "消费者保护",
    "disclosure": "披露",
    "transparency": "透明度",
    "framework": "框架",
    "guidance": "指引",
    "consultation": "咨询",
    "proposal": "提案",
    "rule": "规则",
    "press release": "新闻稿",
    "statement": "声明",
    "speech": "讲话",
    "report": "报告",
    "research": "研究",
    "analysis": "分析",
    "review": "审查",
    "assessment": "评估",
}


def translate_text(text: str) -> str:
    """
    简易翻译：基于词典替换常见术语
    对于完整翻译，建议接入翻译 API（如 Google Translate、DeepL）
    """
    if not text:
        return ""

    result = text
    # 按长度降序排列，优先匹配长词组
    sorted_terms = sorted(TRANSLATION_DICT.keys(), key=len, reverse=True)

    for en_term in sorted_terms:
        zh_term = TRANSLATION_DICT[en_term]
        # 不区分大小写替换
        pattern = re.compile(re.escape(en_term), re.IGNORECASE)
        result = pattern.sub(f"{zh_term}({en_term})", result)

    return result


def translate_to_chinese(text: str) -> str:
    """
    将英文文本翻译成中文
    使用 translators 库（支持多个翻译引擎自动切换）
    """
    if not text or not text.strip():
        return ""

    # 检查是否已经是中文为主的内容
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    if chinese_chars > len(text) * 0.3:  # 超过30%是中文，不翻译
        return text

    # 截断过长文本
    if len(text) > 500:
        text = text[:500]

    # 尝试多个翻译引擎
    engines = ['bing', 'google', 'alibaba', 'baidu']

    for engine in engines:
        try:
            translated = ts.translate_text(
                text,
                translator=engine,
                from_language='en',
                to_language='zh'
            )
            if translated and translated != text:
                return translated
        except Exception as e:
            logger.debug(f"{engine} 翻译失败: {e}")
            continue

    # 所有引擎都失败，使用词典翻译
    logger.warning(f"所有翻译引擎失败，使用词典翻译")
    return translate_text(text)


def translate_with_api(text: str, target_lang: str = "zh") -> str:
    """
    翻译文本到中文（兼容旧接口）
    """
    return translate_to_chinese(text)


# ============== 重试装饰器 ==============

def retry_with_backoff(
    max_attempts: int = 3,
    backoff_base: int = 2,
    exceptions: tuple = (requests.RequestException,),
) -> Callable:
    """指数退避重试装饰器"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts:
                        wait_time = backoff_base ** attempt
                        logger.warning(
                            f"{func.__name__} 失败 (尝试 {attempt}/{max_attempts}): {e}"
                            f"，{wait_time}秒后重试..."
                        )
                        time.sleep(wait_time)
                    else:
                        logger.error(
                            f"{func.__name__} 最终失败 (尝试 {attempt}/{max_attempts}): {e}"
                        )
            raise last_exception
        return wrapper
    return decorator


# ============== 配置加载 ==============

def load_feeds() -> list[FeedSource]:
    """加载 RSS 源配置"""
    if not FEEDS_FILE.exists():
        logger.error(f"RSS 源配置文件不存在: {FEEDS_FILE}")
        return []

    with open(FEEDS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    feeds = []
    for item in data.get("feeds", []):
        if item.get("enabled", True):
            feeds.append(FeedSource(
                name=item["name"],
                full_name=item.get("full_name", item["name"]),
                url=item["url"],
                tags=item.get("tags", []),
                enabled=item.get("enabled", True),
            ))

    logger.info(f"已加载 {len(feeds)} 个 RSS 源")
    return feeds


def load_config() -> AppConfig:
    """加载应用配置，支持环境变量覆盖"""
    config = AppConfig()

    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        keywords = data.get("keywords", {})
        config.keywords_allow = keywords.get("allow", [])
        config.keywords_deny = keywords.get("deny", [])

        settings = data.get("settings", {})
        config.http_timeout = settings.get("http_timeout_seconds", 30)
        config.max_entries_per_feed = settings.get("max_entries_per_feed", 50)
        config.state_retention_days = settings.get("state_retention_days", 30)
        config.max_retries = settings.get("max_retries", 3)
        config.retry_backoff_base = settings.get("retry_backoff_base", 2)
        config.message_batch_size = settings.get("message_batch_size", 5)
        config.message_delay = settings.get("message_delay_seconds", 1.0)
        config.summary_max_length = settings.get("summary_max_length", 200)

        tags_filter = data.get("tags_filter", {})
        config.tags_filter_enabled = tags_filter.get("enabled", False)
        config.tags_include = tags_filter.get("include_tags", [])
        config.tags_exclude = tags_filter.get("exclude_tags", [])

    # 环境变量覆盖
    if os.getenv("HTTP_TIMEOUT"):
        config.http_timeout = int(os.getenv("HTTP_TIMEOUT"))
    if os.getenv("MAX_ENTRIES_PER_FEED"):
        config.max_entries_per_feed = int(os.getenv("MAX_ENTRIES_PER_FEED"))
    if os.getenv("STATE_RETENTION_DAYS"):
        config.state_retention_days = int(os.getenv("STATE_RETENTION_DAYS"))

    logger.info(f"配置已加载: 允许关键词 {len(config.keywords_allow)} 个，"
                f"拒绝关键词 {len(config.keywords_deny)} 个")
    return config


# ============== 状态管理 ==============

def load_state() -> dict[str, Any]:
    """加载状态文件"""
    if not STATE_FILE.exists():
        return {"sent_ids": {}, "last_run": None}

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict[str, Any]) -> None:
    """保存状态文件"""
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    logger.info("状态已保存")


def cleanup_state(state: dict[str, Any], retention_days: int) -> dict[str, Any]:
    """清理过期的状态记录"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_str = cutoff.isoformat()

    sent_ids = state.get("sent_ids", {})
    original_count = len(sent_ids)

    # 保留未过期的记录
    cleaned = {
        entry_id: timestamp
        for entry_id, timestamp in sent_ids.items()
        if timestamp > cutoff_str
    }

    removed_count = original_count - len(cleaned)
    if removed_count > 0:
        logger.info(f"已清理 {removed_count} 条过期状态记录")

    state["sent_ids"] = cleaned
    return state


def generate_entry_id(entry: dict, source_name: str) -> str:
    """生成条目唯一 ID"""
    # 优先使用 entry 自带的 id
    if entry.get("id"):
        return f"{source_name}:{entry['id']}"

    # 否则使用 link 的 hash
    if entry.get("link"):
        link_hash = hashlib.md5(entry["link"].encode()).hexdigest()[:12]
        return f"{source_name}:{link_hash}"

    # 最后使用标题的 hash
    title_hash = hashlib.md5(entry.get("title", "").encode()).hexdigest()[:12]
    return f"{source_name}:{title_hash}"


# ============== RSS 抓取 ==============

@retry_with_backoff(max_attempts=3, backoff_base=2)
def fetch_feed(url: str, timeout: int = 30) -> feedparser.FeedParserDict:
    """抓取 RSS 源"""
    # 使用 requests 获取内容，以便更好地控制超时和重试
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; CryptoPolicyBot/1.0)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }

    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()

    return feedparser.parse(response.content)


def parse_entry_date(entry: dict) -> datetime:
    """解析条目发布时间，确保返回 timezone-aware datetime"""
    # 尝试多个日期字段
    for date_field in ["published", "updated", "created"]:
        if entry.get(date_field):
            try:
                dt = date_parser.parse(entry[date_field])
                # 确保时区感知
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (ValueError, TypeError):
                continue

    # 默认返回当前时间
    return datetime.now(timezone.utc)


def extract_summary(entry: dict, max_length: int = 200) -> str:
    """提取摘要"""
    summary = ""

    # 尝试多个摘要字段
    if entry.get("summary"):
        summary = entry["summary"]
    elif entry.get("description"):
        summary = entry["description"]
    elif entry.get("content"):
        contents = entry["content"]
        if isinstance(contents, list) and contents:
            summary = contents[0].get("value", "")

    # 清理 HTML 标签
    summary = re.sub(r"<[^>]+>", "", summary)
    summary = re.sub(r"\s+", " ", summary).strip()

    # 截断
    if len(summary) > max_length:
        summary = summary[:max_length].rsplit(" ", 1)[0] + "..."

    return summary


def matches_keywords(text: str, keywords: list[str]) -> bool:
    """检查文本是否匹配关键词"""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def filter_entry(
    entry: dict,
    config: AppConfig,
    source_tags: list[str],
) -> bool:
    """过滤条目：返回 True 表示保留"""
    title = entry.get("title", "")
    summary = entry.get("summary", "") or entry.get("description", "")
    combined_text = f"{title} {summary}"

    # 检查拒绝关键词
    if config.keywords_deny and matches_keywords(combined_text, config.keywords_deny):
        return False

    # 检查允许关键词（如果有配置）
    if config.keywords_allow:
        if not matches_keywords(combined_text, config.keywords_allow):
            return False

    # 检查标签过滤
    if config.tags_filter_enabled:
        if config.tags_exclude:
            if any(tag in config.tags_exclude for tag in source_tags):
                return False
        if config.tags_include:
            if not any(tag in config.tags_include for tag in source_tags):
                return False

    return True


def process_feed(
    source: FeedSource,
    config: AppConfig,
    sent_ids: set[str],
) -> list[FeedEntry]:
    """处理单个 RSS 源"""
    logger.info(f"正在抓取: {source.name} ({source.url})")

    try:
        feed = fetch_feed(source.url, config.http_timeout)
    except Exception as e:
        logger.error(f"抓取 {source.name} 失败: {e}")
        return []

    entries = []
    for raw_entry in feed.entries[:config.max_entries_per_feed]:
        entry_id = generate_entry_id(raw_entry, source.name)

        # 跳过已发送
        if entry_id in sent_ids:
            continue

        # 过滤
        if not filter_entry(raw_entry, config, source.tags):
            continue

        # 提取信息
        title = raw_entry.get("title", "无标题")
        summary = extract_summary(raw_entry, config.summary_max_length)

        # 翻译（添加延迟避免速率限制）
        title_zh = translate_to_chinese(title)
        time.sleep(1.0)  # 避免翻译API速率限制
        summary_zh = translate_to_chinese(summary)
        time.sleep(1.0)

        entry = FeedEntry(
            id=entry_id,
            title=title,
            title_zh=title_zh,
            link=raw_entry.get("link", ""),
            summary=summary,
            summary_zh=summary_zh,
            published=parse_entry_date(raw_entry),
            source=source.name,
            source_full=source.full_name,
            tags=source.tags,
        )
        entries.append(entry)

    logger.info(f"{source.name}: 发现 {len(entries)} 条新条目")
    return entries


# ============== 企业微信发送 ==============

def format_wecom_markdown(entries: list[FeedEntry]) -> str:
    """格式化企业微信 Markdown 消息（中文版）"""
    # 北京时间
    beijing_tz = timezone(timedelta(hours=8))
    now_beijing = datetime.now(beijing_tz)

    lines = [
        "# 📚 加密政策/研报速览",
        f"> ⏰ {now_beijing.strftime('%Y-%m-%d %H:%M')} 北京时间",
        "",
    ]

    for i, entry in enumerate(entries, 1):
        # 来源标签（绿色高亮）
        source_tag = f"<font color=\"info\">[{entry.source}]</font>"

        # 标题（中文优先）
        lines.append(f"**{i}. {source_tag} {entry.title_zh}**")

        # 摘要（中文）
        if entry.summary_zh:
            summary_text = entry.summary_zh[:150]
            if len(entry.summary_zh) > 150:
                summary_text += "..."
            lines.append(f"> {summary_text}")

        # 链接
        lines.append(f"[👉 阅读原文]({entry.link})")
        lines.append("")

    # 标签
    all_tags = set()
    for entry in entries:
        all_tags.update(entry.tags)
    if all_tags:
        tag_str = " ".join(f"`#{tag}`" for tag in sorted(all_tags)[:5])
        lines.append(tag_str)

    return "\n".join(lines)


def format_wecom_text(entries: list[FeedEntry]) -> str:
    """格式化企业微信纯文本消息（备用）"""
    beijing_tz = timezone(timedelta(hours=8))
    now_beijing = datetime.now(beijing_tz)

    lines = [
        "📚 加密政策/研报速览",
        f"⏰ {now_beijing.strftime('%Y-%m-%d %H:%M')} 北京时间",
        "━" * 20,
        "",
    ]

    for i, entry in enumerate(entries, 1):
        lines.append(f"{i}. [{entry.source}] {entry.title_zh}")
        if entry.summary_zh:
            lines.append(f"   📝 {entry.summary_zh[:120]}...")
        lines.append(f"   🔗 {entry.link}")
        lines.append("")

    return "\n".join(lines)


@retry_with_backoff(max_attempts=3, backoff_base=2)
def send_wecom_message(content: str, webhook_url: str, msg_type: str = "markdown") -> bool:
    """
    发送企业微信消息

    Args:
        content: 消息内容
        webhook_url: 企业微信 Webhook URL
        msg_type: 消息类型 (markdown / text)
    """
    if msg_type == "markdown":
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }
    else:
        payload = {
            "msgtype": "text",
            "text": {
                "content": content
            }
        }

    response = requests.post(webhook_url, json=payload, timeout=30)
    response.raise_for_status()

    result = response.json()
    if result.get("errcode") != 0:
        raise Exception(f"企业微信 API 错误: {result}")

    logger.debug(f"企业微信响应: {result}")
    return True


def send_entries(
    entries: list[FeedEntry],
    batch_size: int = 5,
    delay: float = 1.0,
) -> list[str]:
    """批量发送条目到企业微信"""
    if not entries:
        logger.info("没有新条目需要发送")
        return []

    if DRY_RUN:
        logger.info(f"[DRY-RUN] 将发送 {len(entries)} 条消息")
        for entry in entries:
            logger.info(f"  - [{entry.source}] {entry.title_zh}")
        # 打印消息预览
        preview = format_wecom_markdown(entries[:3])
        logger.info(f"\n消息预览:\n{preview}")
        return [e.id for e in entries]

    if not WECOM_WEBHOOK_URL:
        logger.error("企业微信配置缺失: 请设置 WECOM_WEBHOOK_URL 环境变量")
        return []

    sent_ids = []

    # 分批发送（企业微信单条消息限制 4096 字节）
    for i in range(0, len(entries), batch_size):
        batch = entries[i:i + batch_size]
        message = format_wecom_markdown(batch)

        # 如果消息过长，尝试使用纯文本格式
        if len(message.encode('utf-8')) > 4000:
            logger.warning("消息过长，切换为纯文本格式")
            message = format_wecom_text(batch)

        try:
            send_wecom_message(message, WECOM_WEBHOOK_URL, "markdown")
            sent_ids.extend(e.id for e in batch)
            logger.info(f"已发送第 {i // batch_size + 1} 批 ({len(batch)} 条)")

            # 批次间延迟（企业微信限制每分钟 20 条）
            if i + batch_size < len(entries):
                time.sleep(delay)

        except Exception as e:
            logger.error(f"发送失败: {e}")
            # 继续尝试下一批

    return sent_ids


# ============== 主函数 ==============

def main() -> int:
    """主函数"""
    logger.info("=" * 50)
    logger.info("加密政策 RSS 聚合器启动")
    logger.info(f"DRY_RUN: {DRY_RUN}")
    logger.info("=" * 50)

    # 加载配置
    feeds = load_feeds()
    if not feeds:
        logger.error("没有可用的 RSS 源")
        return 1

    config = load_config()

    # 加载并清理状态
    state = load_state()
    state = cleanup_state(state, config.state_retention_days)
    sent_ids = set(state.get("sent_ids", {}).keys())

    # 处理所有 RSS 源
    all_entries: list[FeedEntry] = []

    for source in feeds:
        try:
            entries = process_feed(source, config, sent_ids)
            all_entries.extend(entries)
        except Exception as e:
            logger.error(f"处理 {source.name} 时出错: {e}")
            # 单个源失败不影响其他源
            continue

    # 按发布时间排序（最新的在前）
    all_entries.sort(key=lambda e: e.published, reverse=True)

    logger.info(f"共发现 {len(all_entries)} 条新条目")

    # 发送
    newly_sent = send_entries(
        all_entries,
        batch_size=config.message_batch_size,
        delay=config.message_delay,
    )

    # 更新状态
    now_iso = datetime.now(timezone.utc).isoformat()
    for entry_id in newly_sent:
        state["sent_ids"][entry_id] = now_iso

    save_state(state)

    logger.info(f"本次运行完成: 发送 {len(newly_sent)} 条")
    logger.info("=" * 50)

    return 0


if __name__ == "__main__":
    sys.exit(main())
