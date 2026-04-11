#!/bin/bash
# Launch script for Riven
# Copy this file to launch.sh and fill in your IP addresses

# Memory server URL (where your memory API is running)
export MEMORY_API_URL="http://127.0.0.1:8030"

# LLM server URL (where your LLM is running)
export LLM_URL="http://127.0.0.1:8000/v1"

# Optional: LLM API key if needed
# export LLM_API_KEY="your-api-key-here"

# Run the agent
python main.py "$@"