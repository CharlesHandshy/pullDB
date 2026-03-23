# ECR Setup Guide

pullDB uses AWS Elastic Container Registry (ECR) as its private image registry.
Authentication is handled entirely via the EC2 instance's IAM role — no credentials
or config file changes are needed on the host once the role policy is attached.

---

## One-time setup (do this once per AWS account)

### Step 1: Create the ECR repository

```bash
aws ecr create-repository \
    --repository-name pulldb \
    --region us-east-1 \
    --image-scanning-configuration scanOnPush=true \
    --encryption-configuration encryptionType=AES256
```

Note the `repositoryUri` in the output — it will be:
```
<account-id>.dkr.ecr.us-east-1.amazonaws.com/pulldb
```

### Step 2: Set a lifecycle policy (keeps last 5 versions, auto-expires older ones)

```bash
aws ecr put-lifecycle-policy \
    --repository-name pulldb \
    --region us-east-1 \
    --lifecycle-policy-text '{
        "rules": [
            {
                "rulePriority": 1,
                "description": "Keep last 5 tagged releases",
                "selection": {
                    "tagStatus": "tagged",
                    "tagPrefixList": [""],
                    "countType": "imageCountMoreThan",
                    "countNumber": 5
                },
                "action": { "type": "expire" }
            },
            {
                "rulePriority": 2,
                "description": "Expire untagged images after 7 days",
                "selection": {
                    "tagStatus": "untagged",
                    "countType": "sinceImagePushed",
                    "countUnit": "days",
                    "countNumber": 7
                },
                "action": { "type": "expire" }
            }
        ]
    }'
```

---

## IAM policy: host EC2 instance role (pull only)

Attach this policy to the IAM role that the pullDB host EC2 instance uses.
This is the same role that already has access to S3 and Secrets Manager.

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ECRPull",
            "Effect": "Allow",
            "Action": [
                "ecr:GetAuthorizationToken",
                "ecr:BatchCheckLayerAvailability",
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage"
            ],
            "Resource": "*"
        }
    ]
}
```

> `ecr:GetAuthorizationToken` requires `Resource: "*"` — it cannot be scoped to a
> specific repository. The other actions can be scoped to
> `arn:aws:ecr:us-east-1:<account>:repository/pulldb` if you prefer least-privilege.

**How to attach via AWS Console:**
1. IAM → Roles → select the instance role (e.g., `pulldb-ec2-role`)
2. Add permissions → Create inline policy
3. Paste the JSON above → name it `pulldb-ecr-pull`

**How to attach via CLI:**
```bash
ROLE_NAME="pulldb-ec2-role"   # your instance role name

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name pulldb-ecr-pull \
    --policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "ECRPull",
            "Effect": "Allow",
            "Action": [
                "ecr:GetAuthorizationToken",
                "ecr:BatchCheckLayerAvailability",
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage"
            ],
            "Resource": "*"
        }]
    }'
```

---

## IAM policy: developer machines (push)

For the developer or CI runner that builds and pushes images.
Scope to the specific repository for least privilege.

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ECRAuth",
            "Effect": "Allow",
            "Action": ["ecr:GetAuthorizationToken"],
            "Resource": "*"
        },
        {
            "Sid": "ECRPush",
            "Effect": "Allow",
            "Action": [
                "ecr:BatchCheckLayerAvailability",
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage",
                "ecr:PutImage",
                "ecr:InitiateLayerUpload",
                "ecr:UploadLayerPart",
                "ecr:CompleteLayerUpload"
            ],
            "Resource": "arn:aws:ecr:us-east-1:<account-id>:repository/pulldb"
        }
    ]
}
```

---

## Verify access

On the host EC2 instance (no credentials required — uses instance role):
```bash
# Authenticate Docker to ECR
aws ecr get-login-password --region us-east-1 \
    | docker login --username AWS --password-stdin \
      <account-id>.dkr.ecr.us-east-1.amazonaws.com

# Pull the latest image
docker pull <account-id>.dkr.ecr.us-east-1.amazonaws.com/pulldb:1.3.0
```

On a developer machine (uses your local AWS profile):
```bash
aws --profile pr-dev ecr get-login-password --region us-east-1 \
    | docker login --username AWS --password-stdin \
      <account-id>.dkr.ecr.us-east-1.amazonaws.com
```

---

## Setting up the .env.compose file

After creating the repository, set `PULLDB_IMAGE` in `compose/.env.blue`:

```bash
cp compose/.env.compose.example compose/.env.blue
# Edit PULLDB_IMAGE to:
# <account-id>.dkr.ecr.us-east-1.amazonaws.com/pulldb:1.3.0
```

---

## Updating the image tag for each release

```bash
# On dev machine — build and push
make push   # builds image, authenticates, pushes with version tag

# On host — upgrade
sudo ./upgrade.sh <account-id>.dkr.ecr.us-east-1.amazonaws.com/pulldb:1.3.0
```
