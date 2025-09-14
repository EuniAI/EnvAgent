# Vertex AI Integration for Gemini 2.5 Pro

This document explains how to use Google Cloud Vertex AI with Gemini 2.5 Pro in the Prometheus Bug Reproduction Agent project.

## Setup

### 1. Install Dependencies

The required dependency has been added to `pyproject.toml`:

```toml
"google-cloud-aiplatform>=1.38.0"
```

Install it with:
```bash
pip install google-cloud-aiplatform>=1.38.0
```

### 2. Google Cloud Setup

1. **Authenticate with Google Cloud:**
   ```bash
   gcloud auth application-default login
   ```

2. **Enable the Vertex AI API:**
   ```bash
   gcloud services enable aiplatform.googleapis.com
   ```

3. **Set your project ID:**
   ```bash
   gcloud config set project YOUR_PROJECT_ID
   ```

## Usage

### Basic Usage

```python
from app.services.llm_service import LLMService

# Initialize with Vertex AI Gemini 2.5 Pro
llm_service = LLMService(
    advanced_model_name="gemini-2.5-pro",
    base_model_name="gemini-2.5-pro",
    vertex_ai_project_id="prometheus-code-agent",
    vertex_ai_location="us-central1",  # or other supported region
    temperature=0.0,
    max_output_tokens=15000,
)

# Use the model
response = llm_service.advanced_model.invoke("hi")
print(response.content)
```

### Direct Model Usage

```python
from app.services.llm_service import get_model

# Get a Vertex AI model directly
model = get_model(
    model_name="gemini-2.5-pro",
    vertex_ai_project_id="your-project-id",
    vertex_ai_location="us-central1",
    temperature=0.0,
    max_output_tokens=15000,
)

response = model.invoke("Your prompt here")
print(response.content)
```

## Model Selection Logic

The system automatically chooses the appropriate implementation based on the model name and parameters:

- **Gemini models with `vertex_ai_project_id`**: Uses Vertex AI (recommended for production)
- **Gemini models without `vertex_ai_project_id`**: Uses Google AI Studio API
- **Claude models**: Uses Anthropic API
- **Other models**: Uses OpenAI-compatible API

## Configuration

### Environment Variables

You can set these environment variables for easier configuration:

```bash
export VERTEX_AI_PROJECT_ID="your-project-id"
export VERTEX_AI_LOCATION="us-central1"
```

### Supported Regions

Gemini 2.5 Pro is available in the following regions:
- `us-central1`
- `us-east1`
- `us-west1`
- `europe-west1`
- `asia-southeast1`

## Example Scripts

- `test_vertex_ai_simple.py`: Simple test matching the original gcpscript.py
- `example_vertex_ai_usage.py`: More comprehensive example with error handling

## Troubleshooting

### Common Issues

1. **Authentication Error**: Make sure you've run `gcloud auth application-default login`
2. **API Not Enabled**: Enable the Vertex AI API in your GCP project
3. **Region Not Supported**: Check that Gemini 2.5 Pro is available in your chosen region
4. **Project ID Mismatch**: Ensure the project ID matches your GCP project

### Debug Mode

To debug authentication issues, you can check your current authentication:

```bash
gcloud auth list
gcloud config get-value project
```

## Performance Considerations

- Vertex AI provides better performance and reliability for production use
- The integration includes automatic retry logic (max 3 retries)
- Token limits are configurable via `max_output_tokens` parameter
- Temperature and other generation parameters are fully supported
