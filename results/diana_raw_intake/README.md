# Diana Raw Intake

Status: **template ready**.

Artifacts:

1. `manifests/diana_raw_inputs.template.csv`
2. `docs/operations/diana-raw-inputs.md`
3. `results/diana_raw_intake/input_contract.json`
4. `results/diana_raw_intake/intake_readiness_summary.csv`
5. `results/diana_raw_intake/dinah_handoff_plan.md`

The project can now accept Diana raw FASTQ, BAM, or CRAM paths through `manifests/diana_raw_inputs.csv`, plan the handoff with `PYTHONPATH=src /usr/bin/python3 -m diana_omics plan:diana-raw-handoff`, and validate paths with `PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw`.

Private S3 intake prefix:

```text
s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox
```
