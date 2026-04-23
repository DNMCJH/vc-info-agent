# VC Info Agent

[中文版](#中文说明)

An AI-powered information aggregation agent for venture capital professionals. It automatically collects high-quality content from YouTube (expandable to Twitter/X, WeChat), filters noise, and generates a structured daily briefing using LLM.

## Project Structure

```
vc-info-agent/
├── README.md              ← You are here
├── design.md              ← System design document
├── requirements.txt       ← Python dependencies
├── .env.example           ← Environment variable template
├── src/
│   ├── main.py            ← Entry point — runs the full pipeline
│   ├── config.py          ← Configuration and defaults
│   ├── collector.py       ← YouTube data collector
│   ├── filter.py          ← Content quality scoring and filtering
│   └── summarizer.py      ← LLM-based summarization and briefing generation
└── sample_output/
    └── briefing_2026-04-23.md  ← Sample briefing (mock data)
```

## Quick Start

### Prerequisites

- Python 3.10+
- A YouTube Data API v3 key ([get one here](https://console.cloud.google.com/apis/credentials))
- A DeepSeek API key ([get one here](https://platform.deepseek.com/api_keys)), or any OpenAI-compatible LLM API

### Setup

```bash
cd vc-info-agent

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure API keys
cp .env.example .env
# Edit .env and fill in your API keys
```

### Run

```bash
cd src
python main.py
```

The briefing will be saved to `sample_output/briefing_YYYY-MM-DD.md`.

### Using a Different LLM

Edit `.env` to point to any OpenAI-compatible API:

```bash
# OpenAI
LLM_BASE_URL=https://api.openai.com
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-xxx

# Qwen (通义千问)
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode
LLM_MODEL=qwen-plus
LLM_API_KEY=sk-xxx
```

## Design Highlights

- **Multi-dimensional quality scoring**: Each piece of content is scored across 6 dimensions (source credibility, content length, engagement, keyword relevance, recency, spam detection)
- **Feedback loop ready**: Architecture supports user feedback (thumbs up/down) to iteratively improve content selection
- **Mobile-friendly briefing**: Designed to be read in under 5 minutes on a phone — short paragraphs, emoji markers, structured by domain

See [design.md](design.md) for the full system design document.

---

# 中文说明

[English Version](#vc-info-agent)

面向 VC 投资人的 AI 信息聚合 Agent。自动从 YouTube 采集高质量内容（可扩展至 Twitter/X、微信公众号），过滤噪音，通过 LLM 生成结构化每日简报。

## 快速开始

### 环境要求

- Python 3.10+
- YouTube Data API v3 密钥（[申请地址](https://console.cloud.google.com/apis/credentials)）
- DeepSeek API 密钥（[申请地址](https://platform.deepseek.com/api_keys)），或任何 OpenAI 兼容的 LLM API

### 安装

```bash
cd vc-info-agent

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 配置 API 密钥
cp .env.example .env
# 编辑 .env，填入你的 API Key
```

### 运行

```bash
cd src
python main.py
```

简报将保存到 `sample_output/briefing_YYYY-MM-DD.md`。

## 设计亮点

- **多维度质量评分**：6 个维度（来源权威性、内容长度、互动指标、关键词匹配、时效性、垃圾检测）综合打分
- **反馈闭环**：架构支持用户反馈（👍👎），逐步学习偏好
- **手机友好**：简报控制在 5 分钟内读完，短段落 + emoji 标记 + 按领域分区

完整系统设计见 [design.md](design.md)。
