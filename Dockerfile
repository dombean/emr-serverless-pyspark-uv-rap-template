# Dockerfile for EMR Serverless PySpark Application
#
# This Dockerfile creates a self-contained, reproducible environment for running
# PySpark jobs on EMR Serverless. It is optimized for faster rebuilds during
# development by leveraging Docker's layer caching.
#
# --- Build Strategy Explanation ---
# The build process is structured in multiple steps to optimize for speed.
# Docker's layer caching reuses results from previous builds if the inputs
# for a step have not changed.
#
# 1.  **Dependency Definition Copy**: We first copy only `pyproject.toml` and
#     `uv.lock`. These files change infrequently.
# 2.  **Dependency Installation**: The `uv pip compile` and `uv pip install`
#     steps are the most time-consuming. By isolating them after the first
#     copy, the resulting layer is cached and only rebuilt if the lock file
#     changes.
# 3.  **Source Code Copy**: The application's source code is copied last.
#     This code changes frequently.
#
# This separation ensures that minor code edits do not trigger a full, slow
# re-installation of all Python dependencies, making the development cycle
# much more efficient.

# 1. Start with the official EMR Serverless base image for your target release.
FROM public.ecr.aws/emr-serverless/spark/emr-7.9.0:latest

# The base image uses Amazon Linux. We'll set the user to root to install packages.
USER root

# 2. Install uv using the existing Python 3.9 environment.
RUN pip3 install uv

# 3. Copy your project files and install dependencies
COPY pyproject.toml uv.lock ./

# First, compile a requirements.txt file from your project dependencies.
# The "debug" extra bakes in the remote-debugging agents (pydevd-pycharm,
# debugpy); they are inert unless DEBUG_HOST is set at job submission.
RUN uv pip compile pyproject.toml --extra debug --output-file requirements.txt

# Now, install the dependencies from the generated requirements.txt file.
RUN uv pip install --system -r requirements.txt

# Copy the rest of your application source code into the container.
COPY . .

# NOW, explicitly install the local package in editable mode into the system environment.
RUN uv pip install --system -e .

# 5. Set the default user back to 'hadoop'
# EMR Serverless runs jobs as this user.
USER hadoop
