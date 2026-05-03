"""Web search tools - fetch pages and search the web using lynx.

Provides web access capabilities:
- fetch_page: Get page content as text via lynx
- fetch_page_links: Extract links from a page
- web_search: Search DuckDuckGo lite
"""

import re
import subprocess
from typing import Optional

from modules import CalledFn, ContextFn, Module
from config import get


DEFAULT_TIMEOUT = get('web_timeout', 30)
MAX_CONTENT_LENGTH = get('web_max_content_length', 10000)


async def fetch_page(url: str) -> str:
    """Fetch a web page using lynx and return text content.
    
    Args:
        url: The URL to fetch
        
    Returns:
        Text content of the page
    """
    if not url.startswith(('http://', 'https://')):
        return f"[ERROR] URL must start with http:// or https://"
    
    try:
        result = subprocess.run(
            ['lynx', '-dump', '-nolist', '-width=200', url],
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT,
        )
        
        if result.returncode != 0:
            return f"[ERROR] Failed to fetch {url}: {result.stderr}"
        
        content = result.stdout.strip()
        
        if not content:
            return f"[ERROR] No content found at {url}"
        
        # Truncate very long pages
        if len(content) > MAX_CONTENT_LENGTH:
            content = content[:MAX_CONTENT_LENGTH] + f"\n\n... (truncated, {len(result.stdout)} total chars)"
        
        return content
    
    except subprocess.TimeoutExpired:
        return f"[ERROR] Timeout fetching {url}"
    except FileNotFoundError:
        return "[ERROR] lynx not installed. Install with: apt install lynx"
    except Exception as e:
        return f"[ERROR] {e}"


async def fetch_page_links(url: str) -> str:
    """Fetch a web page and return just the links.
    
    Args:
        url: The URL to fetch
        
    Returns:
        List of links from the page
    """
    if not url.startswith(('http://', 'https://')):
        return f"[ERROR] URL must start with http:// or https://"
    
    try:
        result = subprocess.run(
            ['lynx', '-dump', '-nolist', url],
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT,
        )
        
        if result.returncode != 0:
            return f"[ERROR] Failed to fetch {url}: {result.stderr}"
        
        # Extract links (lines starting with http)
        lines = result.stdout.strip().split('\n')
        links = []
        
        for line in lines:
            line = line.strip()
            # Links in lynx dump are typically standalone URLs
            if line.startswith(('http://', 'https://')):
                links.append(line)
        
        if not links:
            return f"No links found at {url}"
        
        return "Links found:\n" + "\n".join(f"  - {link}" for link in links[:50])
    
    except subprocess.TimeoutExpired:
        return f"[ERROR] Timeout fetching {url}"
    except FileNotFoundError:
        return "[ERROR] lynx not installed. Install with: apt install lynx"
    except Exception as e:
        return f"[ERROR] {e}"


async def web_search(query: str, num_results: int = 10) -> str:
    """Search the web using DuckDuckGo lite.
    
    Args:
        query: Search query
        num_results: Number of results to return (default: 10)
        
    Returns:
        Search results with titles and URLs
    """
    try:
        # Use DuckDuckGo HTML version
        search_url = f"https://lite.duckduckgo.com/lite/?q={query.replace(' ', '+')}"
        
        result = subprocess.run(
            ['lynx', '-dump', '-nolist', '-width=200', search_url],
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT,
        )
        
        if result.returncode != 0:
            return f"[ERROR] Search failed: {result.stderr}"
        
        lines = result.stdout.strip().split('\n')
        results = []
        
        # Parse results: numbered entries followed by description and URL
        current_result = None
        
        for line in lines:
            line = line.strip()
            
            if not line:
                continue
            
            # Skip header and navigation
            if 'DuckDuckGo' in line or 'Next Page' in line:
                continue
            if line.startswith('__'):
                continue
            
            # Match numbered results: "1. Title" or "  1. Title"
            match = re.match(r'^\s*(\d+)\.\s+(.+)$', line)
            if match:
                if current_result and current_result not in results:
                    results.append(current_result)
                title = match.group(2).strip()
                current_result = title
                continue
            
            # If we have a current result, parse description and URL
            if current_result:
                if line.startswith(('http://', 'https://')):
                    current_result += f" | {line}"
                    if current_result not in results:
                        results.append(current_result)
                    current_result = None
                elif len(line) > 10 and 'duckduckgo' not in line.lower():
                    current_result += f" - {line}"
            
            if len(results) >= num_results:
                break
        
        # Add last result if not added
        if current_result and current_result not in results:
            results.append(current_result)
        
        if not results:
            return f"No results found for: {query}"
        
        output = [f"Search results for: {query}", ""]
        for i, r in enumerate(results, 1):
            output.append(f"{i}. {r}")
        
        return '\n'.join(output)
    
    except subprocess.TimeoutExpired:
        return "[ERROR] Search timeout"
    except FileNotFoundError:
        return "[ERROR] lynx not installed. Install with: apt install lynx"
    except Exception as e:
        return f"[ERROR] {e}"


def _web_help() -> str:
    """Static tool documentation - does not change between calls."""
    from modules import _tool_ref
    return """## Web Tools (Help)

""" + _tool_ref('web_tools') + """

Note: Requires lynx to be installed (`apt install lynx`)."""


def get_module() -> Module:
    """Get the web_tools module."""
    return Module(
        name="web_tools",
        called_fns=[
            CalledFn(
                name="fetch_page",
                description="Fetch a web page using lynx and return text content.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to fetch (must start with http:// or https://)"},
                    },
                    "required": ["url"],
                },
                fn=fetch_page,
            ),
            CalledFn(
                name="fetch_page_links",
                description="Fetch a web page and return just the links.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to fetch links from"},
                    },
                    "required": ["url"],
                },
                fn=fetch_page_links,
            ),
            CalledFn(
                name="web_search",
                description="Search the web using DuckDuckGo lite.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "num_results": {"type": "integer", "description": "Number of results to return (default: 10)"},
                    },
                    "required": ["query"],
                },
                fn=web_search,
            ),
        ],
        context_fns=[
            # web_help is the standard tag used in shard configs (alias for web_tools)
            ContextFn(tag="web_help", fn=_web_help),
        ],
    )
