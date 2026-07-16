# Diana AWS job viewer

A private local dashboard for Diana AWS Batch jobs and CloudWatch logs.

## Open the viewer

```bash
cd tools/aws-job-viewer
npm install
npm run viewer
```

Then open [http://localhost:3000](http://localhost:3000). The viewer reads the current AWS CLI profile, discovers enabled Batch queues, and refreshes every 60 seconds. Set `AWS_PROFILE` before launching to use a profile other than `default`.

AWS credentials stay in the server process and are never sent to the browser. The profile only needs read access for Batch job discovery and CloudWatch log events.

Vercel deployments use `AWS_ROLE_ARN` with Vercel OIDC to exchange short-lived tokens for a scoped AWS read-only session. Static AWS access keys are not required.

## Views

- **Overview** shows active and recent jobs, run stages, dependency order, execution details, and chromosome progress when GATK progress events are available.
- **Raw logs** tails the latest 1,000 events from the selected job's CloudWatch stream.

Optional runtime configuration is documented in `.env.example`.
