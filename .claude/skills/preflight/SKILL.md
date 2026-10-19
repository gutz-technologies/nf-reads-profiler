---
name: preflight
description: Pre-flight check before running the pipeline on AWS Batch
---

# Pre-flight check for AWS Batch pipeline runs

Run these read-only checks before launching a pipeline run to catch common
problems early.

## Checks

### 1. Compute environments are ENABLED + VALID

```bash
aws batch describe-compute-environments \
  --region us-east-2 \
  --query "computeEnvironments[].{Name:computeEnvironmentName,State:state,Status:status,Reason:statusReason}"
```

Both must show `State: ENABLED`, `Status: VALID`.

### 2. Job queue is ENABLED

```bash
aws batch describe-job-queues \
  --job-queues spot-queue \
  --region us-east-2 \
  --query "jobQueues[0].{State:state,Status:status}"
```

### 3. Worker AMI is the current thin stock AMI

All four queues boot the thin stock AL2023 ECS ARM64 AMI (`ThinEcsAmiId`) and
sync their DBs from S3 at boot — there is no baked custom AMI. Verify each
queue's CE is on the AMI the public SSM parameter currently resolves to (a CE
stuck on an old LT version is the usual cause of boot-sync DB failures).

```bash
# What the stock thin AMI resolves to right now
THIN_AMI=$(aws ssm get-parameter --region us-east-2 \
  --name /aws/service/ecs/optimized-ami/amazon-linux-2023/arm64/recommended/image_id \
  --query 'Parameter.Value' --output text)
echo "Current thin AMI: $THIN_AMI"

# AMI each queue's CE's launch template resolves to
for q in spot-queue spot-metaphlan spot-humann spot-medi; do
  for ce in $(aws batch describe-job-queues --job-queues "$q" --region us-east-2 \
       --query "jobQueues[0].computeEnvironmentOrder[].computeEnvironment" --output text); do
    lt=$(aws batch describe-compute-environments --compute-environments "$ce" --region us-east-2 \
       --query "computeEnvironments[0].computeResources.launchTemplate.launchTemplateId" --output text)
    ami=$(aws ec2 describe-launch-template-versions --launch-template-id "$lt" --region us-east-2 \
       --versions '$Latest' --query 'LaunchTemplateVersions[0].LaunchTemplateData.ImageId' --output text)
    echo "$q / $ce -> LT $lt"
  done
done
```

WARN if any CE's LT doesn't resolve to the current thin AMI — force-roll it with
`/deploy-stack` step 4.

### 4. S3 buckets are reachable

```bash
aws s3 ls s3://gutz-nf-reads-profilers-workdir/ --region us-east-2 > /dev/null && echo "workdir: OK"
aws s3 ls s3://gutz-nf-reads-profilers-runs/ --region us-east-2 > /dev/null && echo "runs: OK"
aws s3 ls s3://cjb-gutz-s3-demo/ --region us-east-2 > /dev/null && echo "db source: OK"
```

### 5. Samplesheet exists (if user provided one)

If the user specified an `--input` samplesheet path, verify it exists in S3:

```bash
aws s3 ls <samplesheet-path>
```

### 6. No stuck jobs in the queue

```bash
aws batch list-jobs --job-queue spot-queue --region us-east-2 --job-status RUNNABLE \
  --query "length(jobSummaryList)"
aws batch list-jobs --job-queue spot-queue --region us-east-2 --job-status RUNNING \
  --query "length(jobSummaryList)"
```

If there are unexpected RUNNABLE/RUNNING jobs from a previous run, warn the user.

## Output

Print a pass/fail checklist and stop if anything fails.
