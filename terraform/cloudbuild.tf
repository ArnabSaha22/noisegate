# ---------------------------------------------------------------------------
# A dedicated identity for Cloud Build.
#
# WHY THIS EXISTS -- a gotcha that costs everyone the same hour:
#
# On projects created after roughly 2024, Google no longer auto-grants the
# legacy Cloud Build service account its old permissions, and manual builds
# default to the COMPUTE ENGINE default service account, which has none of the
# roles a build needs. `gcloud builds submit` then fails with a 403 that names a
# storage object -- which reads like a bucket problem but is really an identity
# problem:
#
#   ERROR: could not resolve source: Error 403:
#   <n>-compute@developer.gserviceaccount.com does not have
#   storage.objects.get access to .../<project>_cloudbuild/objects/source/...
#
# Granting roles to the compute default SA would fix it, but that account is
# attached to anything else in the project that lacks an explicit identity, so
# every role given to it leaks broadly. A dedicated build account keeps the
# permissions where they belong.
#
# Use it explicitly when submitting:
#
#   gcloud builds submit --config cloudbuild.yaml \
#     --service-account=projects/<PROJECT>/serviceAccounts/<EMAIL> .
#
# `terraform output cloudbuild_submit_command` prints the full command.
# ---------------------------------------------------------------------------

resource "google_service_account" "cloudbuild" {
  account_id   = "${var.name_prefix}-cloudbuild"
  display_name = "NoiseGate Cloud Build runner"
}

# Push the three images to Artifact Registry.
resource "google_project_iam_member" "cloudbuild_artifacts" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.cloudbuild.email}"
}

# Required because cloudbuild.yaml sets logging: CLOUD_LOGGING_ONLY. A custom
# service account may not write build logs to GCS, so Cloud Logging is the only
# option -- and without this role the build fails before it starts.
resource "google_project_iam_member" "cloudbuild_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.cloudbuild.email}"
}

# Read the uploaded source tarball. Scoped to the bucket gcloud stages sources
# in, rather than granting project-wide object read -- which would also expose
# the document corpus in the raw and processed buckets.
#
# Referenced by name rather than via a data source: the bucket is created
# on-demand by `gcloud builds submit`, so a data source would fail to plan
# before the first upload.
resource "google_storage_bucket_iam_member" "cloudbuild_source" {
  bucket = "${var.project_id}_cloudbuild"
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.cloudbuild.email}"
}
