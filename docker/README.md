# Docker readme

## Setup

```sh
docker login
# I opened the web browser and logged in with GitHub

# Set up multiplatform builds, see
# https://forums.docker.com/t/error-multiple-platforms-feature-is-currently-not-supported-for-docker-driver/124811/12
docker buildx ls
docker buildx create --name multiarch --driver docker-container --use
docker buildx ls
```

## Buildx

Note that the final argument is the path to the folder with the Dockerfile, not the name of the image. The name of the image is set with the -t flag.

```sh
cd docker

# Build and push multi-arch (amd64 + arm64)
docker buildx build --platform linux/amd64,linux/arm64 -t colinbrislawn/aws-cli-bash:2 --push aws-cli-bash
docker buildx build --platform linux/amd64,linux/arm64 -t colinbrislawn/sra-tools-bash:3.0.7 --push sra-tools-bash
docker buildx build --platform linux/arm64 -t colinbrislawn/kneaddata:0.10.0 --push kneaddata
docker buildx build --platform linux/arm64 -t colinbrislawn/metaphlan:4.2.4 --push metaphlan
docker buildx build --platform linux/arm64 -t colinbrislawn/medi:0.2.1 --push medi
```

## ECR (AWS private registry)

Authenticate once per session, then build and push to ECR:

```sh
ECR=730883236839.dkr.ecr.us-east-2.amazonaws.com
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin $ECR

cd docker

# Build and push all ARM, all the time 🦾
docker buildx build --platform linux/arm64 -t $ECR/aws-cli-bash:2 --push aws-cli-bash
docker buildx build --platform linux/arm64 -t $ECR/sra-tools-bash:3.0.7 --push sra-tools-bash
docker buildx build --platform linux/arm64 -t $ECR/metaphlan:4.2.4 --push metaphlan
docker buildx build --platform linux/arm64 -t $ECR/medi:0.2.1 --push medi
docker buildx build --platform linux/arm64 -t $ECR/kneaddata:0.10.0 --push kneaddata

# Mirror public images to our ECR
docker pull --platform linux/arm64 barbarahelena/humann:4.0.3
docker tag barbarahelena/humann:4.0.3 $ECR/humann:4.0.3
docker push $ECR/humann:4.0.3

docker pull --platform linux/arm64 getwilds/fastp:1.1.0
docker tag getwilds/fastp:1.1.0 $ECR/fastp:1.1.0
docker push $ECR/fastp:1.1.0

docker pull --platform linux/arm64 ghcr.io/multiqc/multiqc:v1.22.3
docker tag ghcr.io/multiqc/multiqc:v1.22.3 $ECR/multiqc:v1.22.3
docker push $ECR/multiqc:v1.22.3

# back to the repo root!
cd ..
```

## KneadData 0.10.0 (standalone preprocessing)

The image installs Bioconda KneadData **0.10.0** and Trimmomatic **0.39** to
match the documented CosmosID/Diversigen cohort protocol. It replaces the
standalone Hostile image; preprocessing is not wired into Nextflow yet.
Run it only for cohorts that still need preprocessing. For cohorts already
processed with KneadData, supply their cleaned FASTQs directly to the pipeline;
do not run KneadData a second time.
The Dockerfile exposes the Trimmomatic JAR on PATH for this older KneadData
release. Bowtie2 and the remaining dependencies are resolved at build time;
record their versions and the image digest with each run. This does not establish
an exact match to the providers' full software environment.

Build and check locally before publishing (from the repository root):

```sh
docker build -t colinbrislawn/kneaddata:0.10.0 docker/kneaddata
docker run --rm colinbrislawn/kneaddata:0.10.0 kneaddata --version
```

Keep reference databases outside the image. To reproduce the cohorts, obtain the
same **GRCh38_noalt_as** Bowtie2 index and record its source and checksums. A newer
T2T/human reference is a different filtering protocol. Mount the complete index
directory; `-db` takes the index **prefix**, not the directory or a `.bt2` file.

```sh
docker run --rm \
  -v /path/to/GRCh38_noalt_as:/db:ro \
  -v /path/to/data:/data:ro -v /path/to/out:/out \
  colinbrislawn/kneaddata:0.10.0 \
  kneaddata \
    -i /data/R1.fastq.gz -i /data/R2.fastq.gz \
    -o /out -db /db/GRCh38_noalt_as -t 10
```

The repeated `-i` syntax is specific to this older interface. Trimmomatic is
found through PATH, so no host-side `--trimmomatic` path is needed. This command
retains the cohort's default trimming, TRF filtering, and strict paired-read
removal behavior. Loss between trimmed and decontaminated counts can include
TRF removal; do not label all of it as host removal. Preserve KneadData logs for
stage-level counts and provenance.

For AWS, provision the same index on workers and mount its directory. The build
commands above prepare an ARM64 image; the upstream `biobakery/kneaddata:0.10.0`
image is AMD64-only. Avoid upstream `:latest`, which points to 0.7.10.

## View images we can give to Nextlow

```sh
docker search colinbrislawn
```

## Extra!

```sh
# View all local images on this machine
docker image ls

# Remove a local image
# be specific with REPOSITORY:TAG
docker image rm hello-world:latest
docker image rm lightweightlabware/aws-cli-bash:ubuntu
docker image rm amazon/aws-cli

```
