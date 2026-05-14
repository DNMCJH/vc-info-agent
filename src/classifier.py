"""LLM-based batch domain classifier with keyword fallback."""

import json
import logging

import httpx

from config import Config

logger = logging.getLogger(__name__)

CLASSIFY_PROMPT = """你是一位 VC 行业分析师。请对以下新闻标题进行领域分类。

可选领域：AI、芯片、机器人
规则：
- 每条可以有 1-2 个标签
- 如果与以上三个领域都无关，标记为 ["无关"]
- 只根据标题判断，不要猜测

严格输出 JSON 数组，不要输出其他内容：
[{{"idx": 0, "domains": ["AI"]}}, {{"idx": 1, "domains": ["机器人", "AI"]}}, ...]

标题列表：
{titles}"""


def classify_items(items: list[dict], config: Config) -> list[dict]:
    """Classify items by domain using LLM, with keyword fallback on failure."""
    if not items:
        return items

    # Process in batches of 50 to avoid LLM output truncation
    batch_size = 50
    total_applied = 0

    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        try:
            results = _llm_classify(batch, config)
            for r in results:
                idx = r.get("idx")
                domains = r.get("domains", [])
                if idx is None or idx >= len(batch):
                    continue
                actual_idx = start + idx
                if "无关" in domains:
                    items[actual_idx]["domain"] = "irrelevant"
                elif domains:
                    items[actual_idx]["domain"] = domains[0]
                    if len(domains) > 1:
                        items[actual_idx]["secondary_domains"] = domains[1:]
                total_applied += 1
        except Exception as e:
            logger.warning(f"LLM classification failed for batch {start}-{start+len(batch)}, using keyword fallback: {e}")

    if total_applied:
        logger.info(f"LLM classification applied to {total_applied}/{len(items)} items")

    return items


def _llm_classify(items: list[dict], config: Config) -> list[dict]:
    """Call LLM to classify all items in one batch."""
    titles = "\n".join(f"{i}. {item.get('title', '')}" for i, item in enumerate(items))
    prompt = CLASSIFY_PROMPT.format(titles=titles)

    client = httpx.Client(
        base_url=config.llm_base_url,
        headers={"Authorization": f"Bearer {config.llm_api_key}"},
        timeout=60,
    )
    try:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": config.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 2000,
            },
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        # Extract JSON from response (handle markdown code blocks)
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        # Try parsing; if it fails, attempt to fix truncated JSON
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Find the last complete object in the array
            last_bracket = content.rfind("}]")
            if last_bracket > 0:
                return json.loads(content[:last_bracket + 2])
            raise
    finally:
        client.close()
