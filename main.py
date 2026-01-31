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
import trafilatura
from openai import OpenAI

# ============== 配置 ==============

BASE_DIR = Path(__file__).parent
FEEDS_FILE = BASE_DIR / "feeds.json"
CONFIG_FILE = BASE_DIR / "config.json"
STATE_FILE = BASE_DIR / "state.json"

# 环境变量
WECOM_WEBHOOK_URL = os.getenv("WECOM_WEBHOOK_URL", "")  # 企业微信 Webhook
DRY_RUN = os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")  # DeepSeek API 密钥

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
    popularity_score: float = 0.0
    smart_summary: Optional[dict] = None  # LLM生成的结构化摘要


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
    # 智能摘要配置
    smart_summary_enabled: bool = True
    smart_summary_score_threshold: int = 70
    smart_summary_max_content_length: int = 4000


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

# 预排序翻译词典（按长度降序，优先匹配长词组）
SORTED_TRANSLATION_TERMS = sorted(TRANSLATION_DICT.keys(), key=len, reverse=True)


def translate_text(text: str) -> str:
    """
    简易翻译：基于词典替换常见术语
    对于完整翻译，建议接入翻译 API（如 Google Translate、DeepL）
    """
    if not text:
        return ""

    result = text
    # 使用预排序列表（模块加载时已排序）
    for en_term in SORTED_TRANSLATION_TERMS:
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

    # 检查是否需要翻译：只有英文字母占比足够高才翻译
    # 统计英文字母数量（不含数字、空格、标点）
    english_chars = len(re.findall(r'[a-zA-Z]', text))
    total_chars = len(text.strip())
    if total_chars == 0:
        return text
    # 英文字母占比低于40%，说明已是中文为主，不翻译
    if english_chars / total_chars < 0.4:
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

    try:
        with open(FEEDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"RSS 源配置文件格式错误: {e}")
        return []
    except Exception as e:
        logger.error(f"读取 RSS 源配置文件失败: {e}")
        return []

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
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"配置文件格式错误: {e}，使用默认配置")
            data = {}
        except Exception as e:
            logger.error(f"读取配置文件失败: {e}，使用默认配置")
            data = {}
    else:
        data = {}

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

        # 智能摘要配置
        smart_summary = data.get("smart_summary", {})
        config.smart_summary_enabled = smart_summary.get("enabled", True)
        config.smart_summary_score_threshold = smart_summary.get("score_threshold", 70)
        config.smart_summary_max_content_length = smart_summary.get("max_content_length", 4000)

    # 环境变量覆盖（带类型转换错误处理）
    def safe_int_env(name: str, default: int) -> int:
        val = os.getenv(name)
        if val:
            try:
                return int(val)
            except ValueError:
                logger.warning(f"环境变量 {name}={val} 不是有效整数，使用默认值 {default}")
        return default

    config.http_timeout = safe_int_env("HTTP_TIMEOUT", config.http_timeout)
    config.max_entries_per_feed = safe_int_env("MAX_ENTRIES_PER_FEED", config.max_entries_per_feed)
    config.state_retention_days = safe_int_env("STATE_RETENTION_DAYS", config.state_retention_days)

    # 智能摘要环境变量覆盖
    if os.getenv("SMART_SUMMARY_ENABLED"):
        config.smart_summary_enabled = os.getenv("SMART_SUMMARY_ENABLED", "").lower() in ("1", "true", "yes")

    logger.info(f"配置已加载: 允许关键词 {len(config.keywords_allow)} 个，"
                f"拒绝关键词 {len(config.keywords_deny)} 个")
    return config


# ============== 状态管理 ==============

def load_state() -> dict[str, Any]:
    """加载状态文件"""
    if not STATE_FILE.exists():
        return {"sent_ids": {}, "last_run": None}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
            # 确保必要字段存在
            if "sent_ids" not in state:
                state["sent_ids"] = {}
            return state
    except json.JSONDecodeError as e:
        logger.error(f"状态文件格式错误: {e}，重新初始化")
        return {"sent_ids": {}, "last_run": None}
    except Exception as e:
        logger.error(f"读取状态文件失败: {e}，重新初始化")
        return {"sent_ids": {}, "last_run": None}


def save_state(state: dict[str, Any]) -> None:
    """保存状态文件（原子写入，避免写入中断导致文件损坏）"""
    state["last_run"] = datetime.now(timezone.utc).isoformat()

    # 先写入临时文件，再原子性重命名
    temp_file = STATE_FILE.with_suffix(".tmp")
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        # 原子性重命名（同一文件系统内是原子操作）
        temp_file.replace(STATE_FILE)
        logger.info("状态已保存")
    except Exception as e:
        logger.error(f"保存状态失败: {e}")
        # 清理临时文件
        if temp_file.exists():
            temp_file.unlink()
        raise


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
    """检查文本是否匹配关键词（使用词边界避免子串误匹配）"""
    text_lower = text.lower()
    for kw in keywords:
        # 使用词边界 \b 避免子串误匹配（如 "etf" 不会匹配 "platform"）
        pattern = r'\b' + re.escape(kw.lower()) + r'\b'
        if re.search(pattern, text_lower):
            return True
    return False


# ============== 网页内容抓取 ==============

def fetch_article_content(url: str, max_length: int = 4000, timeout: int = 30) -> str:
    """
    抓取网页正文内容

    Args:
        url: 文章链接
        max_length: 最大内容长度
        timeout: 超时时间（秒）

    Returns:
        正文内容，失败返回空字符串
    """
    if not url:
        return ""

    try:
        # 使用 trafilatura 抓取和提取正文
        # 设置配置以控制超时
        config = trafilatura.settings.use_config()
        config.set("DEFAULT", "DOWNLOAD_TIMEOUT", str(timeout))
        downloaded = trafilatura.fetch_url(url, config=config)
        if not downloaded:
            logger.warning(f"无法下载页面: {url}")
            return ""

        # 提取正文
        content = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )

        if not content:
            logger.warning(f"无法提取正文: {url}")
            return ""

        # 截断过长内容
        if len(content) > max_length:
            content = content[:max_length]
            # 尝试在句子边界截断
            last_period = content.rfind(".")
            if last_period > max_length * 0.8:
                content = content[:last_period + 1]

        logger.debug(f"成功抓取正文: {url} ({len(content)} 字符)")
        return content

    except Exception as e:
        logger.warning(f"抓取正文失败 {url}: {e}")
        return ""


# ============== DeepSeek 智能摘要 ==============

def generate_smart_summary(title: str, content: str) -> Optional[dict]:
    """
    使用 DeepSeek API 生成结构化摘要

    Args:
        title: 文章标题
        content: 文章正文

    Returns:
        结构化摘要字典，失败返回 None
        {
            "core_point": "一句话核心（20字内）",
            "key_data": ["关键数据1", "关键数据2"],
            "impact": "影响评估（30字内）"
        }
    """
    if not DEEPSEEK_API_KEY:
        logger.warning("DEEPSEEK_API_KEY 未设置，跳过智能摘要")
        return None

    if not content:
        logger.debug("正文为空，跳过智能摘要")
        return None

    try:
        client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )

        prompt = f"""分析以下加密货币/金融新闻，提取关键信息。

标题：{title}

正文：
{content[:3000]}

请用中文回复，严格按以下JSON格式输出（不要添加其他内容）：
{{
    "core_point": "一句话概括核心内容（不超过20字）",
    "key_data": ["关键数据点1", "关键数据点2"],
    "impact": "对市场/行业的影响（不超过30字）"
}}

注意：
- core_point 必须简洁有力，抓住新闻核心
- key_data 提取具体数字、金额、时间、比例等数据，没有则返回空数组
- impact 评估这条新闻的实际影响，偏利好/利空/中性"""

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是专业的加密货币新闻分析师，擅长提炼关键信息。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=500,
        )

        result_text = response.choices[0].message.content.strip()

        # 尝试解析 JSON
        # 处理可能的 markdown 代码块
        if "```" in result_text:
            # 提取代码块内容
            parts = result_text.split("```")
            for part in parts[1::2]:  # 取奇数索引（代码块内容）
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    result_text = part
                    break

        # 如果还不是以 { 开头，尝试用正则提取 JSON 对象
        if not result_text.strip().startswith("{"):
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', result_text, re.DOTALL)
            if json_match:
                result_text = json_match.group()

        summary = json.loads(result_text.strip())

        # 验证必要字段
        if "core_point" not in summary:
            logger.warning("智能摘要缺少 core_point 字段")
            return None

        # 确保 key_data 是列表
        if "key_data" not in summary:
            summary["key_data"] = []
        elif not isinstance(summary["key_data"], list):
            summary["key_data"] = [summary["key_data"]]

        # 确保 impact 存在
        if "impact" not in summary:
            summary["impact"] = ""

        logger.debug(f"智能摘要生成成功: {summary['core_point']}")
        return summary

    except json.JSONDecodeError as e:
        logger.warning(f"智能摘要 JSON 解析失败: {e}")
        return None
    except Exception as e:
        logger.warning(f"智能摘要生成失败: {e}")
        return None


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


# ============== 热度评分系统 ==============

# 来源权威性权重 (0-35分)
SOURCE_WEIGHTS = {
    "SEC": 35,
    "CoinDesk": 30,
    "TheBlock": 28,
    "Cointelegraph": 26,
    "Decrypt": 22,
    "CryptoSlate": 20,
    "CardanoSpot": 18,
    "IOHK-Blog": 18,
    "AdaPulse": 16,
    "Cardano-Forum": 15,
    "U.Today": 14,
    "NewsBTC": 12,
    "BeInCrypto": 12,
}

# 标题热词 (累计最高25分)
HOT_KEYWORDS = {
    "breaking": 10,
    "surge": 5,
    "crash": 5,
    "etf": 6,
    "approved": 7,
    "sec": 5,
    "regulation": 4,
    "bitcoin": 3,
    "ethereum": 3,
    "ban": 5,
    "hack": 5,
    "lawsuit": 4,
    "settlement": 4,
    "partnership": 3,
    "launch": 3,
    "upgrade": 3,
    "mainnet": 4,
    "airdrop": 3,
}

# Cardano 关键词（用于加分）
CARDANO_KEYWORDS = ["cardano", "ada", "iohk", "hoskinson", "plutus", "hydra", "midnight", "lace", "voltaire"]


def calculate_popularity_score(entry: FeedEntry) -> float:
    """
    计算文章热度评分

    评分维度：
    1. 来源权威性 (0-35分)
    2. 标题热词 (0-25分)
    3. 时效性 (0-20分)
    4. 内容质量启发 (0-15分)
    5. Cardano 加分 (0-20分)

    总分范围: 0-115分
    """
    score = 0.0

    # 1. 来源权威性 (0-35分)
    source_score = SOURCE_WEIGHTS.get(entry.source, 10)
    score += source_score

    # 2. 标题热词 (0-25分，累计)
    title_lower = entry.title.lower()
    keyword_score = 0
    for keyword, points in HOT_KEYWORDS.items():
        if keyword in title_lower:
            keyword_score += points
    score += min(keyword_score, 25)  # 上限25分

    # 3. 时效性 (0-20分)
    now = datetime.now(timezone.utc)
    age_hours = (now - entry.published).total_seconds() / 3600
    if age_hours <= 2:
        score += 20
    elif age_hours <= 6:
        score += 15
    elif age_hours <= 12:
        score += 10
    elif age_hours <= 24:
        score += 5

    # 4. 内容质量启发 (0-15分)
    # 标题长度适中 (20-80字符) +5分
    title_len = len(entry.title)
    if 20 <= title_len <= 80:
        score += 5
    # 有摘要 +5分
    if entry.summary and len(entry.summary) > 50:
        score += 5
    # 有链接 +5分
    if entry.link:
        score += 5

    # 5. Cardano 加分 (0-30分，确保优先推送)
    combined_text = f"{entry.title} {entry.summary}".lower()
    if any(kw in combined_text for kw in CARDANO_KEYWORDS):
        score += 20  # 关键词匹配
    # 来自 Cardano 专用源 +10分
    if any(tag in ["cardano", "ada"] for tag in entry.tags):
        score += 10

    return score


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

def get_importance_level(score: float) -> tuple[str, str]:
    """
    根据热度评分获取重要度级别

    Returns:
        (emoji标签, 级别名称)
    """
    if score >= 70:
        return "🔴", "必读"
    elif score >= 50:
        return "🟡", "重要"
    else:
        return "🟢", "参考"


def format_wecom_markdown(entries: list[FeedEntry]) -> str:
    """格式化企业微信 Markdown 消息（中文版，支持分级显示）"""
    # 北京时间
    beijing_tz = timezone(timedelta(hours=8))
    now_beijing = datetime.now(beijing_tz)

    lines = [
        "# 📚 加密政策/研报速览",
        f"> ⏰ {now_beijing.strftime('%Y-%m-%d %H:%M')} 北京时间",
        "",
    ]

    for i, entry in enumerate(entries, 1):
        # 获取重要度级别
        emoji, level = get_importance_level(entry.popularity_score)

        # 来源标签
        source_tag = f"[{entry.source}]"

        # 标题行：重要度 + 来源 + 标题
        lines.append(f"**{emoji} {level} | {source_tag} {entry.title_zh}**")

        # 根据是否有智能摘要决定显示格式
        if entry.smart_summary:
            # 必读级别：显示结构化智能摘要
            summary = entry.smart_summary

            # 核心观点
            lines.append(f"📌 核心：{summary.get('core_point', '')}")

            # 关键数据
            key_data = summary.get('key_data', [])
            if key_data:
                data_str = " | ".join(key_data[:3])  # 最多3个数据点
                lines.append(f"📊 数据：{data_str}")

            # 影响评估
            impact = summary.get('impact', '')
            if impact:
                lines.append(f"⚡ 影响：{impact}")
        else:
            # 普通级别：显示RSS原摘要
            if entry.summary_zh:
                summary_text = entry.summary_zh[:150]
                if len(entry.summary_zh) > 150:
                    summary_text += "..."
                lines.append(f"> {summary_text}")

        # 链接
        lines.append(f"[👉 原文]({entry.link})")
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
    MAX_MESSAGE_BYTES = 4000  # 留100字节余量

    for i in range(0, len(entries), batch_size):
        batch = entries[i:i + batch_size]
        message = format_wecom_markdown(batch)

        # 如果消息过长，尝试使用纯文本格式
        if len(message.encode('utf-8')) > MAX_MESSAGE_BYTES:
            logger.warning("Markdown消息过长，切换为纯文本格式")
            message = format_wecom_text(batch)

            # 纯文本仍超限，逐条拆分发送
            if len(message.encode('utf-8')) > MAX_MESSAGE_BYTES:
                logger.warning("纯文本仍超限，改为逐条发送")
                # 将当前批次拆分为单条发送
                for single_entry in batch:
                    single_message = format_wecom_text([single_entry])
                    # 单条仍超限则截断
                    if len(single_message.encode('utf-8')) > MAX_MESSAGE_BYTES:
                        single_message = single_message[:MAX_MESSAGE_BYTES].rsplit('\n', 1)[0]
                    try:
                        send_wecom_message(single_message, WECOM_WEBHOOK_URL, "text")
                        sent_ids.append(single_entry.id)
                        time.sleep(delay)
                    except Exception as e:
                        logger.error(f"单条发送失败 [{single_entry.source}] {single_entry.title[:30]}: {e}")
                continue  # 跳过后续批次发送逻辑

        batch_num = i // batch_size + 1
        max_batch_retries = 3

        for retry in range(max_batch_retries):
            try:
                send_wecom_message(message, WECOM_WEBHOOK_URL, "markdown")
                sent_ids.extend(e.id for e in batch)
                logger.info(f"已发送第 {batch_num} 批 ({len(batch)} 条)")
                break  # 发送成功，跳出重试循环
            except Exception as e:
                if retry < max_batch_retries - 1:
                    wait_time = 2 ** (retry + 1)  # 指数退避：2, 4, 8 秒
                    logger.warning(f"第 {batch_num} 批发送失败 (尝试 {retry + 1}/{max_batch_retries}): {e}，{wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    # 最终失败，记录未发送的条目
                    failed_titles = [e.title[:30] for e in batch]
                    logger.error(f"第 {batch_num} 批最终发送失败: {e}")
                    logger.error(f"未发送条目: {failed_titles}")

        # 批次间延迟（企业微信限制每分钟 20 条）
        if i + batch_size < len(entries):
            time.sleep(delay)

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

    # 计算热度评分并排序
    for entry in all_entries:
        entry.popularity_score = calculate_popularity_score(entry)

    # 按热度评分排序（同分按时间）
    all_entries.sort(key=lambda e: (e.popularity_score, e.published), reverse=True)

    logger.info(f"共发现 {len(all_entries)} 条新条目")

    # 只推送前20条最重要的文章
    MAX_DAILY_ENTRIES = 20
    if len(all_entries) > MAX_DAILY_ENTRIES:
        logger.info(f"筛选前 {MAX_DAILY_ENTRIES} 条最重要的文章")
        all_entries = all_entries[:MAX_DAILY_ENTRIES]

    # 打印热度评分（调试用）
    if all_entries:
        logger.info("热度排名前5:")
        for i, entry in enumerate(all_entries[:5], 1):
            emoji, level = get_importance_level(entry.popularity_score)
            logger.info(f"  {i}. {emoji}{level} [{entry.source}] {entry.title[:50]}... (评分: {entry.popularity_score:.1f})")

    # 为高分文章生成智能摘要
    if config.smart_summary_enabled and DEEPSEEK_API_KEY:
        logger.info("开始为必读级文章生成智能摘要...")
        smart_summary_count = 0

        for entry in all_entries:
            if entry.popularity_score >= config.smart_summary_score_threshold:
                logger.info(f"  抓取正文: {entry.title[:40]}...")

                # 抓取文章全文
                content = fetch_article_content(
                    entry.link,
                    max_length=config.smart_summary_max_content_length,
                    timeout=config.http_timeout
                )

                if content:
                    # 生成智能摘要
                    logger.info(f"  生成摘要: {entry.title[:40]}...")
                    summary = generate_smart_summary(entry.title, content)

                    if summary:
                        entry.smart_summary = summary
                        smart_summary_count += 1
                        logger.info(f"  ✓ 摘要完成: {summary.get('core_point', '')[:30]}...")
                    else:
                        logger.warning(f"  ✗ 摘要生成失败，使用RSS原摘要")
                else:
                    logger.warning(f"  ✗ 正文抓取失败，使用RSS原摘要")

                # API调用间隔
                time.sleep(1.0)

        logger.info(f"智能摘要完成: {smart_summary_count}/{len([e for e in all_entries if e.popularity_score >= config.smart_summary_score_threshold])} 篇")
    elif config.smart_summary_enabled and not DEEPSEEK_API_KEY:
        logger.warning("智能摘要已启用但 DEEPSEEK_API_KEY 未设置，跳过智能摘要")

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
