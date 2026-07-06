---
name: build-partitioned-events
description: Scalable event distribution via consistent hashing (uhashring).
when_to_use: Use when an event stream must be sharded across multiple worker partitions.
group: coding
kind: skill
source_prompt: build-partitioned-events.md
---

# Partitioned Events

## Skill summary

- **Name:** `build-partitioned-events`
- **Description:** Scalable event distribution via consistent hashing (uhashring).
- **When to use:** Use when an event stream must be sharded across multiple worker partitions.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `build-partitioned-events.md`

## Examples

- The user asks: "Add or revise the partitioned events for this feature."
- You want the canonical build pattern before touching partitioned events.

## Guidance

> **Note**
It is essential to refer to the `skills/coding/build-domain-features/SKILL.md` file before reading this each time as it contains important information about events. 

### The `partition_config.py` File

The `partition_config.py` creates a continuum with `n` partitions that publish the events into one of the partitions using consistent hashing. 

We use the `uhashring` library for this and create a predefined set of worker nodes with a specific `worker_name`. The workers could be Celery[Redis] workers or any other kind. 

Here is how the `partition_config.py` file looks. 

```python
from config import cfg
from pydantic import BaseModel
from typing import Dict, Optional
from uuid import UUID, uuid4
from uhashring import HashRing
from mmh3 import hash as m3h

continuum = {
    "67ce52a1-4f28-4634-8437-b188cd5eda66": {
        "hostname": cfg("REDIS_URL"),
        "worker_name": "system_events_worker_01",
    },
    "e1166979-53d5-4193-a214-d7f944555536": {
        "hostname": cfg("REDIS_URL"),
        "worker_name": "system_events_worker_02",
    },
    "bf316a57-a877-41cb-8bf7-389c0ab0c5d2": {
        "hostname": cfg("REDIS_URL"),
        "worker_name": "system_events_worker_03",
    },
    "0573d06f-4aca-4600-b49d-eb715365ed14": {
        "hostname": cfg("REDIS_URL"),
        "worker_name": "system_events_worker_04",
    },
    "fea71e29-7c75-4d3e-80f3-346ea8ae1e30": {
        "hostname": cfg("REDIS_URL"),
        "worker_name": "system_events_worker_05",
    },
    "20fb96c8-e4c4-4d9b-90ba-155481c6c78d": {
        "hostname": cfg("REDIS_URL"),
        "worker_name": "system_events_worker_06",
    },
    "b1d2a320-23c6-4c2e-97d5-ffd8740f1f2c": {
        "hostname": cfg("REDIS_URL"),
        "worker_name": "system_events_worker_07",
    },
    "2da2b3e8-8fb9-4bdc-b0ea-9ebde2fae8f3": {
        "hostname": cfg("REDIS_URL"),
        "worker_name": "system_events_worker_08",
    },
}

ring = HashRing(continuum, hash_fn=m3h)
```

The service file for the SystemEvent domain is unique and contains certain methods which aren't standard CRUD because the `system_events` table is an immutable log of data. 

### How Are Events Used

The events usage can be learned by looking at the `skills/coding/build-application-services/SKILL.md` file
