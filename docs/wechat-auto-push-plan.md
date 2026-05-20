# WeChat Auto-Push Integration Plan

Status: design — pending user decision on approach
Date: 2026-05-20

## Problem

`scheduler.py` runs the pipeline daily at 08:00. After the briefing is generated,
the user wants the WeChat card + links pushed automatically. Currently:

- `main.py` calls `FeishuDelivery.send()` only.
- `WechatDelivery` (wxauto-based) exists but is **never called from the pipeline**.
- wxauto requires a logged-in WeChat **desktop client on Windows with GUI**.
- VPS (`tcloud`, Ubuntu, headless) cannot run wxauto. Scheduler currently lives
  on the user's local machine (presumed Windows), or could be moved.

## What was wired in this session

`main.py` step 7 now contains an **env-gated WeChat hook**:

```python
wechat_chat = os.getenv("WECHAT_CHAT_NAME", "").strip()
if wechat_chat and card_path:
    h5_base = os.getenv("H5_BASE_URL", "").rstrip("/")
    detail_url = f"{h5_base}/briefing/{date_str}" if h5_base else None
    audio_url = f"{h5_base}/audio/briefing_{date_str}.mp3" if ...
    WechatDelivery(wechat_chat).send(card_path, audio_url, detail_url)
```

- If `WECHAT_CHAT_NAME` is **unset**, the hook is a no-op — VPS-safe.
- If set on a Windows machine with WeChat desktop running, the push fires.
- `H5_BASE_URL=https://vcbrief.site` is already in `.env`.

To enable WeChat push: add `WECHAT_CHAT_NAME=<chat or contact name>` to `.env`
on the machine that runs the scheduler.

## The deployment question

We still need to choose **where the scheduler lives**.

### Option A: Scheduler on local Windows (simplest, recommended for now)

- Run `python scheduler.py` on the user's main Windows PC.
- WeChat desktop must be running and logged in at 08:00.
- Pros: works today, no extra infra, wxauto path is unmodified.
- Cons: requires PC awake at 08:00 (or use Windows Task Scheduler to wake/run).
  If PC is asleep / off, no push.

### Option B: Scheduler on VPS (cloud) + Feishu only, no WeChat

- Move scheduler to VPS, drop WeChat push for now.
- Pros: reliable, always-on. Feishu already works.
- Cons: no WeChat push (which is the whole point of this thread).

### Option C: Hybrid — VPS schedules + signals local Windows to push

- VPS generates briefing daily (current pipeline minus WeChat step).
- A lightweight local Windows agent polls VPS for "new briefing today?" and
  triggers `WechatDelivery` against the just-fetched data.
- Pros: pipeline reliability decoupled from PC uptime; WeChat push works when
  PC happens to be on.
- Cons: more moving parts; need a poll endpoint or webhook on VPS.

### Option D: Replace wxauto with WeCom (企业微信) bot webhook  ✅ implemented (2026-05-20)

- 企业微信 has a real webhook API like Feishu — no GUI needed.
- Push from VPS directly, no Windows dependency.
- Pros: cloud-native, reliable, same model as Feishu.
- Cons: requires 企业微信 setup, push goes to 企业微信 not personal WeChat.
  User's actual audience might not use 企业微信.

**Status**: `src/wecom_delivery.py` written, wired into `main.py` step 7. Sends
a `news` image card (clickable, links to H5 detail page) when `H5_BASE_URL` +
card image are available; falls back to `markdown` text otherwise. Gated by
`WECOM_WEBHOOK_URL` env var — no-op when unset, so safe to merge.

**To enable**: create a 企业微信 group bot, copy its webhook URL, set
`WECOM_WEBHOOK_URL=<url>` in `.env`. Coexists with Options A/B/C — all three
delivery channels (Feishu / personal WeChat / WeCom) can fire from one run.

## Recommended next step

Start with **Option A** because the infra is already in place — just set
`WECHAT_CHAT_NAME` and run `python scheduler.py` on the Windows PC during a
window when WeChat desktop is open. Validate the end-to-end flow before
investing in Option C or D.

If Option A proves unreliable (PC frequently off / wxauto flaky), escalate to
Option C. Option D is the cleanest long-term answer if 企业微信 fits the
distribution model.

## Open questions for the user

1. Which chat / contact name should `WECHAT_CHAT_NAME` be set to?
2. Is the daily 08:00 cron OK, or should it move (e.g. evening)?
3. Is 企业微信 (Option D) viable for the target audience?
