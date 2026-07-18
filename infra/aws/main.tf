data "aws_caller_identity" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name_prefix = "${var.project}-${var.environment}"
  azs         = slice(data.aws_availability_zones.available.names, 0, 2)

  bucket_names = {
    work            = "${var.project}-work-${data.aws_caller_identity.current.account_id}-${var.region}"
    results         = "${var.project}-results-${data.aws_caller_identity.current.account_id}-${var.region}"
    private_results = "${var.project}-private-results-${data.aws_caller_identity.current.account_id}-${var.region}"
    raw             = "${var.project}-raw-inputs-${data.aws_caller_identity.current.account_id}-${var.region}"
  }

  tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
    Repository  = "diana-omics"
  }

  diana_raw_inbox_prefix = "diana/inbox"
  phase3_fast_source_bucket_names = toset([
    "${var.project}-private-results-${data.aws_caller_identity.current.account_id}-${var.phase3_fast_source_region}",
    "${var.project}-raw-inputs-${data.aws_caller_identity.current.account_id}-${var.phase3_fast_source_region}",
  ])
  phase3_fast_source_bucket_arns = [
    for bucket in local.phase3_fast_source_bucket_names : "arn:aws:s3:::${bucket}"
  ]
  phase3_fast_source_kms_aliases = [
    "alias/${var.project}-${var.phase3_fast_source_environment}"
  ]
  batch_service_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-service-role/batch.amazonaws.com/AWSServiceRoleForBatch"

  # Public access is opt-in per reviewed validation or alias-only analysis run.
  # Never grant bucket listing, version listing, historical-version reads, or a
  # wildcard object read on the results bucket. Raw inputs, BAMs, and direct
  # identifiers remain outside these prefixes.
  public_results_prefixes = [
    "public-index",
    "runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z",
    "runs/known_answer_bounded_non_dry",
    "runs/known_answer_expanded_cohort",
    "runs/known_answer_public_findings",
    "runs/phase3_fastpath_forcealign_minimap2_scatter8_normal_shardmanifest_20260614T2117Z",
    "runs/phase3_fastpath_forcealign_minimap2_scatter8_tumor_shardmanifest_20260614T2040Z",
    "runs/phase3_sra_benchmark",
    "runs/phase3_wgs",
    "runs/phase3_wgs_scatter",
    "runs/rosalind_hrd/cloud-colo829-guardrail-20260617",
    "runs/rosalind_hrd/cloud-hcc1395-wes-20260617",
    "runs/rosalind_hrd/cloud-helper-selective5-20260617",
    "runs/rosalind_hrd/cloud-hg008-depth-20260617",
    "runs/rosalind_hrd/cloud-selective5-20260617",
  ]
}

data "aws_iam_policy_document" "kms_main" {
  statement {
    sid    = "EnableAccountKmsAdministration"
    effect = "Allow"
    actions = [
      "kms:*"
    ]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

}

data "aws_iam_policy_document" "bootstrap_local_cli" {
  count = var.bootstrap_iam_user_name == "" ? 0 : 1

  statement {
    sid    = "BatchEcrCloudWatchBootstrap"
    effect = "Allow"
    actions = [
      "batch:*",
      "ecr:*",
      "ec2:DescribeInstances",
      "ecs:DescribeClusters",
      "ecs:DescribeContainerInstances",
      "ecs:DescribeTasks",
      "ecs:ListContainerInstances",
      "ecs:ListTasks",
      "kms:*",
      "logs:*",
      "servicequotas:GetRequestedServiceQuotaChange",
      "servicequotas:GetServiceQuota",
      "servicequotas:ListRequestedServiceQuotaChangeHistory",
      "servicequotas:ListRequestedServiceQuotaChangeHistoryByQuota",
      "servicequotas:ListServiceQuotas",
      "servicequotas:RequestServiceQuotaIncrease",
      "ssm:CancelCommand",
      "ssm:GetCommandInvocation",
      "ssm:ListCommandInvocations",
      "ssm:SendCommand",
      "iam:PassRole"
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "bootstrap_local_cli" {
  count = var.bootstrap_iam_user_name == "" ? 0 : 1

  name        = "${local.name_prefix}-bootstrap-batch-ecr"
  description = "Temporary bootstrap permissions for Diana Omics ${var.environment} Batch and ECR provisioning"
  policy      = data.aws_iam_policy_document.bootstrap_local_cli[0].json
}

resource "aws_iam_user_policy_attachment" "bootstrap_local_cli" {
  count = var.bootstrap_iam_user_name == "" ? 0 : 1

  user       = var.bootstrap_iam_user_name
  policy_arn = aws_iam_policy.bootstrap_local_cli[0].arn
}

resource "aws_kms_key" "main" {
  description             = "Diana Omics ${var.environment} S3 and Batch encryption key"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.kms_main.json
}

resource "aws_kms_alias" "main" {
  name          = "alias/${local.name_prefix}"
  target_key_id = aws_kms_key.main.key_id
}

resource "aws_vpc" "main" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-igw"
  }
}

resource "aws_subnet" "public" {
  for_each = { for index, az in local.azs : az => index }

  vpc_id                  = aws_vpc.main.id
  availability_zone       = each.key
  cidr_block              = cidrsubnet(aws_vpc.main.cidr_block, 8, each.value)
  map_public_ip_on_launch = true

  tags = {
    Name = "${local.name_prefix}-public-${each.key}"
    Tier = "public"
  }
}

resource "aws_subnet" "private" {
  for_each = { for index, az in local.azs : az => index }

  vpc_id            = aws_vpc.main.id
  availability_zone = each.key
  cidr_block        = cidrsubnet(aws_vpc.main.cidr_block, 4, each.value + 1)

  tags = {
    Name = "${local.name_prefix}-private-${each.key}"
    Tier = "private"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${local.name_prefix}-public"
  }
}

resource "aws_route_table_association" "public" {
  for_each = aws_subnet.public

  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

resource "aws_eip" "nat" {
  domain = "vpc"

  depends_on = [aws_internet_gateway.main]

  tags = {
    Name = "${local.name_prefix}-nat"
  }
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = values(aws_subnet.public)[0].id

  tags = {
    Name = "${local.name_prefix}-nat"
  }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }

  tags = {
    Name = "${local.name_prefix}-private"
  }
}

resource "aws_route_table_association" "private" {
  for_each = aws_subnet.private

  subnet_id      = each.value.id
  route_table_id = aws_route_table.private.id
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = {
    Name = "${local.name_prefix}-s3"
  }
}

resource "aws_security_group" "batch" {
  name        = "${local.name_prefix}-batch"
  description = "Diana Omics Batch compute hosts; no inbound access"
  vpc_id      = aws_vpc.main.id

  egress {
    description = "Outbound HTTPS and public data downloads"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-batch"
  }
}

resource "aws_s3_bucket" "this" {
  for_each = local.bucket_names

  bucket = each.value
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = aws_s3_bucket.this

  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = contains(["raw", "results"], each.key) ? false : true
  ignore_public_acls      = true
  restrict_public_buckets = contains(["raw", "results"], each.key) ? false : true
}

resource "aws_s3_bucket_ownership_controls" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_cors_configuration" "raw_public_read" {
  bucket = aws_s3_bucket.this["raw"].id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = ["*"]
    expose_headers  = ["ETag", "Content-Length", "Last-Modified"]
    max_age_seconds = 3600
  }
}

resource "aws_s3_bucket_cors_configuration" "results_public_read" {
  bucket = aws_s3_bucket.this["results"].id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = ["*"]
    expose_headers  = ["ETag", "Content-Length", "Last-Modified"]
    max_age_seconds = 3600
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = contains(["raw", "results"], each.key) ? null : aws_kms_key.main.arn
      sse_algorithm     = contains(["raw", "results"], each.key) ? "AES256" : "aws:kms"
    }
  }
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  versioning_configuration {
    status = each.key == "work" ? "Suspended" : "Enabled"
  }
}

data "aws_iam_policy_document" "s3_tls" {
  for_each = aws_s3_bucket.this

  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"
    actions = [
      "s3:*"
    ]
    resources = [
      each.value.arn,
      "${each.value.arn}/*"
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  dynamic "statement" {
    for_each = each.key == "raw" ? [1] : []

    content {
      sid     = "AllowPublicListDianaInbox"
      effect  = "Allow"
      actions = ["s3:ListBucket"]
      resources = [
        each.value.arn
      ]
      principals {
        type        = "*"
        identifiers = ["*"]
      }
      condition {
        test     = "StringLike"
        variable = "s3:prefix"
        values = [
          local.diana_raw_inbox_prefix,
          "${local.diana_raw_inbox_prefix}/",
          "${local.diana_raw_inbox_prefix}/*"
        ]
      }
    }
  }

  dynamic "statement" {
    for_each = each.key == "raw" ? [1] : []

    content {
      sid     = "AllowPublicReadDianaInbox"
      effect  = "Allow"
      actions = ["s3:GetObject"]
      resources = [
        "${each.value.arn}/${local.diana_raw_inbox_prefix}/*"
      ]
      principals {
        type        = "*"
        identifiers = ["*"]
      }
    }
  }

  dynamic "statement" {
    for_each = each.key == "raw" ? [1] : []

    content {
      sid     = "AllowAnyAwsPrincipalWriteDianaInbox"
      effect  = "Allow"
      actions = ["s3:PutObject"]
      resources = [
        "${each.value.arn}/${local.diana_raw_inbox_prefix}/*"
      ]
      principals {
        type        = "*"
        identifiers = ["*"]
      }
      condition {
        test     = "StringNotEquals"
        variable = "aws:PrincipalType"
        values   = ["Anonymous"]
      }
    }
  }

  dynamic "statement" {
    for_each = each.key == "raw" ? [1] : []

    content {
      sid     = "DenyNonPubliclyReadableEncryptionDianaInbox"
      effect  = "Deny"
      actions = ["s3:PutObject"]
      resources = [
        "${each.value.arn}/${local.diana_raw_inbox_prefix}/*"
      ]
      principals {
        type        = "*"
        identifiers = ["*"]
      }
      condition {
        test     = "Null"
        variable = "s3:x-amz-server-side-encryption"
        values   = ["false"]
      }
      condition {
        test     = "StringNotEquals"
        variable = "s3:x-amz-server-side-encryption"
        values   = ["AES256"]
      }
    }
  }

  dynamic "statement" {
    for_each = each.key == "raw" ? [1] : []

    content {
      sid    = "AllowAnyAwsPrincipalManageMultipartDianaInbox"
      effect = "Allow"
      actions = [
        "s3:AbortMultipartUpload",
        "s3:ListMultipartUploadParts"
      ]
      resources = [
        "${each.value.arn}/${local.diana_raw_inbox_prefix}/*"
      ]
      principals {
        type        = "*"
        identifiers = ["*"]
      }
      condition {
        test     = "StringNotEquals"
        variable = "aws:PrincipalType"
        values   = ["Anonymous"]
      }
    }
  }

  dynamic "statement" {
    for_each = each.key == "results" ? [1] : []

    content {
      sid     = "AllowPublicReadVerifiedPublicResults"
      effect  = "Allow"
      actions = ["s3:GetObject"]
      resources = [
        for prefix in local.public_results_prefixes : "${each.value.arn}/${prefix}/*"
      ]
      principals {
        type        = "*"
        identifiers = ["*"]
      }
    }
  }

  dynamic "statement" {
    for_each = each.key == "results" ? [1] : []

    content {
      sid    = "DenyExternalReadDianaWgsHrd20260716"
      effect = "Deny"
      actions = [
        "s3:GetObject",
        "s3:GetObjectVersion"
      ]
      resources = [
        "${each.value.arn}/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/*"
      ]
      principals {
        type        = "*"
        identifiers = ["*"]
      }
      condition {
        test     = "StringNotEquals"
        variable = "aws:PrincipalAccount"
        values   = [data.aws_caller_identity.current.account_id]
      }
    }
  }

}

resource "aws_s3_bucket_policy" "tls" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id
  policy = data.aws_iam_policy_document.s3_tls[each.key].json
}

resource "aws_s3_bucket_lifecycle_configuration" "work" {
  bucket = aws_s3_bucket.this["work"].id

  rule {
    id     = "expire-nextflow-work"
    status = "Enabled"

    filter {
      prefix = ""
    }

    expiration {
      days = var.work_bucket_lifecycle_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "raw" {
  bucket = aws_s3_bucket.this["raw"].id

  rule {
    id     = "expire-old-raw-input-versions"
    status = "Enabled"

    filter {
      prefix = ""
    }

    noncurrent_version_expiration {
      noncurrent_days = var.raw_bucket_noncurrent_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_ecr_repository" "diana_omics" {
  name                 = var.project
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.main.arn
  }

  depends_on = [aws_iam_user_policy_attachment.bootstrap_local_cli]
}

resource "aws_ecr_lifecycle_policy" "diana_omics" {
  repository = aws_ecr_repository.diana_omics.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the most recent 25 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 25
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "batch" {
  name              = "/aws/batch/${local.name_prefix}"
  retention_in_days = 30
}

data "aws_iam_policy_document" "batch_instance_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "batch_instance" {
  name               = "${local.name_prefix}-batch-instance"
  assume_role_policy = data.aws_iam_policy_document.batch_instance_assume.json
}

resource "aws_iam_role_policy_attachment" "batch_instance_ecs" {
  role       = aws_iam_role.batch_instance.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_role_policy_attachment" "batch_instance_ssm" {
  role       = aws_iam_role.batch_instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "batch_instance_extra" {
  statement {
    sid    = "ReadEcrImage"
    effect = "Allow"
    actions = [
      "ecr:GetAuthorizationToken",
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage"
    ]
    resources = ["*"]
  }

  statement {
    sid    = "WriteBatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams"
    ]
    resources = ["${aws_cloudwatch_log_group.batch.arn}:*"]
  }
}

resource "aws_iam_role_policy" "batch_instance_extra" {
  name   = "${local.name_prefix}-batch-instance-extra"
  role   = aws_iam_role.batch_instance.id
  policy = data.aws_iam_policy_document.batch_instance_extra.json
}

resource "aws_iam_instance_profile" "batch" {
  name = "${local.name_prefix}-batch-instance"
  role = aws_iam_role.batch_instance.name
}

data "aws_iam_policy_document" "batch_job_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "batch_job" {
  name               = "${local.name_prefix}-batch-job"
  assume_role_policy = data.aws_iam_policy_document.batch_job_assume.json
}

data "aws_iam_policy_document" "batch_job" {
  statement {
    sid    = "UseDianaBuckets"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation"
    ]
    resources = [for bucket in aws_s3_bucket.this : bucket.arn]
  }

  statement {
    sid    = "ReadWriteDianaObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts"
    ]
    resources = [for bucket in aws_s3_bucket.this : "${bucket.arn}/*"]
  }

  statement {
    sid    = "ReadPhase3FastSourceBuckets"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation"
    ]
    resources = local.phase3_fast_source_bucket_arns
  }

  statement {
    sid    = "ReadPhase3FastVersionedSourceObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion"
    ]
    resources = [
      for arn in local.phase3_fast_source_bucket_arns : "${arn}/*"
    ]
  }

  statement {
    sid    = "DecryptPhase3FastSourceKmsKey"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:DescribeKey"
    ]
    resources = [
      "arn:aws:kms:${var.phase3_fast_source_region}:${data.aws_caller_identity.current.account_id}:key/*"
    ]
    condition {
      test     = "ForAnyValue:StringEquals"
      variable = "kms:ResourceAliases"
      values   = local.phase3_fast_source_kms_aliases
    }
  }

  statement {
    sid    = "UseDianaKmsKey"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:Encrypt",
      "kms:GenerateDataKey",
      "kms:DescribeKey"
    ]
    resources = [aws_kms_key.main.arn]
  }

  statement {
    sid    = "WriteBatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams"
    ]
    resources = ["${aws_cloudwatch_log_group.batch.arn}:*"]
  }
}

resource "aws_iam_role_policy" "batch_job" {
  name   = "${local.name_prefix}-batch-job"
  role   = aws_iam_role.batch_job.id
  policy = data.aws_iam_policy_document.batch_job.json
}

moved {
  from = aws_iam_service_linked_role.batch
  to   = aws_iam_service_linked_role.batch[0]
}

moved {
  from = aws_iam_service_linked_role.ec2_spot
  to   = aws_iam_service_linked_role.ec2_spot[0]
}

resource "aws_iam_service_linked_role" "batch" {
  count = var.manage_service_linked_roles ? 1 : 0

  aws_service_name = "batch.amazonaws.com"
  description      = "Service-linked role for Diana Omics AWS Batch"

  depends_on = [aws_iam_user_policy_attachment.bootstrap_local_cli]
}

resource "aws_iam_service_linked_role" "ec2_spot" {
  count = var.manage_service_linked_roles ? 1 : 0

  aws_service_name = "spot.amazonaws.com"
  description      = "Service-linked role for Diana Omics AWS Batch Spot capacity"

  depends_on = [aws_iam_user_policy_attachment.bootstrap_local_cli]
}

resource "aws_launch_template" "batch" {
  name_prefix            = "${local.name_prefix}-batch-"
  update_default_version = true
  user_data = base64encode(<<-USER_DATA
    MIME-Version: 1.0
    Content-Type: multipart/mixed; boundary="==DIANA_OMICS_USER_DATA=="

    --==DIANA_OMICS_USER_DATA==
    Content-Type: text/x-shellscript; charset="us-ascii"

    #!/bin/bash
    set -euxo pipefail
    mkdir -p /opt/diana-aws/bin
    ln -sf /usr/bin/aws /opt/diana-aws/bin/aws

    --==DIANA_OMICS_USER_DATA==--
  USER_DATA
  )

  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      delete_on_termination = true
      encrypted             = true
      iops                  = var.batch_root_volume_iops
      throughput            = var.batch_root_volume_throughput
      volume_size           = var.batch_root_volume_gb
      volume_type           = "gp3"
    }
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_put_response_hop_limit = 2
    http_tokens                 = "required"
  }

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "${local.name_prefix}-batch"
    }
  }
}

resource "aws_batch_compute_environment" "spot" {
  name         = "${local.name_prefix}-spot"
  service_role = local.batch_service_role_arn
  type         = "MANAGED"
  state        = "ENABLED"

  compute_resources {
    type                = "SPOT"
    allocation_strategy = "SPOT_CAPACITY_OPTIMIZED"
    bid_percentage      = 80
    min_vcpus           = 0
    desired_vcpus       = 0
    max_vcpus           = var.spot_max_vcpus
    instance_role       = aws_iam_instance_profile.batch.arn
    instance_type       = var.batch_arm_instance_families
    security_group_ids  = [aws_security_group.batch.id]
    subnets             = values(aws_subnet.private)[*].id

    launch_template {
      launch_template_id = aws_launch_template.batch.id
      version            = aws_launch_template.batch.latest_version
    }
  }

  depends_on = [
    aws_iam_role_policy.batch_instance_extra,
    aws_iam_role_policy_attachment.batch_instance_ecs,
    aws_iam_service_linked_role.batch,
    aws_iam_service_linked_role.ec2_spot
  ]

  lifecycle {
    ignore_changes = [compute_resources[0].desired_vcpus]
  }
}

resource "aws_batch_compute_environment" "ondemand" {
  name         = "${local.name_prefix}-ondemand"
  service_role = local.batch_service_role_arn
  type         = "MANAGED"
  state        = "ENABLED"

  compute_resources {
    type                = "EC2"
    allocation_strategy = "BEST_FIT_PROGRESSIVE"
    min_vcpus           = 0
    desired_vcpus       = 0
    max_vcpus           = var.ondemand_max_vcpus
    instance_role       = aws_iam_instance_profile.batch.arn
    instance_type       = var.batch_arm_instance_families
    security_group_ids  = [aws_security_group.batch.id]
    subnets             = values(aws_subnet.private)[*].id

    launch_template {
      launch_template_id = aws_launch_template.batch.id
      version            = aws_launch_template.batch.latest_version
    }
  }

  depends_on = [
    aws_iam_role_policy.batch_instance_extra,
    aws_iam_role_policy_attachment.batch_instance_ecs,
    aws_iam_service_linked_role.batch
  ]

  lifecycle {
    ignore_changes = [compute_resources[0].desired_vcpus]
  }
}

resource "aws_batch_compute_environment" "hrd_x86_ondemand" {
  name         = "${local.name_prefix}-hrd-x86-ondemand"
  service_role = local.batch_service_role_arn
  type         = "MANAGED"
  state        = "ENABLED"

  compute_resources {
    type                = "EC2"
    allocation_strategy = "BEST_FIT_PROGRESSIVE"
    min_vcpus           = 0
    desired_vcpus       = 0
    max_vcpus           = var.hrd_x86_max_vcpus
    instance_role       = aws_iam_instance_profile.batch.arn
    instance_type       = var.batch_x86_instance_families
    security_group_ids  = [aws_security_group.batch.id]
    subnets             = values(aws_subnet.private)[*].id

    ec2_configuration {
      image_type = "ECS_AL2023"
    }

    launch_template {
      launch_template_id = aws_launch_template.batch.id
      version            = aws_launch_template.batch.latest_version
    }
  }

  depends_on = [
    aws_iam_role_policy.batch_instance_extra,
    aws_iam_role_policy_attachment.batch_instance_ecs,
    aws_iam_service_linked_role.batch
  ]

  lifecycle {
    ignore_changes = [compute_resources[0].desired_vcpus]
  }

  tags = {
    Architecture = "linux-amd64"
    Workload     = "private-hrd-cross-check"
  }
}

resource "aws_batch_compute_environment" "gpu_p5en_ondemand" {
  name         = "${local.name_prefix}-gpu-p5en-ondemand"
  service_role = local.batch_service_role_arn
  type         = "MANAGED"
  state        = "ENABLED"

  compute_resources {
    type                = "EC2"
    allocation_strategy = "BEST_FIT_PROGRESSIVE"
    min_vcpus           = 0
    desired_vcpus       = 0
    max_vcpus           = var.gpu_p5en_max_vcpus
    instance_role       = aws_iam_instance_profile.batch.arn
    instance_type       = var.batch_gpu_p5en_instance_types
    security_group_ids  = [aws_security_group.batch.id]
    subnets             = values(aws_subnet.private)[*].id

    ec2_configuration {
      image_type = "ECS_AL2023_NVIDIA"
    }

    launch_template {
      launch_template_id = aws_launch_template.batch.id
      version            = aws_launch_template.batch.latest_version
    }
  }

  depends_on = [
    aws_iam_role_policy.batch_instance_extra,
    aws_iam_role_policy_attachment.batch_instance_ecs,
    aws_iam_service_linked_role.batch
  ]

  lifecycle {
    ignore_changes = [compute_resources[0].desired_vcpus]
  }

  tags = {
    Architecture = "linux-amd64"
    Workload     = "parabricks-p5en"
  }
}

resource "aws_batch_job_queue" "spot" {
  name     = "${local.name_prefix}-spot"
  state    = "ENABLED"
  priority = 10

  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.spot.arn
  }

  compute_environment_order {
    order               = 2
    compute_environment = aws_batch_compute_environment.ondemand.arn
  }
}

resource "aws_batch_job_queue" "ondemand" {
  name     = "${local.name_prefix}-ondemand"
  state    = "ENABLED"
  priority = 20

  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.ondemand.arn
  }
}

resource "aws_batch_job_queue" "hrd_x86" {
  name     = "${local.name_prefix}-hrd-x86"
  state    = "ENABLED"
  priority = 20

  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.hrd_x86_ondemand.arn
  }

  tags = {
    Architecture = "linux-amd64"
    Workload     = "private-hrd-cross-check"
  }
}

resource "aws_batch_job_queue" "gpu_p5en" {
  name     = "${local.name_prefix}-gpu-p5en"
  state    = "ENABLED"
  priority = 30

  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.gpu_p5en_ondemand.arn
  }

  tags = {
    Architecture = "linux-amd64"
    Workload     = "parabricks-p5en"
  }
}

resource "local_file" "nextflow_params" {
  filename        = "${path.module}/${var.nextflow_params_filename}"
  file_permission = "0600"
  content = jsonencode({
    aws_region                    = var.region
    aws_workdir                   = "s3://${aws_s3_bucket.this["work"].bucket}/work"
    aws_results_dir               = "s3://${aws_s3_bucket.this["results"].bucket}/runs"
    aws_private_results_dir       = "s3://${aws_s3_bucket.this["private_results"].bucket}/runs"
    phase3_fast_cache_kms_key_arn = aws_kms_key.main.arn
    phase3_fast_cache_prefix      = "s3://${aws_s3_bucket.this["private_results"].bucket}/phase3-fast-cache/wgs-v2"
    phase3_fast_cache_region      = var.region
    aws_gpu_queue                 = aws_batch_job_queue.gpu_p5en.name
    batch_gpu_p5en_instance_types = var.batch_gpu_p5en_instance_types
    gpu_p5en_max_vcpus            = var.gpu_p5en_max_vcpus
    aws_hrd_x86_queue             = aws_batch_job_queue.hrd_x86.name
    aws_spot_queue                = aws_batch_job_queue.spot.name
    aws_ondemand_queue            = aws_batch_job_queue.ondemand.name
    aws_job_role                  = aws_iam_role.batch_job.arn
    aws_logs_group                = aws_cloudwatch_log_group.batch.name
    container                     = "${aws_ecr_repository.diana_omics.repository_url}:${var.image_tag}"
    parabricks_container          = var.parabricks_container
    phase3_asset_cache_uri        = "s3://${aws_s3_bucket.this["raw"].bucket}/cache/phase3_wgs"
    diana_raw_inbox_uri           = "s3://${aws_s3_bucket.this["raw"].bucket}/${local.diana_raw_inbox_prefix}"
  })
}
