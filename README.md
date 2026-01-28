# 加密政策 RSS -> 企业微信推送工具

自动聚合全球主要金融监管机构的加密货币政策动态，翻译成中文后推送到企业微信群。

## 功能特点

- **多源聚合**: 支持 17+ 权威 RSS 源（BIS、IMF、Fed、ECB、SEC 等）
- **智能过滤**: 基于关键词白名单/黑名单过滤相关内容
- **中文翻译**: 内置金融术语词典，支持 DeepL API 完整翻译
- **自动去重**: 基于状态文件防止重复推送
- **定时推送**: 北京时间每天早上 8:00 自动推送
- **错误处理**: 单个源失败不影响整体，支持指数退避重试

## 文件结构

```
crypto-policy-rss/
├── main.py              # 主程序
├── feeds.json           # RSS 源配置
├── config.json          # 关键词、超时等配置
├── state.json           # 去重状态（自动生成）
├── requirements.txt     # Python 依赖
├── README.md            # 本文件
└── .github/
    └── workflows/
        └── daily.yml    # GitHub Actions 工作流
```

## 快速开始

### 1. 获取企业微信 Webhook

1. 在企业微信群中添加「群机器人」
2. 复制 Webhook 地址，格式如：
   ```
   https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   ```

### 2. 本地测试

```bash
# 安装依赖
pip install -r requirements.txt

# Dry-run 模式（只打印不发送）
DRY_RUN=1 python main.py

# 实际发送
WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx" python main.py
```

### 3. GitHub Actions 部署

1. Fork 本仓库
2. 在 Settings -> Secrets and variables -> Actions 中添加：
   - `WECOM_WEBHOOK_URL`: 企业微信群机器人 Webhook URL
   - （可选）`DEEPL_API_KEY`: DeepL 翻译 API 密钥
   - （可选）`TRANSLATE_API`: 设为 `deepl` 启用 API 翻译
3. 工作流将在每天北京时间 8:00 自动运行

### 4. 手动触发

在 GitHub Actions 页面点击 "Run workflow"，可选择：
- **Dry-run**: 只打印不发送
- **Log level**: 日志详细程度
- **Force run**: 忽略状态文件，重新推送所有内容

## 配置说明

### feeds.json - RSS 源

```json
{
  "feeds": [
    {
      "name": "BIS",
      "full_name": "Bank for International Settlements",
      "url": "https://www.bis.org/doclist/all_rss.rss",
      "tags": ["policy", "cbdc", "international"],
      "enabled": true
    }
  ]
}
```

### config.json - 过滤配置

```json
{
  "keywords": {
    "allow": ["crypto", "bitcoin", "cbdc", "stablecoin"],
    "deny": ["job posting", "career"]
  },
  "settings": {
    "http_timeout_seconds": 30,
    "max_entries_per_feed": 50,
    "state_retention_days": 30
  }
}
```

## 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `WECOM_WEBHOOK_URL` | 是 | 企业微信群机器人 Webhook URL |
| `DRY_RUN` | 否 | 设为 `1` 启用测试模式 |
| `LOG_LEVEL` | 否 | 日志级别（DEBUG/INFO/WARNING） |
| `TRANSLATE_API` | 否 | 翻译 API（none/deepl） |
| `DEEPL_API_KEY` | 否 | DeepL API 密钥 |
| `HTTP_TIMEOUT` | 否 | HTTP 超时（秒） |
| `STATE_RETENTION_DAYS` | 否 | 状态保留天数 |

## 消息格式示例

企业微信群中显示效果：

```
# 📚 加密政策/研报速览
> ⏰ 2024-01-15 08:00 北京时间

**1. [BIS] 央行数字货币(CBDC)跨境支付研究报告**
> Central Bank Digital Currency Cross-border Payment Research
👉 阅读原文
> 本报告探讨了央行数字货币在跨境支付场景中的应用...

**2. [Fed] 美联储(Federal Reserve)发布加密(crypto)资产监管指引**
> Federal Reserve Issues Crypto Asset Regulatory Guidance
👉 阅读原文
> 美联储今日发布针对银行持有加密资产的新指引...

`#policy` `#cbdc` `#regulation`
```

## 支持的 RSS 源

| 来源 | 说明 | 标签 |
|------|------|------|
| BIS | 国际清算银行 | policy, cbdc |
| IMF | 国际货币基金组织 | policy, macro |
| Fed | 美联储 | policy, us |
| ECB | 欧洲央行 | policy, eu |
| SEC | 美国证监会 | regulation, us |
| CFTC | 美国商品期货委员会 | regulation, derivatives |
| FCA | 英国金融行为监管局 | regulation, uk |
| MAS | 新加坡金管局 | policy, asia |
| HKMA | 香港金管局 | policy, asia |
| BOE | 英格兰银行 | policy, uk |
| FSB | 金融稳定委员会 | policy, stability |
| ESMA | 欧洲证监局 | regulation, eu |
| FATF | 金融行动特别工作组 | policy, aml |
| OCC | 美国货币监理署 | regulation, banking |
| PBOC | 中国人民银行 | policy, china |
| CoinDesk | 行业新闻 | news, crypto |
| TheBlock | 行业研究 | research, crypto |

## 翻译说明

默认使用内置词典进行术语翻译，格式为：`中文(English)`

如需完整翻译，请：
1. 获取 DeepL API 密钥（免费版每月 50 万字符）
2. 设置环境变量：
   ```bash
   TRANSLATE_API=deepl
   DEEPL_API_KEY=your_key
   ```

## 企业微信限制

- 单条消息最大 4096 字节（超长自动切换纯文本）
- 每分钟最多 20 条消息（已内置延迟处理）
- Markdown 支持有限，仅支持标题、加粗、链接、引用、代码块

## 许可证

MIT License
