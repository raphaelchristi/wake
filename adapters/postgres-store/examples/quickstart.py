"""Quickstart: hello-world against a local Postgres.

Run a Postgres 16 instance locally (``docker run -p 5432:5432 -e
POSTGRES_PASSWORD=wake -e POSTGRES_USER=wake -e POSTGRES_DB=wake
postgres:16-alpine``) then::

    python examples/quickstart.py

The script:

1. Builds a ``PostgresStore`` from the DSN.
2. Runs Alembic to head (idempotent).
3. Creates an agent, opens a session, and appends a few events.
4. Subscribes briefly to demonstrate live event delivery via LISTEN/NOTIFY.
5. Reads everything back to prove durability.
"""

from __future__ import annotations

import asyncio
import os

from wake.types import ModelConfig

from wake_store_postgres import PostgresStore

DSN = os.environ.get(
    "WAKE_PG_DSN",
    "postgresql+asyncpg://wake:wake@localhost:5432/wake",
)


async def main() -> None:
    store = PostgresStore(DSN)
    await store.initialize()
    try:
        agent = await store.agents.create(name="hello", model=ModelConfig(id="claude-opus-4-7"))
        session = await store.sessions.create(agent_id=agent.id, agent_version=agent.version)

        # Append a few events.
        for i in range(3):
            await store.events.append(session.id, "status", {"phase": "running", "step": i})

        # Read everything back.
        events = await store.events.get(session.id)
        print(f"appended {len(events)} events:")
        for e in events:
            print(f"  seq={e.seq} type={e.type} payload={e.payload}")

        # Brief subscribe demo.
        print("subscribing for 0.5s to demonstrate live delivery…")
        received: list[int] = []

        async def consume() -> None:
            gen = await store.events.subscribe(session.id, since=len(events))
            async for ev in gen:
                received.append(ev.seq)
                if len(received) >= 1:
                    break

        async def produce() -> None:
            await asyncio.sleep(0.1)
            await store.events.append(session.id, "status", {"phase": "live"})

        try:
            await asyncio.wait_for(asyncio.gather(consume(), produce()), timeout=2.0)
        except TimeoutError:
            print("subscribe timed out (Postgres NOTIFY may be unavailable)")
        else:
            print(f"received live event with seq={received[0]}")
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
