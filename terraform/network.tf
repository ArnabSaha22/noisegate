# ---------------------------------------------------------------------------
# Private networking -- created ONLY when the cache is enabled.
#
# A design note worth understanding, because it saves real money:
#
#   Memorystore Redis has a PRIVATE IP only. Cloud Run is serverless and lives
#   outside your VPC, so it needs a Serverless VPC Access connector to reach it.
#   That connector runs on always-on instances and bills ~$10-15/month.
#
#   Cloud SQL does NOT need the connector. Cloud Run v2 can mount a Cloud SQL
#   instance as a Unix socket at /cloudsql/<connection_name> using the built-in
#   proxy -- which is exactly the path app/agents/graph.py already builds its
#   connection string around.
#
# So the connector is tied to enable_cache alone, not to enable_sql. Turning the
# cache off removes both the Redis bill and the connector bill.
# ---------------------------------------------------------------------------

locals {
  need_connector = var.enable_cache
}

resource "google_compute_network" "vpc" {
  count = local.need_connector ? 1 : 0

  name                    = "${var.name_prefix}-vpc"
  auto_create_subnetworks = false

  depends_on = [google_project_service.enabled]
}

resource "google_compute_subnetwork" "connector" {
  count = local.need_connector ? 1 : 0

  name          = "${var.name_prefix}-connector-subnet"
  region        = var.region
  network       = google_compute_network.vpc[0].id
  ip_cidr_range = "10.8.0.0/28" # /28 is the required size for a VPC connector
}

resource "google_vpc_access_connector" "serverless" {
  count = local.need_connector ? 1 : 0

  name   = "${var.name_prefix}-vpc"
  region = var.region

  subnet {
    name = google_compute_subnetwork.connector[0].name
  }

  # Smallest supported machines and instance count -- this is a demo, not a
  # high-throughput system, and these instances bill continuously.
  machine_type  = "e2-micro"
  min_instances = 2
  max_instances = 3

  depends_on = [google_project_service.enabled]
}

# Gotcha #9, encoded: tearing down direct VPC egress can leave an orphaned
# address reservation that outlives the service and blocks destroying the
# network. If `terraform destroy` hangs on the VPC, check for a leftover
# reservation under VPC network -> IP addresses and release it by hand.
