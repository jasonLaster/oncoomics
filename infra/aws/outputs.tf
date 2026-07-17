output "account_id" {
  description = "AWS account where the stack is provisioned."
  value       = data.aws_caller_identity.current.account_id
}

output "region" {
  description = "AWS region where the stack is provisioned."
  value       = var.region
}

output "ecr_repository_url" {
  description = "ECR repository URL for the Diana Omics image."
  value       = aws_ecr_repository.diana_omics.repository_url
}

output "nextflow_params_file" {
  description = "Generated Nextflow params file for AWS profiles."
  value       = local_file.nextflow_params.filename
}

output "nextflow_work_bucket" {
  description = "S3 bucket for disposable Nextflow work data."
  value       = aws_s3_bucket.this["work"].bucket
}

output "results_bucket" {
  description = "S3 bucket for reviewed public-validation Diana Omics results."
  value       = aws_s3_bucket.this["results"].bucket
}

output "private_results_bucket" {
  description = "Private, versioned, KMS-encrypted bucket for sensitive analysis results and reports."
  value       = aws_s3_bucket.this["private_results"].bucket
}

output "raw_inputs_bucket" {
  description = "Private bucket reserved for future raw-input handoffs."
  value       = aws_s3_bucket.this["raw"].bucket
}

output "diana_raw_inbox_uri" {
  description = "Write-only S3 inbox prefix for Diana raw-input uploads and transfers."
  value       = "s3://${aws_s3_bucket.this["raw"].bucket}/${local.diana_raw_inbox_prefix}"
}

output "spot_queue" {
  description = "AWS Batch Spot queue name."
  value       = aws_batch_job_queue.spot.name
}

output "ondemand_queue" {
  description = "AWS Batch On-Demand queue name."
  value       = aws_batch_job_queue.ondemand.name
}

output "batch_job_role_arn" {
  description = "IAM role ARN used by Batch jobs."
  value       = aws_iam_role.batch_job.arn
}
