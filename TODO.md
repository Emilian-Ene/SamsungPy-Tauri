# TODO

## Completed

### Option B routing architecture

- Each screen record must store both `tv_ip` and `agent_id`.
- Frontend sends command requests with both values to cloud backend.
- Cloud backend enqueues by `agent_id` bucket and does not call TV IP directly.
- Only the Pi agent whose `AGENT_ID` equals the job `agent_id` can poll and receive that job.
- The matched agent executes locally in its LAN using the job `tv_ip`.

### Explore Agents workflow

- Explore Agents page is available.
- Agent status list supports auto refresh and manual refresh.
- Clicking an agent row opens a TV list scoped to that agent.
- Clicking the same selected agent row again collapses that TV list.
- Clicking a TV row from the agent TV list switches to Controls with that TV selected.

## Example mapping

- Screens 1-5 -> `agent_id=shop-a`
- Screens 6-10 -> `agent_id=shop-b`
- Command for screen 8 (`tv_ip=192.168.1.50`, `agent_id=shop-b`) is executable only by agent `shop-b`.

## Planned

- Add `Timestamp Monitor` page:
  - Check all saved TVs every 1 minute
  - Track and show `last online` timestamp per device
  - Track and show `last offline` timestamp per device
  - Keep list auto-refreshing every minute
