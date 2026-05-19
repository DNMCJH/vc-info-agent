"""TTS demo — generate a sample briefing audio with edge-tts."""

import asyncio
import edge_tts

SAMPLE_TEXT = """
今日 VC 简报速览。

第一条，AI 领域。OpenAI 发布 GPT-5 技术报告，重点提升了多模态推理能力，代码生成准确率提升 40%。

第二条，芯片领域。台积电宣布 2 纳米工艺量产时间表提前至 2025 年第四季度，良率已达 80%。

第三条，机器人领域。Figure 公司完成新一轮 6.75 亿美元融资，估值达到 39 亿美元，将用于人形机器人量产。

以上是今日精选 3 条，完整报告请查看飞书卡片。
"""

OUTPUT_PATH = "a:/VScode/Code/Projects/vc-info-agent/sample_output/demo_briefing.mp3"


async def main():
    # zh-CN-XiaoxiaoNeural: 女声，自然流畅
    # zh-CN-YunxiNeural: 男声，偏新闻播报
    voice = "zh-CN-XiaoxiaoNeural"
    communicate = edge_tts.Communicate(SAMPLE_TEXT.strip(), voice, rate="+10%")
    await communicate.save(OUTPUT_PATH)
    print(f"Audio saved to: {OUTPUT_PATH}")
    print(f"Voice: {voice}, Rate: +10%")


if __name__ == "__main__":
    asyncio.run(main())
