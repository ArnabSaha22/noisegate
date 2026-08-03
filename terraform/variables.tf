# ---------------------------------------------------------------------------
# Core project settings
# ---------------------------------------------------------------------------

variable "project_id" {
  description = "GCP project ID to deploy into."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Cloud SQL, Memorystore and the VPC connector."
  type        = string
  default     = "us-central1"
}

variable "name_prefix" {
  description = "Prefix applied to every created resource, so multiple environments can coexist."
  type        = string
  default     = "noisegate"
}

# ---------------------------------------------------------------------------
# COST TOGGLES
#
# Cloud Run scales to zero and costs ~nothing idle. Cloud SQL, Memorystore and
# the Serverless VPC connector bill 24/7 whether traffic arrives or not, and
# together they dominate the monthly bill.
#
# The application degrades gracefully without them:
#   - no Redis     -> app/services/gcp/redis_semantic_cache.py becomes a no-op
#   - no Cloud SQL -> app/agents/graph.py falls back to in-RAM MemorySaver
#
# So both default to OFF. You get a fully working deployment for roughly $0/month
# idle, and opt into the full production topology only while you need it.
# ---------------------------------------------------------------------------

variable "enable_cache" {
  description = "Create Memorystore Redis for the semantic cache. Adds roughly $35-40/month."
  type        = bool
  default     = false
}

variable "enable_sql" {
  description = "Create Cloud SQL Postgres for persistent conversation memory. Adds roughly $10/month."
  type        = bool
  default     = false
}

variable "enable_ingestion_trigger" {
  description = "Create the Eventarc trigger so uploads to the raw bucket auto-ingest."
  type        = bool
  default     = true
}

# ---------------------------------------------------------------------------
# Buckets
#
# These already exist in the project and hold real data, so they are adopted as
# data sources rather than managed resources. Terraform will never create,
# modify, or -- crucially -- destroy them. See storage.tf.
# ---------------------------------------------------------------------------

variable "raw_bucket" {
  description = "Existing GCS bucket holding original uploaded documents."
  type        = string
  default     = "noisegate-rag-raw"
}

variable "processed_bucket" {
  description = "Existing GCS bucket holding extracted text as JSON. MUST differ from raw_bucket."
  type        = string
  default     = "noisegate-rag-processed"
}

# ---------------------------------------------------------------------------
# Application configuration
# ---------------------------------------------------------------------------

variable "image_tag" {
  description = "Container image tag to deploy. Prefer a git SHA over 'latest' so rollbacks are possible."
  type        = string
  default     = "latest"
}

variable "qdrant_url" {
  description = "Qdrant cluster endpoint, including :6333."
  type        = string
}

variable "doc_ai_location" {
  description = "Document AI processor location. Note this is a broad multi-region ('us'/'eu'), not a normal region."
  type        = string
  default     = "us"
}

variable "doc_ai_processor_id" {
  description = "Document AI processor ID used for PDF parsing."
  type        = string
  default     = ""
}

variable "db_name" {
  description = "Postgres database name for the LangGraph checkpointer."
  type        = string
  default     = "rag_memory"
}

variable "db_user" {
  description = "Postgres user for the LangGraph checkpointer."
  type        = string
  default     = "rag_admin"
}

variable "db_tier" {
  description = "Cloud SQL machine tier. db-f1-micro is the cheapest option suitable for a demo."
  type        = string
  default     = "db-f1-micro"
}

variable "redis_memory_gb" {
  description = "Memorystore size in GB. 1 is the minimum."
  type        = number
  default     = 1
}

# ---------------------------------------------------------------------------
# Secrets
#
# Marked sensitive so Terraform never prints them. They are supplied through a
# gitignored *.tfvars file or TF_VAR_ environment variables -- never committed.
#
# A stronger production pattern is Secret Manager with the Cloud Run service
# reading secret references instead of plaintext env vars; that is noted in the
# terraform README as a deliberate next step.
# ---------------------------------------------------------------------------

variable "qdrant_api_key" {
  description = "Qdrant API key."
  type        = string
  sensitive   = true
}

variable "groq_api_key" {
  description = "Groq API key for Llama 3.3."
  type        = string
  sensitive   = true
}

variable "db_password" {
  description = "Password for the Postgres user. Ignored when enable_sql is false."
  type        = string
  sensitive   = true
  default     = ""
}

variable "logfire_token" {
  description = "Logfire write token for system tracing."
  type        = string
  sensitive   = true
  default     = ""
}

variable "langsmith_api_key" {
  description = "LangSmith API key for agent tracing."
  type        = string
  sensitive   = true
  default     = ""
}
