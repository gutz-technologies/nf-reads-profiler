---
name: deploy-stack
description: Deploy the CloudFormation stack and re-validate Batch compute environments
---

# Deploy the nf-reads-profiler Batch stack

This skill deploys the CloudFormation stack and re-validates compute environments.

**Before running**: confirm with the user that they want to deploy. Show them the
`git diff infra/batch-stack.yaml` so they can review changes.

## Steps

### 1. Validate the templates

Use `cfn-lint` (no 51 KB inline limit, stricter than `validate-template`):

```bash
cfn-lint infra/batch-stack.yaml infra/batch-dashboard.yaml
```

If linting fails, stop and report the error.

### 2. Deploy the compute stack

The template is over the 51 KB inline limit, so `deploy` MUST stage it through
S3 (`--s3-bucket`/`--s3-prefix`); a bare `deploy` errors with "Templates with a
size greater than 51,200 bytes must be deployed via an S3 Bucket".

`aws cloudformation deploy` **preserves the stack's previous value for any
param not listed** in `--parameter-overrides`. So editing a param's `Default:`
in the template is a no-op on redeploy unless the param is passed here. Every
non-default param (including all four `MaxvCPUs*`) is therefore pinned
explicitly below — update the value here when you change a `Default:`.

Budget/alarm/dashboard resources moved to batch-dashboard.yaml (step 4b), so
`BudgetAlertEmail`/`MonthlyBudgetThreshold` are NOT passed here anymore.

```bash
aws cloudformation deploy \
  --stack-name nf-reads-profiler-batch \
  --template-file infra/batch-stack.yaml \
  --s3-bucket gutz-nf-reads-profilers-workdir \
  --s3-prefix cfn-templates \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-2 \
  --parameter-overrides \
    VpcId=vpc-06ad1e39bb8cd26df \
    SubnetIds="subnet-09159c654acc505a3,subnet-03afe111356916511,subnet-0d0f1d152c1656677" \
    WorkDirBucketName=gutz-nf-reads-profilers-workdir \
    RunsBucketName=gutz-nf-reads-profilers-runs \
    SpotBidPercentage=50 \
    MaxvCPUsSpot=256 \
    MaxvCPUsOnDemand=0 \
    MaxvCPUsMetaphlan=200 \
    MaxvCPUsHumann=960 \
    MaxvCPUsMedi=100 \
    ProjectTag=nf-reads-profiler \
    EnvironmentTag=development \
    DbSourceBucket=cjb-gutz-s3-demo
```

### 3. Wait for completion

```bash
aws cloudformation wait stack-update-complete \
  --stack-name nf-reads-profiler-batch \
  --region us-east-2
```

### 3b. Deploy the monitoring stack

The observability subsystem (SNS topic, alarms, the EventBridge→Lambda metric
publishers, the multi-queue dashboard, and the monthly budget) lives in a
separate stack that imports the compute stack's queue-ARN exports. Deploy it
AFTER the compute stack so those exports exist. It is independent — a
dashboard/alarm change can be re-deployed with just this command, no compute
churn.

```bash
aws cloudformation deploy \
  --stack-name nf-reads-profiler-monitoring \
  --template-file infra/batch-dashboard.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-2 \
  --parameter-overrides \
    BatchStackName=nf-reads-profiler-batch \
    ProjectTag=nf-reads-profiler \
    EnvironmentTag=development \
    BudgetAlertEmail=colin@vasogo.com \
    MonthlyBudgetThreshold=200

aws cloudformation wait stack-update-complete \
  --stack-name nf-reads-profiler-monitoring \
  --region us-east-2
```

### 4. Force compute environments to pick up the new launch template

**Important:** A simple disable/re-enable does NOT force Batch to re-snapshot
the launch template UserData. You must explicitly update each CE with its
launch template reference and `updateToLatestImageVersion`.

**Refresh ALL four queues, not just spot-queue.** Each per-database queue
(metaphlan/humann/medi) has its own launch template; a UserData change to one of
those won't take until *its* CE is force-rolled. (This bit us once: a medi
boot-sync fix sat inert on a cached LT version while jobs kept failing
`exit 255` until the medi CE was manually refreshed.) The loop below walks every
queue → its CE(s) and rolls each. `spot-queue` has two CEs (spot + on-demand);
the per-DB queues have one each.

```bash
for QUEUE in spot-queue spot-metaphlan spot-humann spot-medi; do
  for CE in $(aws batch describe-job-queues --job-queues "$QUEUE" --region us-east-2 \
       --query "jobQueues[0].computeEnvironmentOrder[].computeEnvironment" --output text); do
    LT_ID=$(aws batch describe-compute-environments --compute-environments "$CE" --region us-east-2 \
       --query "computeEnvironments[0].computeResources.launchTemplate.launchTemplateId" --output text)
    echo "Refreshing $QUEUE -> $CE (LT $LT_ID)"
    aws batch update-compute-environment --compute-environment "$CE" --region us-east-2 \
      --compute-resources "{\"launchTemplate\":{\"launchTemplateId\":\"$LT_ID\",\"version\":\"\$Latest\"},\"updateToLatestImageVersion\":true}"
  done
done
```

Wait for all CEs to become VALID before proceeding.

### 5. Confirm all are VALID

```bash
aws batch describe-compute-environments \
  --region us-east-2 \
  --query "computeEnvironments[].{Name:computeEnvironmentName,State:state,Status:status}"
```

Report the result to the user.
