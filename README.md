# Prometheus Bug Reproduction Agent

This agent is used for automatically reproducing software bugs by utilizing large language models (LLMs) and knowledge graphs to analyze issues in GitHub repositories and attempt to reproduce them.

## Features

* Automatically clones GitHub code repositories
* Builds and stores code knowledge graphs
* Uses LLMs to analyze issue descriptions
* Reproduces bugs in a containerized environment
* Generates bug reproduction files, commands, and patches
* Supports batch testing with the SWE-bench dataset

## Requirements

* Python 3.8+
* Neo4j database
* Docker
* Git

## 📦 Setup
1. ### Install dependencies:

   ```bash
   pip install hatchling
   pip install .
   ```
2. ### Create the working directory to store logs and cloned repositories:

   ```bash
   mkdir working_dir
   ```

## Configuration

Before use, you need to set the following environment variables or configuration files:

* NEO4J related configurations (URI, username, password)
* LLM related API keys (OpenAI, Anthropic, Gemini, etc.)
* Working directory path
* GitHub access token (for private repositories)

## Usage

### Command-line execution

```bash
python -m app.main --dataset_name="your_dataset" --github_token="your_token"
```

### Parameter Description

* `--dataset_name`, `-d`: SWE-bench dataset name (required)
* `--github_token`, `-g`: GitHub access token (optional)
* `--file`, `-f`: File to save the prediction results (defaults to `predictions_XXX.json` with a timestamp)

## Workflow

1. Load test cases from the SWE-bench dataset
2. Clone the GitHub repository locally
3. Build the code knowledge graph
4. Initialize the container environment (user-defined or generic container)
5. Call the bug reproduction subgraph for analysis and reproduction
6. Save the reproduction results (success/failure, related files, commands, and patches)

## Project Structure

* `app/main.py`: Main program entry
* `app/configuration/`: Configuration-related code
* `app/container/`: Docker container management code
* `app/lang_graph/`: Language graph-related code
* `app/services/`: Various service implementations (knowledge graph, repository, LLM, etc.)

## Notes

* Ensure Docker service is running
* For private repositories, provide a valid GitHub token
* Large repositories may require more time and memory for analysis
