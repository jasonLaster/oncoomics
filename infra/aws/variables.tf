variable "region" {
  description = "AWS region for the Diana Omics Batch stack."
  type        = string
  default     = "us-west-1"
}

variable "project" {
  description = "Short project name used in AWS resource names."
  type        = string
  default     = "diana-omics"
}

variable "environment" {
  description = "Environment name used in AWS resource names."
  type        = string
  default     = "prod"
}

variable "image_tag" {
  description = "Immutable ECR image tag that Nextflow should run."
  type        = string
  default     = "dev"
}

variable "batch_root_volume_gb" {
  description = "Encrypted gp3 root volume size for Batch EC2 hosts."
  type        = number
  default     = 500
}

variable "spot_max_vcpus" {
  description = "Maximum vCPUs for the Spot compute environment."
  type        = number
  default     = 64
}

variable "ondemand_max_vcpus" {
  description = "Maximum vCPUs for the On-Demand compute environment."
  type        = number
  default     = 64
}

variable "batch_arm_instance_families" {
  description = "ARM64 EC2 instance families for Batch. The local OrbStack image build is arm64."
  type        = list(string)
  default     = ["c7g", "m7g", "r7g"]
}

variable "work_bucket_lifecycle_days" {
  description = "Days before expiring disposable Nextflow work objects."
  type        = number
  default     = 14
}

variable "raw_bucket_noncurrent_days" {
  description = "Days before expiring noncurrent object versions in the future raw-inputs bucket."
  type        = number
  default     = 90
}

variable "bootstrap_iam_user_name" {
  description = "Optional IAM user to receive temporary ECR/Batch bootstrap permissions. Set to empty to disable."
  type        = string
  default     = "local-cli"
}
