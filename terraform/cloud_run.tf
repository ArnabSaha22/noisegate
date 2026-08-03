# ---------------------------------------------------------------------------
# Three Cloud Run services from one shared image repository.
#
# GOTCHA #7, and the reason this file is shaped the way it is:
# Cloud Run services are independent containers. Environment variables do NOT
# propagate between them. Adding a variable to one service does nothing for the
# others -- this has already cost this project a missing Logfire token once.
#
# The defence is the `shared_env` local below: every service merges it, so a new
# shared variable is added in exactly one place and cannot be forgotten for a
# service. Per-service extras are merged on top.
# ---------------------------------------------------------------------------

locals {
  image_base = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.containers.repository_id}"

  redis_host = var.enable_cache ? google_redis_instance.cache[0].host : ""
  redis_port = var.enable_cache ? tostring(google_redis_instance.cache[0].port) : "6379"

  sql_connection_name = var.enable_sql ? google_sql_database_instance.memory[0].connection_name : ""

  # LOCAL_MODE is the app's master switch. In the cloud it is "true" only when
  # BOTH stateful backends are off -- that is precisely the condition under
  # which the app should stop reaching for Cloud SQL and Redis.
  local_mode = (!var.enable_sql && !var.enable_cache) ? "true" : "false"

  shared_env = {
    PROJECT_ID              = var.project_id
    LOCATION                = var.region
    LOCAL_MODE              = local.local_mode
    QDRANT_CLUSTER_ENDPOINT = var.qdrant_url
    QDRANT_API_KEY          = var.qdrant_api_key
    GROQ_API_KEY            = var.groq_api_key
    LOGFIRE_TOKEN           = var.logfire_token
    LANGSMITH_API_KEY       = var.langsmith_api_key
    LANGSMITH_TRACING       = "true"
    LANGSMITH_PROJECT       = var.name_prefix
  }

  backend_env = merge(local.shared_env, {
    REDIS_HOST         = local.redis_host
    REDIS_PORT         = local.redis_port
    DB_NAME            = var.db_name
    DB_USER            = var.db_user
    DB_PASS            = var.db_password
    DB_CONNECTION_NAME = local.sql_connection_name
  })

  ingestion_env = merge(local.shared_env, {
    GCP_RAW_BUCKET          = data.google_storage_bucket.raw.name
    GCP_PROCESSED_BUCKET    = data.google_storage_bucket.processed.name
    GCP_DOC_AI_LOCATION     = var.doc_ai_location
    GCP_DOC_AI_PROCESSOR_ID = var.doc_ai_processor_id
  })
}

# ---------------------------------------------------------------------------
# Backend -- FastAPI + LangGraph agent
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "backend" {
  name                = "${var.name_prefix}-backend"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.backend.email
    timeout         = "300s"

    scaling {
      min_instance_count = 0 # scale to zero: no traffic, no bill
      max_instance_count = 3
    }

    containers {
      image = "${local.image_base}/backend:${var.image_tag}"

      # GOTCHA #10: Cloud Run routes to 8080.
      ports {
        container_port = 8080
      }

      resources {
        limits = {
          # FlashRank loads an ONNX model into memory on first use; 1Gi is too
          # tight once the Vertex client is also resident.
          cpu    = "1"
          memory = "2Gi"
        }
        startup_cpu_boost = true # helps the lazy-loaded models warm up
      }

      dynamic "env" {
        for_each = local.backend_env
        content {
          name  = env.key
          value = env.value
        }
      }
    }

    # Cloud SQL over the built-in proxy socket at /cloudsql/<connection_name>,
    # which is the path app/agents/graph.py builds its DSN around.
    dynamic "volumes" {
      for_each = var.enable_sql ? [1] : []
      content {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.memory[0].connection_name]
        }
      }
    }

    # Only needed to reach Memorystore's private IP.
    dynamic "vpc_access" {
      for_each = local.need_connector ? [1] : []
      content {
        connector = google_vpc_access_connector.serverless[0].id
        egress    = "PRIVATE_RANGES_ONLY"
      }
    }
  }

  depends_on = [google_project_service.enabled]
}

# ---------------------------------------------------------------------------
# Ingestion -- Eventarc webhook + document pipeline
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "ingestion" {
  name                = "${var.name_prefix}-ingestion"
  location            = var.region
  deletion_protection = false

  # Reachable only from inside Google's network. Eventarc can call it; the
  # public internet cannot.
  ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = google_service_account.ingestion.email

    # Document AI on a large PDF is slow, and processing happens in a
    # BackgroundTask after the webhook returns.
    timeout = "900s"

    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }

    containers {
      image = "${local.image_base}/ingestion:${var.image_tag}"

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          # Splitting and parsing large PDFs is memory-hungry.
          cpu    = "2"
          memory = "4Gi"
        }
      }

      dynamic "env" {
        for_each = local.ingestion_env
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  depends_on = [google_project_service.enabled]
}

# ---------------------------------------------------------------------------
# UI -- Streamlit chat
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "ui" {
  name                = "${var.name_prefix}-ui"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.ui.email

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      # GOTCHA #10 again, and this is the service it actually bit: Streamlit
      # defaults to 8501, so its Dockerfile must force --server.port=8080.
      image = "${local.image_base}/ui:${var.image_tag}"

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      env {
        name  = "BACKEND_URL"
        value = google_cloud_run_v2_service.backend.uri
      }

      # The UI needs its own Logfire token -- it will not inherit the backend's.
      env {
        name  = "LOGFIRE_TOKEN"
        value = var.logfire_token
      }
    }
  }

  depends_on = [google_project_service.enabled]
}
