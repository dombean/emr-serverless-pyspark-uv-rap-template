# Welcome to emr-serverless-pyspark-uv-rap-template 🚀

This is the main documentation for the `emr-serverless-pyspark-uv-rap-template` project, a minimal yet
powerful template for deploying **PySpark** applications to **AWS EMR Serverless**.

This project demonstrates a modern Python development workflow using **uv** for
packaging and a built-in CLI for seamless deployments.

---
## 🧭 Guides

Explore the guides to get started and learn about best practices for
configuration and deployment.

- **[Infrastructure Setup with Terraform](terraform_guide.md) 🏗️:** A step-by-step
  guide to provisioning your AWS infrastructure using Terraform.
- **[EMR Serverless Guide](emr_serverless_guide.md) ⚙️:** A complete guide to setting
  up the necessary IAM roles and AWS resources for EMR Serverless.
- **[Spark Connect Guide](spark_connect_guide.md) 🔌:** Develop and debug PySpark
  interactively from VS Code, PyCharm, or Jupyter against EMR Serverless -- with
  ordinary local breakpoints and no VPC or bastion.
- **[Business Config Workflow](business_config_workflow.md) 🗂️:** Best practices for
  managing your application's configuration in a versioned and auditable way.

---
## ✨ Key Features

-   **Fast Dependency Management:** Uses `uv` for near-instant dependency resolution
    and packaging.
-   **Automated Deployments:** A built-in `deploy-to-emr` CLI to build, package,
    and submit jobs.
-   **Immutable Artifacts:** Creates versioned, immutable releases in S3 for full
    auditability.
-   **Apache Iceberg Ready:** Includes a sample job that writes to an Apache Iceberg
    table using the AWS Glue Catalog.
-   **Interactive Spark Connect:** A `spark-connect` CLI to develop and debug PySpark
    from your laptop against EMR Serverless (`emr-7.13.0`+), with local breakpoints
    and no VPC or bastion.
-   **EMR Studio (Optional):** One flag (`enable_emr_studio`) provisions the
    web-based notebook IDE, including its VPC, security groups, and service role.
