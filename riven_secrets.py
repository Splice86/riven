# Secrets module - loads and provides access to secrets.yaml
import os
import yaml


def _load_secrets() -> dict:
    """Load secrets from secrets.yaml, falling back to template if not found."""
    if os.path.exists("secrets.yaml"):
        with open("secrets.yaml") as f:
            return yaml.safe_load(f) or {}
    
    if os.path.exists("secrets_template.yaml"):
        with open("secrets_template.yaml") as f:
            return yaml.safe_load(f) or {}
    
    raise ValueError("No secrets.yaml or secrets_template.yaml found")


SECRETS = _load_secrets()


def get_secret(*keys, default=None):
    """Get a secret value by keys, e.g. get_secret('llm', 'primary', 'url')
    
    Args:
        *keys: Chain of keys to traverse
        default: Default value if not found
        
    Returns:
        The secret value or default
    """
    value = SECRETS
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
            if value is None:
                return default
        else:
            return default
    return value if value is not None else default


def get_llm_config(name: str) -> dict:
    """Get LLM config by name (primary, alternate, etc.)
    
    Args:
        name: Config name ('primary', 'alternate')
        
    Returns:
        Dict with url, model, api_key
    """
    config = get_secret('llm', name, default={})
    return {
        'url': config.get('url'),
        'model': config.get('model', 'nvidia/MiniMax-M2.5-NVFP4'),
        'api_key': config.get('api_key', 'sk-dummy'),
    }


def get_memory_api() -> str:
    """Get memory API URL."""
    return get_secret('memory_api', 'url')