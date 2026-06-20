> ℹ️ **EMR Studio is optional and off by default**
>
> By default, this Terraform script provisions only the backend infrastructure
> for your EMR Serverless jobs (S3 buckets, ECR, Glue, IAM roles). To also
> create the EMR Studio -- the interactive web-based notebook IDE -- enable it
> with a flag:
>
> ```bash
> terraform apply -var enable_emr_studio=true
> ```
>
> This provisions the Studio together with everything it needs (the VPC,
> private subnets, NAT gateway, security groups, and service role), using IAM
> auth mode so no IAM Identity Center setup is required. Open it via the
> `EMR_STUDIO_URL` output.
>
> To run notebooks against your EMR Serverless application, the application
> must expose interactive endpoints: set `EMR_STUDIO_ENABLED=true` in `.env`
> before running `deploy-to-emr --create-app`. If the application already
> exists, stop it first (updates require the CREATED or STOPPED state).
>
> **Costs and caveats:**
>
> - The Studio itself is free, but the VPC it creates includes a NAT gateway
>   that runs at roughly $0.05/hour plus data charges. Set the flag back to
>   `false` when not in use. (For interactive development without any VPC, use
>   [Spark Connect](spark_connect_guide.md) instead.)
> - To attach a notebook to your application inside the Studio, you select the
>   application plus a **runtime role** -- your existing `EMR_EXECUTION_ROLE`
>   works for that. However, the IAM user/role *opening* the Studio needs its
>   own permissions: `elasticmapreduce:*Studio*`-style actions to access the
>   Studio and its workspaces, `emr-serverless:AccessInteractiveEndpoints` on
>   the application, and `iam:PassRole` on the runtime role. See the
>   [AWS user-permissions documentation for EMR Studio](https://docs.aws.amazon.com/emr/latest/ManagementGuide/emr-studio-user-permissions.html).

# 🏗️ Infrastructure Setup with Terraform

This guide explains how to use the provided Terraform scripts to provision the
necessary AWS infrastructure for this project. Following these steps will create
the S3 bucket, ECR repository, and all the required IAM roles and permissions.

---

### Understanding the Terraform Files

The infrastructure is defined across five files in the `terraform/` directory.
Here’s a breakdown of what each file does:

  - **`variables.tf`**: This file is where you define the input variables for your
  infrastructure. Think of them as parameters you can pass to your Terraform scripts
  to **customise** your deployment. For example, you can change the AWS region,
  S3 bucket name, or environment (dev, staging, prod) by modifying the variables
  in this file or by creating a `terraform.tfvars` file to override them.

  - **`main.tf`**: This is the core of your infrastructure definition. It contains
  the main set of instructions that tell Terraform what to create. It uses the
  variables from `variables.tf` to configure the resources.
  In this project, `main.tf` defines:

      - An S3 bucket for job **artifacts** and logs.
      - A dedicated S3 bucket for the **Iceberg data warehouse**.
      - An ECR repository for Docker images.
      - An AWS Glue Database to act as the **Iceberg catalogue**.
      - The IAM roles and policies needed for EMR Serverless to access these resources.


  - **`network.tf`**: Defines the VPC that EMR Studio requires -- public
  subnet, two private subnets, NAT gateway, and an S3 gateway endpoint. Created
  only when `enable_emr_studio` is true. (Spark Connect needs none of this.)

  - **`studio.tf`**: Defines the **optional** EMR Studio (gated behind
  `enable_emr_studio`, off by default): the Studio itself (IAM auth mode), its
  workspace/engine security groups, and its service role. See the note at the
  top of this page.

  - **`outputs.tf`**: This file declares the output values that you want to be easily
  accessible after Terraform has created the infrastructure. When you run
  `terraform apply`, the values of the outputs defined in this file will be printed
  to your console. This is particularly useful for getting the ARNs and names of
  the resources you've just created, which you'll need for your `.env` file.
  Outputs for the optional EMR Studio (e.g. `EMR_STUDIO_URL`) are `null` until
  `enable_emr_studio` is enabled.

---

### Terraform vs. the Deployment Script: What's the Difference?

It is important to understand the distinct roles of Terraform and
the `deploy-to-emr` script:

  - **Terraform (Infrastructure Setup)**: The Terraform script is responsible
  for provisioning the **foundational, long-lived AWS resources**. This includes
  the IAM roles, S3 buckets, ECR repository, and Glue Database. You typically
  run this **once** to set up your environment.

  - **`deploy-to-emr` script (Application Deployment)**: The
  `uv run deploy-to-emr --create-app` command creates the **EMR Serverless application**
  itself. This application is tightly coupled to your code and a specific Docker
  image version. Since the image URI changes with each new build, managing the
  application lifecycle through the deployment script provides more speed and
  flexibility for day-to-day development and deployment.

This separation ensures that your stable infrastructure is managed consistently,
while your application can be updated and deployed rapidly.

---

### Prerequisites

Before you begin, make sure you have the following installed and configured:

1.  **Terraform**: [Install Terraform](https://learn.hashicorp.com/tutorials/terraform/install-cli)
    on your local machine.
2.  **AWS CLI**: [Install and configure the AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-configure.html)
    with credentials for your AWS account. You should have permissions to
    create S3 buckets, ECR repositories, and IAM roles.

---

### 🚀 Provisioning the Infrastructure

The Terraform scripts are located in the `terraform/` directory.

1.  **Navigate to the Terraform directory:**

        ```bash
        cd terraform
        ```

2.  **Initialise Terraform:**
    This command downloads the necessary provider plug-ins. You only need to
    run this once per project.

        ```bash
        terraform init
        ```

3.  **(Optional) Customise Variables:**
    Open the `variables.tf` file to review the available options. You can change
    the default values here, or create a `terraform.tfvars` file to override them
    for your specific environment. For example, to change the S3 bucket name,
    you could create a `terraform.tfvars` file with the following content:

        ```terraform
        s3_artifact_bucket_name = "my-unique-emr-artifacts"
        iceberg_s3_bucket_name = "my-unique-iceberg-data"
        ```

4.  **Plan the Deployment:**
    This command shows you what resources Terraform will create, modify, or destroy.
    It's a great way to review changes before applying them.

        ```bash
        terraform plan
        ```

5.  **Apply the Configuration:**
    This command will create the resources in your AWS account.

        ```bash
        terraform apply
        ```

    Terraform will show you the plan again and ask for confirmation.
    Type `yes` and press Enter to proceed.

---

### 📝 Configuring Your `.env` File

After `terraform apply` completes successfully, it will print a list of outputs.
These outputs contain the names and ARNs of the resources that were just created.
You will use these values to create your `.env` file.

1.  **Copy the example file:**
    In the root of the repository, copy the `.env.example` file to
    a new file named `.env`.

        ```bash
        cp .env.example .env
        ```

2.  **Update `.env` with Terraform outputs:**
    Open the newly created `.env` file and replace the placeholder values with
     the outputs from the `terraform apply` command.

    Your `terraform apply` output will look something like this:

        ```
        Outputs:

        EMR_EXECUTION_ROLE = "arn:aws:iam::{YOUR_ACCOUNT_ID}:role/emr-spark-uv-emr-execution-role-dev"
        ICEBERG_GLUE_DB = "emr_serverless_iceberg_dev"
        ICEBERG_S3_BUCKET = "your-iceberg-data-bucket-dev"
        IMAGE_URI = "{YOUR_ACCOUNT_ID}.dkr.ecr.eu-west-2.amazonaws.com/emr-pyspark"
        S3_BUCKET = "your-artifacts-bucket-dev"
        ```

    Use these values to update your `.env` file accordingly:

        ```bash
        # .env

        REGION=eu-west-2
        S3_BUCKET="your-artifacts-bucket-dev"  # <-- Use the S3_BUCKET output
        EMR_EXECUTION_ROLE="arn:aws:iam::{YOUR_ACCOUNT_ID}:role/emr-spark-uv-emr-execution-role-dev" # <-- Use the EMR_EXECUTION_ROLE output
        IMAGE_URI="{YOUR_ACCOUNT_ID}.dkr.ecr.eu-west-2.amazonaws.com/emr-pyspark:7.13.0" # <-- Use the IMAGE_URI output and add a tag

        # Iceberg Configuration
        ICEBERG_S3_BUCKET="your-iceberg-data-bucket-dev" # <-- Use the ICEBERG_S3_BUCKET output
        ICEBERG_GLUE_DB="emr_serverless_iceberg_dev" # <-- Use the ICEBERG_GLUE_DB output
        ...
        ```

You are now ready to deploy your EMR Serverless application!

---

### 🧹 Cleaning Up

When you are finished with the infrastructure and want to avoid incurring further
costs, you can destroy all the resources created by Terraform with a single command:

```bash
terraform destroy
```

**A Note on Force Deletion:** The ECR repository is configured with
`force_delete = true` and the S3 buckets are configured with `force_destroy = true`.
This means `terraform destroy` will delete these resources and all of their
contents (Docker images and S3 objects). This is convenient for development but be
cautious if you ever use this script in a production environment where you
might want to preserve data.
