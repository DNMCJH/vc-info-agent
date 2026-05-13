# Deployment Guide

## Server Info

- Provider: Tencent Cloud Lighthouse (Hong Kong)
- IP: 43.128.24.23
- OS: Ubuntu 24.04 LTS
- User: ubuntu
- Project path: `/home/ubuntu/vc-info-agent`

## Services

| Service | Port | systemd unit |
|---|---|---|
| Feedback Server | 9002 | vc-feedback.service |
| Scheduler | - | vc-scheduler.service |

## Update Code

```bash
cd ~/vc-info-agent
git pull origin main
pip install -r requirements.txt  # only if dependencies changed
sudo systemctl restart vc-scheduler vc-feedback
```

## Restart Services

```bash
sudo systemctl restart vc-scheduler vc-feedback
```

## Check Status

```bash
sudo systemctl status vc-feedback --no-pager
sudo systemctl status vc-scheduler --no-pager
sudo journalctl -u vc-scheduler --no-pager -n 20
```

## Manual Pipeline Run

```bash
cd ~/vc-info-agent/src
source ../venv/bin/activate
python main.py
```

## Backup

Automated daily backup via cron (see `/home/ubuntu/backup.sh`):

```bash
# Check backup status
ls -la ~/backups/
```

Manual backup:

```bash
~/backup.sh
```

## Configuration

All secrets in `/home/ubuntu/vc-info-agent/.env` (not in git).

Required keys:
- `LLM_API_KEY` — DeepSeek API key
- `YOUTUBE_API_KEY` — YouTube Data API v3
- `FEISHU_WEBHOOK` — Feishu bot webhook URL
- `TWITTER_BEARER_TOKEN` — X/Twitter API v2 bearer token
- `FEEDBACK_BASE_URL` — Public URL for feedback server (http://43.128.24.23:9002)

## Firewall

Tencent Cloud console → Firewall:
- TCP 22: SSH
- TCP 80: HTTP (reserved)
- TCP 9002: Feedback server
- ICMP: Ping

## Troubleshooting

**Pipeline fails silently:**
```bash
sudo journalctl -u vc-scheduler --since "1 hour ago" --no-pager
```

**Feedback server not responding:**
```bash
curl http://localhost:9002/feedback?id=test&r=like
sudo systemctl restart vc-feedback
```

**Disk space:**
```bash
df -h /
du -sh ~/vc-info-agent/data/
```
