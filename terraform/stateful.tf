# ---------------------------------------------------------------------------
# Cloud SQL -- persistent conversation memory (LangGraph checkpointer)
#
# Optional. Without it, app/agents/graph.py falls back to an in-RAM MemorySaver
# and prints a loud warning that history will be lost on restart.
# ---------------------------------------------------------------------------

resource "google_sql_database_instance" "memory" {
  count = var.enable_sql ? 1 : 0

  name             = "${var.name_prefix}-memory"
  database_version = "POSTGRES_15"
  region           = var.region

  # A demo database should not survive a fat-fingered destroy as a surprise
  # cost. Flip this to true before anything real depends on it.
  deletion_protection = false

  settings {
    tier              = var.db_tier
    availability_type = "ZONAL" # REGIONAL doubles the price
    disk_size         = 10
    disk_autoresize   = true

    ip_configuration {
      # Public IP, reached through the Cloud SQL Auth proxy that Cloud Run
      # mounts as a Unix socket. No VPC connector needed -- see network.tf.
      ipv4_enabled = true
    }

    backup_configuration {
      enabled = false # demo workload; enable for anything real
    }
  }

  depends_on = [google_project_service.enabled]
}

resource "google_sql_database" "memory" {
  count = var.enable_sql ? 1 : 0

  name     = var.db_name
  instance = google_sql_database_instance.memory[0].name
}

resource "google_sql_user" "app" {
  count = var.enable_sql ? 1 : 0

  name     = var.db_user
  instance = google_sql_database_instance.memory[0].name
  password = var.db_password

  lifecycle {
    precondition {
      condition     = var.db_password != ""
      error_message = "db_password must be set when enable_sql is true."
    }
  }
}

# ---------------------------------------------------------------------------
# Memorystore Redis -- semantic cache
#
# Optional and the single most expensive line item. Without it,
# app/services/gcp/redis_semantic_cache.py detects the missing host and turns
# every cache call into a no-op, so the system runs correctly but pays full LLM
# cost on every question.
# ---------------------------------------------------------------------------

resource "google_redis_instance" "cache" {
  count = var.enable_cache ? 1 : 0

  name           = "${var.name_prefix}-cache"
  tier           = "BASIC" # STANDARD_HA roughly doubles the cost
  memory_size_gb = var.redis_memory_gb
  region         = var.region

  authorized_network = google_compute_network.vpc[0].id
  connect_mode       = "DIRECT_PEERING"
  redis_version      = "REDIS_7_0"

  depends_on = [google_project_service.enabled]
}
