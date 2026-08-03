# ---------------------------------------------------------------------------
# One service account per service, with only the roles that service needs.
#
# A single shared account would be simpler, but it would also mean the public
# Streamlit UI carried permission to read GCS and call Document AI -- neither of
# which it ever does. Splitting them keeps the blast radius of a compromised
# frontend to "can call the backend".
# ---------------------------------------------------------------------------

resource "google_service_account" "backend" {
  account_id   = "${var.name_prefix}-backend"
  display_name = "NoiseGate backend (LangGraph agent)"
}

resource "google_service_account" "ingestion" {
  account_id   = "${var.name_prefix}-ingestion"
  display_name = "NoiseGate ingestion (document processing)"
}

resource "google_service_account" "ui" {
  account_id   = "${var.name_prefix}-ui"
  display_name = "NoiseGate Streamlit UI"
}

resource "google_service_account" "eventarc" {
  account_id   = "${var.name_prefix}-eventarc"
  display_name = "NoiseGate Eventarc trigger invoker"
}

# --- Backend: embeds queries via Vertex, and reaches Cloud SQL when enabled ---

resource "google_project_iam_member" "backend_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_project_iam_member" "backend_sql" {
  count = var.enable_sql ? 1 : 0

  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

# --- Ingestion: reads raw documents, writes extracted JSON, parses PDFs -------

resource "google_project_iam_member" "ingestion_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.ingestion.email}"
}

resource "google_project_iam_member" "ingestion_docai" {
  project = var.project_id
  role    = "roles/documentai.apiUser"
  member  = "serviceAccount:${google_service_account.ingestion.email}"
}

# Bucket-scoped rather than project-wide storage access: read the raw bucket,
# write the processed one. Deliberately NOT objectAdmin on raw -- ingestion has
# no business modifying source documents.
resource "google_storage_bucket_iam_member" "ingestion_raw_read" {
  bucket = data.google_storage_bucket.raw.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.ingestion.email}"
}

resource "google_storage_bucket_iam_member" "ingestion_processed_write" {
  bucket = data.google_storage_bucket.processed.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.ingestion.email}"
}

# --- Service-to-service invocation -------------------------------------------

# The UI is the only thing allowed to call the backend.
resource "google_cloud_run_v2_service_iam_member" "ui_invokes_backend" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.ui.email}"
}

# Eventarc is the only thing allowed to call ingestion. Note there is no
# allUsers binding anywhere here: ingestion is never publicly reachable.
resource "google_cloud_run_v2_service_iam_member" "eventarc_invokes_ingestion" {
  count = var.enable_ingestion_trigger ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.ingestion.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.eventarc.email}"
}

resource "google_project_iam_member" "eventarc_receiver" {
  count = var.enable_ingestion_trigger ? 1 : 0

  project = var.project_id
  role    = "roles/eventarc.eventReceiver"
  member  = "serviceAccount:${google_service_account.eventarc.email}"
}

# Creating the trigger fails without this, with a 403 that is easy to
# misread as a missing bucket:
#
#   Permission "storage.buckets.get" denied on "Bucket "noisegate-rag-raw"
#   could not be validated. Please verify that the bucket exists and that the
#   Eventarc service account has permission."
#
# The bucket exists. Eventarc reads the bucket's METADATA to validate the
# trigger at creation time, and eventReceiver alone does not grant that.
# legacyBucketReader is the narrowest predefined role containing
# storage.buckets.get -- it conveys no ability to read object CONTENTS, so the
# trigger identity still cannot see the documents themselves.
resource "google_storage_bucket_iam_member" "eventarc_bucket_read" {
  count = var.enable_ingestion_trigger ? 1 : 0

  bucket = data.google_storage_bucket.raw.name
  role   = "roles/storage.legacyBucketReader"
  member = "serviceAccount:${google_service_account.eventarc.email}"
}

# GCS publishes Eventarc events through Pub/Sub using the Cloud Storage service
# agent, which needs explicit permission to publish.
data "google_storage_project_service_account" "gcs" {}

resource "google_project_iam_member" "gcs_pubsub_publisher" {
  count = var.enable_ingestion_trigger ? 1 : 0

  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
}

# The UI is the public entry point -- the only intentionally open service.
resource "google_cloud_run_v2_service_iam_member" "ui_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.ui.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
