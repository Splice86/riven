"""Web crawler module using lynx."""

import subprocess
from modules import Module


def fetch_page(url: str) -> str:
    """Fetch a web page using lynx and return text content.
    
    Args:
        url: The URL to fetch
        
    Returns:
        Text content of the page
    """
    if not url.startswith(('http://', 'https://')):
        return f"Error: URL must start with http:// or https://"
    
    try:
        result = subprocess.run(
            ['lynx', '-dump', '-nolist', '-width=200', url],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            return f"Error fetching {url}: {result.stderr}"
        
        content = result.stdout.strip()
        if not content:
            return f"Error: No content found at {url}"
        
        # Truncate very long pages
        if len(content) > 10000:
            content = content[:10000] + f"\n\n... (truncated, {len(content)} total chars)"
        
        return content
    
    except subprocess.TimeoutExpired:
        return f"Error: Timeout fetching {url}"
    except Exception as e:
        return f"Error: {e}"


def fetch_page_links(url: str) -> str:
    """Fetch a web page and return just the links.
    
    Args:
        url: The URL to fetch
        
    Returns:
        List of links from the page
    """
    if not url.startswith(('http://', 'https://')):
        return f"Error: URL must start with http:// or https://"
    
    try:
        result = subprocess.run(
            ['lynx', '-dump', '-nolist', url],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            return f"Error fetching {url}: {result.stderr}"
        
        # Extract links (lines starting with numbers followed by URL)
        lines = result.stdout.strip().split('\n')
        links = []
        for line in lines:
            # Links in lynx dump are typically in format: "  1. http://..."
            if line.strip().startswith(('http://', 'https://')):
                links.append(line.strip())
        
        if not links:
            return f"No links found at {url}"
        
        return "Links found:\n" + "\n".join(f"  - {link}" for link in links[:50])
    
    except subprocess.TimeoutExpired:
        return f"Error: Timeout fetching {url}"
    except Exception as e:
        return f"Error: {e}"


def get_module() -> Module:
    """Create the web module."""
    return Module(
        name="web",
        enrollment=lambda: None,
        functions={
            "fetch_page": fetch_page,
            "fetch_page_links": fetch_page_links,
        }
    )