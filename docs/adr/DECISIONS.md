# Architecture Decision Records — FPL Assistant

Decisions specific to the FPL assistant. Cluster/infrastructure decisions live in the
separate `keel-cluster` repo.

---

## Index

| ADR  | Title | Status |
|------|-------|--------|
| 0001 | Haaland Watch Runs as a k3s CronJob (No Custom Image) | Accepted |

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
