# Enable every Google API the stack needs.
#
# Three of these (redis, vpcaccess, eventarc) are currently NOT enabled on the
# project -- gcloud refuses to even list those resource types. Declaring them
# here means a fresh `terraform apply` works on a clean project without anyone
# clicking through the console first.
#
# disable_on_destroy = false is deliberate: turning an API off during a destroy
# can break unrelated resources that happen to share the project.

locals {
  required_apis = [
    "run.googleapis.com",               # Cloud Run services
    "artifactregistry.googleapis.com",  # container image storage
    "cloudbuild.googleapis.com",        # CI builds
    "eventarc.googleapis.com",          # GCS -> ingestion trigger
    "sqladmin.googleapis.com",          # Cloud SQL
    "redis.googleapis.com",             # Memorystore
    "vpcaccess.googleapis.com",         # Serverless VPC connector
    "compute.googleapis.com",           # VPC network backing the connector
    "servicenetworking.googleapis.com", # private services access for Cloud SQL
    "aiplatform.googleapis.com",        # Vertex AI embeddings
    "documentai.googleapis.com",        # PDF parsing
    "storage.googleapis.com",           # GCS
    "iam.googleapis.com",
  ]
}

resource "google_project_service" "enabled" {
  for_each = toset(local.required_apis)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
