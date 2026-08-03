terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # State is local by default. For a shared/team setup, uncomment and point at a
  # GCS bucket -- but note the chicken-and-egg: the bucket must exist before
  # Terraform can store state in it, so create it by hand or on a first local run.
  #
  # backend "gcs" {
  #   bucket = "noisegate-tfstate"
  #   prefix = "terraform/state"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
