# Infrastructure

Terraform definitions for deploying NoiseGate to Google Cloud: three Cloud Run
services, event-driven ingestion, and optional managed state.

Written independently against the Google provider documentation. The resource
inventory is dictated by the architecture in `CLAUDE.md`, not copied from any
other implementation.

---

## The cost model, which drives the whole design

Cloud Run scales to zero: no traffic, no bill. Cloud SQL, Memorystore, and the
Serverless VPC connector bill continuously whether or not anyone uses them, and
together they dominate the monthly cost.

The application already degrades gracefully without either backend:

| Missing | Behaviour |
|---|---|
| Redis | `redis_semantic_cache.py` turns every cache call into a no-op |
| Cloud SQL | `graph.py` falls back to in-RAM `MemorySaver` and warns loudly |

So the infrastructure honours the same contract. Both are **off by default**:

```
enable_sql   = false    # ~$10/mo when on
enable_cache = false    # ~$35-40/mo when on, plus ~$10-15 for the VPC connector
```

A default `terraform apply` gives a fully working, publicly reachable deployment
for roughly **$0/month idle**. Turn the toggles on to demonstrate the full
production topology, then turn them back off.

`terraform output cost_posture` reports which billable components are active.

Note that the VPC connector is tied to `enable_cache` alone. Cloud SQL is reached
through the Cloud Run built-in proxy socket at `/cloudsql/<connection_name>` —
exactly the path `graph.py` builds its connection string around — so enabling
Postgres does not require the connector.

---

## First deployment

There is a chicken-and-egg problem: Cloud Run needs images, images need a
registry, and Terraform creates the registry. So the first run is three steps.

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # then fill it in
terraform init

# 1. Create the image repository (and enable the APIs) first
terraform apply -target=google_artifact_registry_repository.containers

# 2. Build and push all three images (runs on Google's builders; no local Docker)
cd .. && gcloud builds submit --config cloudbuild.yaml .

# 3. Deploy everything else
cd terraform && terraform apply
```

Then open the demo:

```bash
terraform output ui_url
```

Subsequent deploys are just steps 2 and 3.

---

## What gets created

| Resource | Notes |
|---|---|
| Cloud Run × 3 | backend, ui, ingestion — each with its own service account |
| Artifact Registry | one Docker repo for all three images |
| Eventarc trigger | raw bucket object-finalized → ingestion `POST /` |
| Service accounts × 4 | three services plus the Eventarc invoker |
| Cloud SQL | only when `enable_sql = true` |
| Memorystore + VPC | only when `enable_cache = true` |

**Not created:** the two GCS buckets. They already exist and hold the real
corpus, so they are adopted as `data` sources. Terraform can reference them but
is structurally unable to modify or destroy them — the safety comes from the
block type, not from remembering to be careful.

---

## Access model

| Service | Ingress | Who may invoke |
|---|---|---|
| ui | public | `allUsers` — the demo link |
| backend | public endpoint | UI service account only |
| ingestion | internal only | Eventarc service account only |

Each service holds only the roles it uses. The UI cannot read GCS or call
Document AI, so a compromised frontend gains nothing beyond calling the backend.

---

## Gotchas encoded here

These come from `CLAUDE.md §6` and are enforced in the configuration rather than
left to memory:

- **#4 — Eventarc loop.** Only the raw bucket is watched; processed output goes
  to a different, untriggered bucket. A `precondition` in `storage.tf` fails the
  plan if the two bucket names ever match.
- **#7 — Per-service env vars.** Cloud Run containers are independent and share
  nothing. `cloud_run.tf` defines a single `shared_env` local that every service
  merges, so a new variable cannot be added to one service and forgotten on
  another.
- **#9 — Zombie IP.** If `terraform destroy` stalls on the VPC, an orphaned
  address reservation is holding it. Release it under VPC network → IP addresses.
- **#10 — Port 8080.** Every Dockerfile binds 8080 explicitly. The UI is the one
  that actually bites, since Streamlit defaults to 8501.

---

## Tearing down

```bash
terraform destroy
```

The buckets and their contents survive, by design. If the VPC refuses to delete,
see gotcha #9 above.

---

## Known next steps

- **Secrets belong in Secret Manager.** API keys are currently passed as plain
  environment variables, which means they are visible to anyone with
  `run.services.get`. Moving them to Secret Manager references is the right
  production fix and is deliberately left as a follow-up rather than pretended
  to be done.
- **Remote state.** State is local. A GCS backend is stubbed out in
  `versions.tf` for when more than one machine needs to apply.
- **No Cloud Build trigger.** Builds are manual (`gcloud builds submit`).
  Wiring a push trigger is straightforward once the repo has a stable branch.
