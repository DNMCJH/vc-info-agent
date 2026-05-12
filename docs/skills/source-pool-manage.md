---
name: source-pool-manage
description: Manage multi-platform source pool — add, prioritize, activate, and retire information sources.
version: 0.1
owner: 陈嘉豪
---

## When to use
When adding new sources, changing source priority/status, or reviewing source pool coverage.

## Inputs
- Source metadata: name, platform, URL, category, priority, language, access_method
- Status change request: candidate → active, active → disabled

## Preconditions
- `src/source_pool.yaml` exists and is valid YAML

## Steps
1. Identify source platform and access method
2. Assign category from: research_pioneer, power_center, builder_practitioner, educator_curator, ethics_safety, cn_media, vc_startup
3. Set priority (P0/P1/P2) based on signal value and update frequency
4. Set status: active (has working collector), candidate (important but no automation), pending (needs research)
5. Add entry to source_pool.yaml
6. If active: ensure corresponding collector can handle it

## Outputs
- Updated `src/source_pool.yaml`
- If new platform: stub collector or access_method documentation

## Validation
- YAML parses without error
- No duplicate source_id
- Status accurately reflects automation capability
