output "ui_url" {
  description = "Public URL of the Streamlit chat interface -- this is the demo link."
  value       = google_cloud_run_v2_service.ui.uri
}

output "backend_url" {
  description = "Backend API URL. Not public: only the UI service account may invoke it."
  value       = google_cloud_run_v2_service.backend.uri
}

output "ingestion_url" {
  description = "Ingestion service URL. Internal ingress only; invoked by Eventarc."
  value       = google_cloud_run_v2_service.ingestion.uri
}

output "image_repository" {
  description = "Artifact Registry path that cloudbuild.yaml pushes to."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.containers.repository_id}"
}

output "sql_connection_name" {
  description = "Cloud SQL connection name (project:region:instance), empty when enable_sql is false."
  value       = var.enable_sql ? google_sql_database_instance.memory[0].connection_name : ""
}

output "redis_host" {
  description = "Memorystore private IP, empty when enable_cache is false."
  value       = var.enable_cache ? google_redis_instance.cache[0].host : ""
}

output "cost_posture" {
  description = "Which always-on billable components this configuration creates."
  value = join(" | ", [
    "cloud_sql=${var.enable_sql ? "ON (~$10/mo)" : "off"}",
    "memorystore=${var.enable_cache ? "ON (~$35-40/mo)" : "off"}",
    "vpc_connector=${local.need_connector ? "ON (~$10-15/mo)" : "off"}",
    "cloud_run=scales-to-zero",
  ])
}

output "app_mode" {
  description = "The LOCAL_MODE value the deployed services will run with."
  value       = local.local_mode == "true" ? "LOCAL_MODE=true (RAM memory, cache disabled)" : "LOCAL_MODE=false (Cloud SQL and/or Redis in use)"
}

output "cloudbuild_service_account" {
  description = "Dedicated Cloud Build identity. Manual builds must pass this explicitly."
  value       = google_service_account.cloudbuild.email
}

output "cloudbuild_submit_command" {
  description = "Ready-to-run image build command, with the correct service account."
  value       = "gcloud builds submit --config cloudbuild.yaml --project=${var.project_id} --service-account=projects/${var.project_id}/serviceAccounts/${google_service_account.cloudbuild.email} --substitutions=_TAG=$(git rev-parse --short HEAD) ."
}
