# D-08: PostgreSQL job queue

- **Status:** Accepted
- **Decision:** Claim jobs from a PostgreSQL table with `FOR UPDATE SKIP LOCKED`, leases, and heartbeats. Redis is disposable wake-up and fan-out infrastructure.
- **Rationale:** Domain writes and job creation can remain transactionally consistent without a dual-write queue.
