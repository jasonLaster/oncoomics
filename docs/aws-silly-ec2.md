# AWS Silly EC2 Smoke Test

This is a tiny AWS starter exercise: launch one disposable EC2 instance, have it print a silly message to the EC2 console, and let it terminate itself.

The script uses:

- AWS CLI only; no Terraform or CloudFormation yet.
- The AWS Systems Manager public parameter for the latest Amazon Linux 2023 AMI, so no region-specific AMI ID is hard-coded.
- No SSH key and no inbound ports.
- Encrypted 8 GB gp3 root volume with `DeleteOnTermination=true`.
- `--instance-initiated-shutdown-behavior terminate`, so the instance should clean itself up after the user-data script finishes.
- Optional private S3 bucket access through an EC2 instance role, so the instance can write a tiny report without baking access keys into user data.

## Install and Authenticate

Install the AWS CLI:

```sh
brew install awscli
```

Authenticate. SSO is usually the least annoying path for a human AWS account:

```sh
aws configure sso
```

If you already have static credentials or another profile, that is fine too. Export a profile if needed:

```sh
export AWS_PROFILE=my-profile
```

For a personal throwaway test using an IAM access key, the CLI identity needs enough permissions to launch EC2 and create the small S3/IAM test resources. The quick sandbox route is to attach these managed policies to the IAM user while testing:

- `AmazonEC2FullAccess`
- `AmazonS3FullAccess`
- `IAMFullAccess`
- `AmazonSSMReadOnlyAccess`

That is broad. For anything beyond this starter exercise, replace it with a narrower policy and delete or rotate the access key when you are done.

## Check the Setup

From the repo root:

```sh
scripts/aws-silly-ec2 check
```

By default the script uses `us-west-2` and a `t3.micro`. Override those with environment variables:

```sh
AWS_REGION=us-east-1 AWS_SILLY_INSTANCE_TYPE=t3.micro scripts/aws-silly-ec2 check
```

If the region does not have a default VPC, provide a subnet and security group:

```sh
AWS_SILLY_SUBNET_ID=subnet-... \
AWS_SILLY_SECURITY_GROUP_ID=sg-... \
scripts/aws-silly-ec2 check
```

## Add S3

Create a private bucket plus an EC2 instance profile that can write only under the `silly-ec2/` prefix:

```sh
scripts/aws-silly-ec2 setup-s3
```

By default the bucket name is:

```text
diana-omics-silly-<aws-account-id>-<region>
```

To use a different globally unique bucket name:

```sh
AWS_SILLY_S3_BUCKET=my-unique-silly-bucket-name scripts/aws-silly-ec2 setup-s3
```

## Launch the Silly Instance

```sh
scripts/aws-silly-ec2 launch
```

The script asks for confirmation because this creates billable AWS resources. It prints the instance ID. If `setup-s3` has been run, the instance also writes a small report to S3.

Watch status:

```sh
scripts/aws-silly-ec2 status
```

After a minute or two, fetch the console output:

```sh
scripts/aws-silly-ec2 console i-0123456789abcdef0
```

Look for:

```text
SILLY_EC2_BEGIN
cloud potato says:
Silly verdict:
Moon-cheese compatibility score:
S3 report: s3://...
SILLY_EC2_DONE
```

List the S3 reports:

```sh
scripts/aws-silly-ec2 s3-ls
```

## Manual Cleanup

The instance should terminate itself. If it does not, terminate it manually:

```sh
scripts/aws-silly-ec2 terminate i-0123456789abcdef0
```

Then confirm there are no leftover running instances:

```sh
scripts/aws-silly-ec2 status
```

Remove the S3 bucket, instance profile, and role created by `setup-s3`:

```sh
scripts/aws-silly-ec2 cleanup-s3
```

## Cost Notes

This is meant to be small, but not guaranteed free. AWS free tier eligibility depends on the account, region, instance type, and current AWS terms. Keep the instance short-lived and check the AWS billing console if you are using a personal account.
