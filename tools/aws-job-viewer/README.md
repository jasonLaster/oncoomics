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

The hosted viewer also persists normalized job-status, chromosome-progress, and complete CloudWatch log events in Convex. Convex receives the same project-scoped Vercel OIDC identity. Log messages are deduplicated with deterministic SHA-256 event keys, and a per-stream forward cursor makes each one-minute refresh incremental. Durable chromosome maxima are merged back into each response so cold starts do not lose completed work.

The stable Convex production deployment is released with `npm run convex:deploy` while a production deploy key is present. `CONVEX_URL` selects that deployment at runtime; when it is absent, the viewer continues in live AWS-only mode. Vercel Preview and Production point to the same stable operational history rather than creating isolated per-branch databases.

## Views

- **Overview** shows active and recent jobs, run stages, dependency order, execution details, and chromosome progress when GATK progress events are available.
- **Raw logs** reads the newest 1,000 events from Convex, with **Load older** and **Load all** controls that make every archived event visible. Opening or refreshing a job first advances its CloudWatch cursor so the archive remains current.

## Backfill CloudWatch logs

After deploying the Convex schema, backfill every event retained for every stream-bearing job discoverable in the enabled AWS Batch queues:

```bash
cd tools/aws-job-viewer
CONVEX_URL=https://your-production-deployment.convex.cloud \
  npm run convex:backfill-logs
```

The process starts each stream at its head, paginates until CloudWatch returns a stable forward token, and safely resumes after interruptions. Re-running it is idempotent. AWS access comes from the normal SDK credential chain or `AWS_ROLE_ARN`; Convex access uses the project-scoped `VERCEL_OIDC_TOKEN`.

Optional runtime configuration is documented in `.env.example`.
