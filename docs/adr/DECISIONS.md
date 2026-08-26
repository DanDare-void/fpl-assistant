# Architecture Decision Records — FPL Assistant

Decisions specific to the FPL assistant. Cluster/infrastructure decisions live in the
separate `keel-cluster` repo.

---

## Index

| ADR  | Title | Status |
|------|-------|--------|
| 0001 | Haaland Watch Runs as a k3s CronJob (No Custom Image) | Accepted |
| 0002 | FPL Assistant Runs on keel, Image Built on-Node (No Registry) | Accepted |

---

## ADR 0001: Haaland Watch Runs as a k3s CronJob (No Custom Image)

**Status:** Accepted
**Date:** 2026-08-23
**Relates to:** keel-cluster ADR 0001 (k3s adoption)

### Context

The Haaland pivot-watch (`scripts/haaland_watch.py`) checks weekly whether Erling
Haaland's underlying rate (xG/90) and points pace justify pivoting the no-Haaland
"spread squad" into a Haaland build, and emails a verdict. It ran as a node-local
crontab entry on pi-a (now keel-w5), which pinned it to one SD-card node — the exact
coupling the move to a cluster is meant to remove.

The script is stdlib-only (no pip dependencies) and sends mail via Gmail SMTP, reading
credentials that previously came from pi-a's `~/the-tissue/.env`.

### Decision

Run it as a Kubernetes `CronJob` (`k8s/haaland-watch-cronjob.yaml`, namespace
`football`, `17 8 * * 2` Europe/London) using a **stock `python:3.12-slim` image** with:

- the script mounted from a **ConfigMap** (`haaland-watch-script`), and
- SMTP creds injected from a **Secret** (`haaland-smtp`) via `envFrom`.

The script was adapted to read creds from the environment (the Secret) first, falling
back to the `.env` file — so the *same* file runs both in-cluster and standalone. The
node-local crontab on pi-a was retired once the CronJob was verified sending mail.

### Consequences

**Positive:**
- **No image build and no container registry** — the biggest simplification. A stdlib
  script + ConfigMap on a public base image sidesteps building/pushing arm64 images,
  which a small homelab k3s cluster has no registry for.
- The job runs on any available node and survives a single node dying.
- Credentials live in a Secret, not on a node's disk; updating the script is a
  ConfigMap change, not a redeploy of an image.

**Negative:**
- Mounting source via ConfigMap suits a single small script; a multi-file or
  dependency-bearing app would warrant a real image and registry instead.
- The image is pulled from Docker Hub at run time (cached after first pull) — a public
  dependency, acceptable for a weekly job.

**Rejected:**
- **Keep the node crontab** — works, but pins the job to one node and defeats the
  cluster's purpose.
- **Build a custom image** — cleaner packaging, but needs a registry the cluster
  doesn't have, for no benefit given a zero-dependency script.

---

## ADR 0002: FPL Assistant Runs on keel, Image Built on-Node (No Registry)

**Status:** Accepted
**Date:** 2026-08-26
**Relates to:** ADR 0001; keel-cluster ADR 0001 (k3s adoption)

### Context

The FPL assistant (FastAPI backend + built React frontend + SQLite cache) ran only on
the Beelink management box, started by hand. With the keel cluster stable (8 nodes,
SSD-booted, monitored), the app should run there — always on, on the LAN, surviving
the Beelink being off. Unlike the Haaland watch (ADR 0001), this is a multi-file app
with pip and npm dependencies, so the "ConfigMap on a stock image" trick doesn't
stretch to it: it needs a real container image. The cluster has no registry, the
management box has no Docker, and the nodes are arm64 while the Beelink is x86_64.

### Decision

- **Multi-stage `Dockerfile`**: `node:20-slim` builds `frontend/dist`, then
  `python:3.12-slim` runs uvicorn serving both API and static files from `/app`.
- **Build natively on keel-w5 with podman** and pipe `podman save` into
  `k3s ctr -n k8s.io images import` on the same node — no registry, no cross-arch
  emulation. `scripts/deploy-cluster.sh` does the whole cycle (rsync → build →
  import → apply → restart).
- **Deployment pinned to keel-w5** (`k8s/fpl-assistant.yaml`, namespace `football`):
  SQLite sits on a `local-path` PV, which is node-local, and keel-w5 has the NVMe.
  `imagePullPolicy: Never` + image name `localhost/fpl-assistant:dev`; strategy
  `Recreate` so two pods never share the SQLite file.
- **NodePort 30080** (any node IP, LAN only) — same pattern as Grafana's 30030.
- **Secret `fpl-assistant-env`** created imperatively from the local `.env`
  (`kubectl -n football create secret generic fpl-assistant-env --from-env-file=.env`),
  never committed. `DATABASE_PATH` is overridden in the Deployment to point at the PV.

### Consequences

**Positive:**
- App is always on at `http://<any-node>:30080`; the Beelink is only needed to deploy.
- One script rebuilds and rolls out; re-importing the same tag + `rollout restart`
  picks up the new image because the pull policy is `Never`.
- Native arm64 builds on the Pi 5 avoid qemu emulation entirely.

**Negative:**
- The image exists only on keel-w5: the pin is load-bearing twice over (PV locality
  *and* image locality). If keel-w5 dies, redeploying elsewhere means re-running the
  build against another node and losing/restoring the SQLite cache (mostly
  re-fetchable; stored reports are the only real loss).
- FPL Bearer tokens are held in backend memory, so every redeploy logs the Manage
  tab out — unchanged from local, but restarts are now more routine.
- No image versioning: a single mutable `:dev` tag, rollback is "rebuild from an
  older commit".

**Rejected:**
- **A registry (ghcr.io or in-cluster)** — cleaner, enables versioned tags and
  multi-node scheduling, but adds credentials/infrastructure for a single-user app
  that is pinned to one node anyway. Revisit if a second imaged app appears.
- **GitHub Actions CI builds** — free-tier arm64 builds for a private repo mean qemu
  or paid runners, and couple deploys to pushes; overkill for a homelab loop.
- **NFS PV on keel-nas** — would unpin the data, but SQLite over NFS has real
  locking hazards; the keel-cluster docs already reserve NFS for bulk/file data,
  not databases.
