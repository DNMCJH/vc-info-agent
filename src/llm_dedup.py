"""LLM-based dedup refinement.

Coarse entity-overlap clustering (filter.py) over-merges: any two items
sharing a strong proper noun become candidates, but "Google launches X"
and "Google sues Y" share only the company name. This module asks an
LLM to split each candidate cluster into true event groups, so the
final dedup keeps only items that genuinely cover the same event.
"""

import json
import logging
import re
from collections import defaultdict

import httpx

from config import Config
from filter import ContentFilter

logger = logging.getLogger(__name__)


CLUSTER_PROMPT = """你是新闻事件去重助手。下面是一组可能描述同一事件的资讯（共享同一个公司/产品名）。
请判断哪些条目在讲**同一个具体事件**（同一次发布、同一起融资、同一份报告等），把同事件的条目编号分到一组。

判定标准：
- 同事件 = 同一次具体新闻（同一次发布会、同一笔交易、同一篇研究等），不是只共享一个公司或人物
- 不同事件 = 同一公司的两条不同新闻（如「Google 发布 Gemini」vs「Google 起诉 OpenAI」）应分开

输出严格 JSON 数组，每个元素是同事件的条目编号列表。所有编号都必须出现且只出现一次。
示例输出：[[0, 2], [1], [3, 4]]

资讯列表：
{items}

只输出 JSON 数组，不要任何额外文字。"""


class LLMDeduplicator:
    """Refines coarse entity clusters by asking LLM to split them into true events."""

    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.Client(
            base_url=config.llm_base_url,
            headers={"Authorization": f"Bearer {config.llm_api_key}"},
            timeout=60,
        )

    def close(self):
        self.client.close()

    def refine(self, items: list[dict]) -> list[dict]:
        """Coarse-cluster by shared strong entity, then LLM-split each cluster.

        Items must already be sorted by quality_score desc — the first
        item in each final group is the one kept; the rest go into
        merged_from on the kept item.
        """
        # Build clusters: items sharing >=1 strong entity belong to the
        # same coarse cluster. Use union-find over strong entities.
        n = len(items)
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        # Map strong entity -> list of item indices that contain it; pair-up indices
        ent_to_indices: dict[str, list[int]] = defaultdict(list)
        item_strong: list[set[str]] = []
        for i, item in enumerate(items):
            strong, _weak = ContentFilter._extract_entities(item)
            item_strong.append(strong)
            for ent in strong:
                ent_to_indices[ent].append(i)

        for indices in ent_to_indices.values():
            if len(indices) < 2:
                continue
            for i in indices[1:]:
                union(indices[0], i)

        # Group indices by cluster root
        clusters: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            clusters[find(i)].append(i)

        # For singleton clusters, no LLM call needed — keep as-is.
        result: list[dict] = []
        llm_calls = 0
        for indices in clusters.values():
            if len(indices) == 1:
                result.append(items[indices[0]])
                continue

            # Multi-item cluster — ask LLM to split into event groups.
            cluster_items = [items[i] for i in indices]
            try:
                groups = self._split_cluster(cluster_items)
                llm_calls += 1
            except Exception as e:
                logger.warning(
                    f"LLM dedup failed on cluster of {len(cluster_items)}, keeping all: {e}"
                )
                result.extend(cluster_items)
                continue

            # Each group is a list of local indices (0-based within cluster_items).
            # First item in each group (highest quality_score, since input was
            # pre-sorted) wins; the rest fold into its merged_from.
            seen_local: set[int] = set()
            for group in groups:
                if not group:
                    continue
                # Validate: indices must be in range and unique
                group = [g for g in group if 0 <= g < len(cluster_items) and g not in seen_local]
                if not group:
                    continue
                seen_local.update(group)
                # Sort by original quality_score so the strongest stays first;
                # LLM's group ordering is not load-bearing.
                group.sort(key=lambda g: cluster_items[g].get("quality_score", 0), reverse=True)
                kept = cluster_items[group[0]]
                for g in group[1:]:
                    dup = cluster_items[g]
                    kept.setdefault("merged_from", []).append({
                        "title": dup.get("title", ""),
                        "url": dup.get("url", ""),
                        "channel": dup.get("channel", ""),
                    })
                result.append(kept)

            # Defensive: any item the LLM forgot to include — keep it standalone.
            for j, it in enumerate(cluster_items):
                if j not in seen_local:
                    logger.warning(f"LLM dedup omitted item {j}, keeping standalone: {it.get('title','')[:50]}")
                    result.append(it)

        # Re-sort by quality_score so downstream selection sees the right order.
        result.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
        logger.info(f"LLM dedup: {n} items -> {len(result)} events ({llm_calls} LLM calls)")
        return result

    def _split_cluster(self, cluster_items: list[dict]) -> list[list[int]]:
        """Ask LLM to split one coarse cluster into event groups."""
        lines = []
        for i, item in enumerate(cluster_items):
            title = item.get("title", "")[:120]
            desc = item.get("description", "")[:150].replace("\n", " ")
            channel = item.get("channel", "")
            lines.append(f"[{i}] 标题: {title}\n     来源: {channel}\n     描述: {desc}")
        prompt = CLUSTER_PROMPT.format(items="\n\n".join(lines))

        resp = self.client.post(
            "/v1/chat/completions",
            json={
                "model": self.config.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 200,
            },
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()

        # Strip markdown code fences if model wrapped output in them
        match = re.search(r"\[\s*\[.*?\]\s*\]", raw, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON array found in response: {raw[:200]}")
        groups = json.loads(match.group(0))
        if not isinstance(groups, list) or not all(isinstance(g, list) for g in groups):
            raise ValueError(f"Bad shape: {raw[:200]}")
        return groups
