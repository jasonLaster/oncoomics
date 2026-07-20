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
  default     = 2000
}

variable "batch_root_volume_iops" {
  description = "Provisioned gp3 IOPS for Batch EC2 host root volumes."
  type        = number
  default     = 16000
}

variable "batch_root_volume_throughput" {
  description = "Provisioned gp3 throughput in MB/s for Batch EC2 host root volumes."
  type        = number
  default     = 1000
}

variable "spot_max_vcpus" {
  description = "Maximum vCPUs for the Spot compute environment."
  type        = number
  default     = 128
}

variable "ondemand_max_vcpus" {
  description = "Maximum vCPUs for the On-Demand compute environment."
  type        = number
  default     = 256
}

variable "hrd_x86_max_vcpus" {
  description = "Maximum vCPUs for the zero-idle On-Demand linux/amd64 HRD cross-check compute environment."
  type        = number
  default     = 128
}

variable "gpu_p5en_max_vcpus" {
  description = "Maximum vCPUs for the zero-idle On-Demand P5 Hopper Parabricks compute environment."
  type        = number
  default     = 384
}

variable "enable_gpu_p5en_batch" {
  description = "Create the isolated P5 Hopper Parabricks AWS Batch queue and compute environment in this workspace."
  type        = bool
  default     = false
}

variable "daily_cost_guard_limit_usd" {
  description = "Account-wide daily AWS Budgets limit in USD for the Diana Batch kill switch. Keep at or below 200 USD/day."
  type        = number
  default     = 200

  validation {
    condition     = var.daily_cost_guard_limit_usd > 0 && var.daily_cost_guard_limit_usd <= 200
    error_message = "daily_cost_guard_limit_usd must be greater than 0 and no more than 200."
  }
}

variable "daily_cost_guard_stop_threshold_percent" {
  description = "Actual daily AWS spend percentage that invokes the Diana Batch kill switch before the $200/day hard ceiling."
  type        = number
  default     = 80

  validation {
    condition     = var.daily_cost_guard_stop_threshold_percent > 0 && var.daily_cost_guard_stop_threshold_percent <= 80
    error_message = "daily_cost_guard_stop_threshold_percent must be between 0 and 80."
  }
}

variable "daily_cost_guard_live_stop_threshold_percent" {
  description = "Estimated live Diana Batch EC2 spend percentage that invokes the Diana Batch kill switch before slower non-EC2 costs fill the daily limit."
  type        = number
  default     = 80

  validation {
    condition     = var.daily_cost_guard_live_stop_threshold_percent > 0 && var.daily_cost_guard_live_stop_threshold_percent <= 80
    error_message = "daily_cost_guard_live_stop_threshold_percent must be between 0 and 80."
  }
}

variable "daily_cost_guard_phase3_fast_gpu_smoke_reservation_usd" {
  description = "Conservative same-day USD reserved before the P5 Hopper placement smoke may submit."
  type        = number
  default     = 20

  validation {
    condition     = var.daily_cost_guard_phase3_fast_gpu_smoke_reservation_usd >= 0 && var.daily_cost_guard_phase3_fast_gpu_smoke_reservation_usd <= 200
    error_message = "daily_cost_guard_phase3_fast_gpu_smoke_reservation_usd must be between 0 and 200."
  }
}

variable "daily_cost_guard_phase3_fast_execute_reservation_usd" {
  description = "Conservative same-day USD reserved before the full Diana BAM-to-evidence P5 Hopper run may submit."
  type        = number
  default     = 150

  validation {
    condition     = var.daily_cost_guard_phase3_fast_execute_reservation_usd >= 0 && var.daily_cost_guard_phase3_fast_execute_reservation_usd <= 200
    error_message = "daily_cost_guard_phase3_fast_execute_reservation_usd must be between 0 and 200."
  }
}

variable "daily_cost_guard_email" {
  description = "Optional human email subscriber for daily cost guard notifications. Leave empty to keep only the SNS to Lambda stop path."
  type        = string
  default     = ""
}

variable "daily_cost_guard_schedule_expression" {
  description = "EventBridge schedule for the live Diana Batch EC2 spend estimator."
  type        = string
  default     = "rate(1 minute)"
}

variable "daily_cost_guard_regions" {
  description = "AWS regions included in the account-wide live Diana Batch EC2 spend estimator."
  type        = list(string)
  default     = ["us-east-1", "us-east-2", "us-west-2"]

  validation {
    condition = (
      length(var.daily_cost_guard_regions) > 0 &&
      length(var.daily_cost_guard_regions) == length(distinct(var.daily_cost_guard_regions)) &&
      alltrue([
        for region in var.daily_cost_guard_regions :
        can(regex("^[a-z]{2}-[a-z]+-[0-9]+$", region))
      ])
    )
    error_message = "daily_cost_guard_regions must be a non-empty list of distinct AWS region names."
  }
}

variable "daily_cost_guard_instance_hourly_rates_usd" {
  description = "Conservative hourly USD rates used by the near-real-time Diana Batch EC2 spend estimator."
  type        = map(number)
  default = {
    c7g             = 10
    c7gn            = 10
    c7i             = 12
    m7g             = 10
    m7i             = 12
    "p5.48xlarge"   = 140
    "p5e.48xlarge"  = 140
    "p5en.48xlarge" = 140
    r7g             = 10
    r7i             = 12
  }
}

variable "daily_cost_guard_unknown_instance_hourly_rate_usd" {
  description = "Fallback hourly USD rate for any tagged Diana Batch EC2 type not listed in daily_cost_guard_instance_hourly_rates_usd."
  type        = number
  default     = 140
}

variable "batch_arm_instance_families" {
  description = "ARM64 EC2 instance families for Batch. The local OrbStack image build is arm64."
  type        = list(string)
  default     = ["c7gn", "c7g", "m7g", "r7g"]
}

variable "batch_x86_instance_families" {
  description = "Linux/amd64 EC2 instance families for private HRD cross-check Batch jobs."
  type        = list(string)
  default     = ["c7i", "m7i", "r7i"]
}

variable "batch_gpu_p5en_instance_types" {
  description = "GPU EC2 instance types for the isolated Parabricks AWS Batch environment."
  type        = list(string)
  default     = ["p5en.48xlarge", "p5e.48xlarge", "p5.48xlarge"]
}

variable "parabricks_container" {
  description = "Pinned linux/amd64 NVIDIA Parabricks image URI for GPU Batch jobs. Leave empty until the smoke image is selected."
  type        = string
  default     = ""
}

variable "enable_parabricks_mirror" {
  description = "Create a regional immutable ECR repository for mirroring the pinned Parabricks image."
  type        = bool
  default     = false
}

variable "phase3_fast_source_region" {
  description = "AWS region that holds immutable source objects for phase3_wgs_fast regional cache replication."
  type        = string
  default     = "us-east-1"
}

variable "phase3_fast_source_environment" {
  description = "Environment name whose KMS alias can decrypt KMS-encrypted source objects for phase3_wgs_fast cache replication."
  type        = string
  default     = "prod-use1"
}

variable "nextflow_params_filename" {
  description = "Local generated Nextflow params filename under infra/aws."
  type        = string
  default     = "nextflow.aws.json"

  validation {
    condition     = basename(var.nextflow_params_filename) == var.nextflow_params_filename && endswith(var.nextflow_params_filename, ".json")
    error_message = "nextflow_params_filename must be a JSON filename without path separators."
  }
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

variable "manage_service_linked_roles" {
  description = "Whether this workspace should create account-global AWS Batch and EC2 Spot service-linked roles."
  type        = bool
  default     = true
}
