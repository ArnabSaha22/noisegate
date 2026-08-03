# ---------------------------------------------------------------------------
# Buckets: ADOPTED, NOT MANAGED
#
# noisegate-rag-raw and noisegate-rag-processed already exist and hold the real
# corpus (55 and 54 objects respectively). Declaring them as `resource` blocks
# would make Terraform try to create them -- and, far worse, would put them in
# the destroy path, so a `terraform destroy` could delete the source documents.
#
# Using data sources instead means Terraform can REFERENCE them (for the
# Eventarc trigger and IAM) while being structurally incapable of touching them.
# The safety comes from the type of block, not from remembering to be careful.
# ---------------------------------------------------------------------------

data "google_storage_bucket" "raw" {
  name = var.raw_bucket
}

data "google_storage_bucket" "processed" {
  name = var.processed_bucket
}

# The two buckets must never be the same. If ingestion wrote its output back
# into the bucket Eventarc watches, that write would retrigger ingestion, which
# would write again -- an infinite loop billed per invocation.
# This makes that mistake fail at plan time rather than at 3am.
resource "terraform_data" "bucket_isolation_guard" {
  lifecycle {
    precondition {
      condition     = var.raw_bucket != var.processed_bucket
      error_message = "raw_bucket and processed_bucket must differ, or Eventarc will loop forever."
    }
  }
}

# ---------------------------------------------------------------------------
# Artifact Registry
#
# Chicken-and-egg warning: images must exist here before Cloud Run can deploy
# them, but this repo is itself created by Terraform. On a first run, apply this
# target alone, push images, then apply the rest:
#
#   terraform apply -target=google_artifact_registry_repository.containers
#   gcloud builds submit --config cloudbuild.yaml .
#   terraform apply
# ---------------------------------------------------------------------------

resource "google_artifact_registry_repository" "containers" {
  location      = var.region
  repository_id = "${var.name_prefix}-containers"
  description   = "Container images for the ${var.name_prefix} services"
  format        = "DOCKER"

  depends_on = [google_project_service.enabled]
}
