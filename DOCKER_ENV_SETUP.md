# Docker Hub Environment Variables Setup

## Important: Security Notice
**NEVER** include your `.env` file with API keys in the Docker image! 

## Environment Variables for Docker Hub

Based on the `example.env` file, your application needs these environment variables:

### Required API Keys (Add these in Docker Hub Build Settings)

The application supports multiple naming conventions for API keys:

```bash
# Both formats work - choose one:
API_KEY_OPENAI=your-openai-key        # OR  OPENAI_API_KEY=your-openai-key
API_KEY_ANTHROPIC=your-anthropic-key  # OR  ANTHROPIC_API_KEY=your-anthropic-key
API_KEY_GROQ=your-groq-key            # OR  GROQ_API_KEY=your-groq-key
API_KEY_PERPLEXITY=your-perplexity-key # OR  PERPLEXITY_API_KEY=your-perplexity-key
API_KEY_GOOGLE=your-google-key        # OR  GOOGLE_API_KEY=your-google-key
API_KEY_MISTRAL=your-mistral-key      # OR  MISTRAL_API_KEY=your-mistral-key
API_KEY_OPENROUTER=your-openrouter-key # OR  OPENROUTER_API_KEY=your-openrouter-key
API_KEY_SAMBANOVA=your-sambanova-key  # OR  SAMBANOVA_API_KEY=your-sambanova-key
HF_TOKEN=your-huggingface-token       # OR  HUGGINGFACE_TOKEN=your-huggingface-token
```

### Base URLs (These can be included in the Dockerfile)
```bash
OLLAMA_BASE_URL=http://127.0.0.1:11434
LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1
OPEN_ROUTER_BASE_URL=https://openrouter.ai/api/v1
SAMBANOVA_BASE_URL=https://fast-api.snova.ai/v1
```

### Application Settings
```bash
WEB_UI_PORT=50001
USE_CLOUDFLARE=false
TOKENIZERS_PARALLELISM=true
PYDEVD_DISABLE_FILE_VALIDATION=1
```

## How to Add Environment Variables in Docker Hub

1. Go to your Docker Hub repository settings
2. Navigate to "Builds" → "Configure Automated Builds"
3. Click on "Build Environment Variables"
4. Add each API key as a build-time variable
5. Mark sensitive variables as "Hidden" for security

## Runtime vs Build-time Variables

### Build-time (ARG in Dockerfile)
- Used during the build process
- Not included in the final image
- Good for: version info, build metadata

### Runtime (ENV in Dockerfile)
- Available when the container runs
- Included in the image layers
- Good for: default configurations

## Security Best Practices

1. **Never commit API keys to Git**
2. **Use Docker Hub's environment variables for sensitive data**
3. **Create a `.env.example` file with empty values**
4. **Document which variables are required**

## Example Docker Run Command
Using your `.env` file naming convention:
```bash
docker run -p 50001:50001 \
  -e OPENAI_API_KEY="your-key" \
  -e ANTHROPIC_API_KEY="your-key" \
  -e GROQ_API_KEY="your-key" \
  garyocean77/gary-zero:latest
```
Or using the alternative naming:
```bash
docker run -p 50001:50001 \
  -e API_KEY_OPENAI="your-key" \
  -e API_KEY_ANTHROPIC="your-key" \
  -e API_KEY_GROQ="your-key" \
  garyocean77/gary-zero:latest
```

## Using Docker Compose
```yaml
version: '3.8'
services:
  gary-zero:
    image: garyocean77/gary-zero:latest
    ports:
      - "50001:50001"
    env_file:
      - .env  # Create this locally, don't commit it
