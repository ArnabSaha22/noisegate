# ---------------------------------------------------------------------------
# Eventarc: a new object in the RAW bucket triggers the ingestion service.
#
# GOTCHA #4 lives here. This trigger watches the raw bucket only. The ingestion
# service must never write back into that bucket, or its own write would fire
# this trigger, which would write again -- an unbounded loop billed per
# invocation. Two independent guards enforce that:
#
#   1. Infrastructure: only the raw bucket is watched. Processed JSON goes to a
#      different bucket that has no trigger attached.
#   2. Application: event-driven calls pass skip_raw_upload=True, and the
#      webhook rejects events whose bucket is not the configured raw bucket.
#
# The bucket_isolation_guard precondition in storage.tf fails the plan outright
# if the two bucket names are ever set to the same value.
# ---------------------------------------------------------------------------

resource "google_eventarc_trigger" "raw_upload" {
  count = var.enable_ingestion_trigger ? 1 : 0

  name     = "${var.name_prefix}-raw-upload"
  location = var.region

  matching_criteria {
    attribute = "type"
    value     = "google.cloud.storage.object.v1.finalized"
  }

  matching_criteria {
    attribute = "bucket"
    value     = data.google_storage_bucket.raw.name
  }

  destination {
    cloud_run_service {
      service = google_cloud_run_v2_service.ingestion.name
      region  = var.region
      path    = "/" # app/ingestion/processor.py handles POST /
    }
  }

  service_account = google_service_account.eventarc.email

  depends_on = [
    google_project_service.enabled,
    google_project_iam_member.eventarc_receiver,
    google_storage_bucket_iam_member.eventarc_bucket_read,
    google_project_iam_member.gcs_pubsub_publisher,
    google_cloud_run_v2_service_iam_member.eventarc_invokes_ingestion,
  ]
}
