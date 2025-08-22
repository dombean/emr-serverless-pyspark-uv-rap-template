# 🚀 EMR Serverless, CloudWatch & Iceberg Setup

This guide provides a secure and functional IAM policy for running AWS EMR Serverless
applications while ensuring logs are correctly streamed to Amazon CloudWatch.
It also includes best practices for managing environments and setting up an
AWS Glue Catalog for use with Apache Iceberg.

---

## 🏗️ Structuring Environments (Dev vs. Prod)

When managing different environments like `development`, `staging`, and `production`,
you need a clear strategy for isolating data and resources.

Here are two common approaches for S3.

### Approach 1: Separate S3 Buckets (Recommended)

Create a distinct S3 bucket for each environment.

  - `your-app-data-dev`
  - `your-app-data-staging`
  - `your-app-data-prod`

**Trade-offs:**

  - ✅ **Pros**: Provides the strongest security isolation. IAM policies are simpler
    and safer, as you can grant a role access to an entire bucket without worrying
    about it touching another environment's data. It's the standard for production
    workloads.
  - ❌ **Cons**: Requires managing more S3 buckets, which can slightly increase
    administrative overhead.

### Approach 2: Subfolders in a Single S3 Bucket

Use one bucket with a folder structure for each environment.

  - `your-app-data/dev/`
  - `your-app-data/staging/`
  - `your-app-data/prod/`

**Trade-offs:**

  - ✅ **Pros**: Consolidates resources into a single bucket, which can be easier
    to browse.
  - ❌ **Cons**: **IAM policies are significantly more complex and error-prone**.
    You must write highly specific policies to prevent a dev role from
    accessing `prod/` data. A small mistake in the policy could lead to a major
    security incident.

**Recommendation**: For any serious project, **use separate S3 buckets**. The security
and isolation benefits far outweigh the minor inconvenience of managing a
few extra resources.

---

## 🧊 Using Iceberg with Glue Catalog

EMR Serverless uses the AWS Glue Data Catalog by default to manage metadata for
frameworks like Apache Spark and Hive. To use Apache Iceberg tables with PySpark,
you first need a database in Glue to act as a namespace.

1.  **Create a Glue Database**: Run the following AWS CLI command to create
    your database.

    ```bash
    aws glue create-database --database-input '{"Name":"emr_serverless_iceberg"}' --region <your-aws-region>
    ```

2.  **Important Naming Convention**:

      - In AWS Glue and Spark SQL, database names **cannot contain dashes (`-`)**.
      - Use only letters, numbers, and **underscores (`_`)**.
      - Example: `emr_serverless_iceberg` is valid; `emr-serverless-iceberg`
        is **invalid**.

---

## 🔑 Complete IAM Execution Role Policy

This is the final IAM policy needed for your EMR Serverless execution role.

**Important:** Before using this policy, replace the following placeholders:

  - `<your-aws-account-id>` with your AWS Account ID.
  - `<your-aws-region>` with your AWS Region.
  - `your-emr-bucket` with the name of your S3 bucket.

⚠️ **Security Note:** The following policy uses wildcards (`*`) for some resource
permissions for ease of setup. In a production environment, it is highly recommended
to scope these down to the specific resources your application needs.

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "FullAccessToSpecificOutputBucket",
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:ListBucket",
                "s3:DeleteObject"
            ],
            "Resource": [
                "arn:aws:s3:::your-emr-bucket",
                "arn:aws:s3:::your-emr-bucket/*"
            ]
        },
        {
            "Sid": "GlueCreateAndReadDataCatalog",
            "Effect": "Allow",
            "Action": [
                "glue:GetDatabase",
                "glue:CreateDatabase",
                "glue:GetDataBases",
                "glue:CreateTable",
                "glue:GetTable",
                "glue:UpdateTable",
                "glue:DeleteTable",
                "glue:GetTables",
                "glue:GetPartition",
                "glue:GetPartitions",
                "glue:CreatePartition",
                "glue:BatchCreatePartition",
                "glue:GetUserDefinedFunctions"
            ],
            "Resource": "*"
        },
        {
            "Sid": "AllowCloudWatchDescribe",
            "Effect": "Allow",
            "Action": "logs:DescribeLogGroups",
            "Resource": "*"
        },
        {
            "Sid": "AllowCloudWatchCreateAndWrite",
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents",
                "logs:DescribeLogStreams"
            ],
            "Resource": [
                "arn:aws:logs:<your-aws-region>:<your-aws-account-id>:log-group:/aws/emr-serverless*",
                "arn:aws:logs:<your-aws-region>:<your-aws-account-id>:log-group:/aws/emr-serverless*:*"
            ]
        }
    ]
}
```

---

## 🔑 ECR Repository Policy (for Custom Images)

If you use custom Docker images for your EMR Serverless jobs, you need to grant the
EMR Serverless service principal permission to pull images from your ECR repository.
This is done by attaching a resource-based policy to your ECR repository.

**Important:** Before using this policy, replace the following placeholders:

  - `<your-aws-region>` with your AWS Region.
  - `<your-aws-account-id>` with your AWS Account ID.

⚠️ **Security Note:** The following policy uses a wildcard (`*`) in the `aws:SourceArn`
to allow any EMR Serverless application in your account to access the ECR repository.
This is convenient for development, but for production, you should restrict this to a
specific application ARN for better security.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Emr Serverless Custom Image Support",
      "Effect": "Allow",
      "Principal": {
        "Service": "emr-serverless.amazonaws.com"
      },
      "Action": [
        "ecr:BatchGetImage",
        "ecr:DescribeImages",
        "ecr:GetDownloadUrlForLayer"
      ],
      "Condition": {
        "StringLike": {
          "aws:SourceArn": "arn:aws:emr-serverless:<your-aws-region>:<your-aws-account-id>:/applications/*"
        }
      }
    }
  ]
}
```

---

## ⚙️ Next Steps

1.  **Create IAM Role**: Go to the IAM console in AWS and create a new role.
    Select **Custom trust policy**. Use the following trust policy, which allows
    EMR Serverless to assume this role:
    ```json
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "emr-serverless.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }
    ```
2.  **Attach Policy**: On the next screen, create a new policy and paste the
    large JSON policy from the section above.
3.  **Name and Create**: Give your role a name (e.g., `EMR-Serverless-Execution-Role`)
    and save it.
4.  **Use the Role**: When you create your EMR Serverless application, select this
    newly created role as its execution role.
5.  **Check Logs**: After running a job, your logs will appear in CloudWatch under
    the log group `/aws/emr-serverless`.
