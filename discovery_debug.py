#!/usr/bin/env python3
"""Debug script to run model discovery and print detailed information."""

import asyncio
import sys

# Add the src/gateway directory to the path so we can import gateway modules
sys.path.insert(0, '/Users/manavsharma/Desktop/Urumi_AI/src/gateway')

from chat.model_discovery import ModelDiscovery
from config import get_settings


async def main():
    print("=== Model Discovery Debug ===")
    
    # Get settings
    settings = get_settings()
    print(f"Settings type: {type(settings)}")
    print(f"Settings dir: {[attr for attr in dir(settings) if not attr.startswith('_')]}")
    print(f"API Key set: {bool(settings.openai_api_key)}")
    print(f"Base URL: {settings.openai_base_url}")
    print(f"Models env: {settings.openai_models}")
    
    # Try to access the methods
    try:
        print(f"Min version filter: {settings.min_version_filter()}")
    except Exception as e:
        print(f"Error accessing min_version_filter: {e}")
        
    try:
        print(f"Exclude patterns: {settings.exclude_patterns()}")
    except Exception as e:
        print(f"Error accessing exclude_patterns: {e}")
        
    try:
        print(f"Discovery enabled: {settings.discovered_models_enabled()}")
    except Exception as e:
        print(f"Error accessing discovered_models_enabled: {e}")
    
    if not settings.discovered_models_enabled():
        print("Discovery not enabled - missing API key or base URL")
        return
    
    # Create discovery instance
    discovery = ModelDiscovery()
    
    # Run refresh
    print("\n--- Running discovery refresh ---")
    models = await discovery.refresh()
    
    print(f"\nDiscovered {len(models)} models after filtering and probing")
    
    # Print detailed info for each model
    print("\n--- Detailed Model Information ---")
    for i, model in enumerate(models):
        print(f"{i+1}. ID: {model.id}")
        print(f"   Owned by: {model.owned_by}")
        print(f"   Supports tools: {model.supports_tools}")
        print(f"   Last probe time: {model.last_probe_time}")
        print(f"   Last probe error: {model.last_probe_error}")
        print(f"   Available now: {model.is_available(asyncio.get_event_loop().time())}")
        print()
    
    # Get effective model chain
    print("--- Effective Model Chain ---")
    chain = discovery.get_effective_model_chain(settings)
    print(f"Chain: {chain}")
    
    # Get discovered models info for summary
    info = discovery.get_discovered_models_info()
    
    # Summary statistics
    print("--- Summary Statistics ---")
    total = len(info)
    supports_tools_true = sum(1 for m in info if m["supports_tools"] is True)
    supports_tools_false = sum(1 for m in info if m["supports_tools"] is False)
    supports_tools_none = sum(1 for m in info if m["supports_tools"] is None)
    available = sum(1 for m in info if m["available"])
    
    print(f"Total models: {total}")
    print(f"Supports tools (True): {supports_tools_true}")
    print(f"Supports tools (False): {supports_tools_false}")
    print(f"Supports tools (None/unknown): {supports_tools_none}")
    print(f"Available (not in cooldown): {available}")
    
    # Show which would be excluded by "older" and why
    print("\n--- Models excluded by min_version filter ---")
    min_version = settings.min_version_filter()
    if min_version:
        excluded_by_min_version = [m for m in info if m["id"] < min_version]
        for m in excluded_by_min_version:
            print(f"  {m['id']} (lexicographically < '{min_version}')")
    else:
        print("  No min_version filter set")
    
    print("\n--- Models excluded by exclude patterns ---")
    exclude_patterns = settings.exclude_patterns()
    if exclude_patterns:
        excluded_by_patterns = []
        for m in info:
            for pattern in exclude_patterns:
                if pattern in m["id"]:
                    excluded_by_patterns.append((m["id"], pattern))
                    break
        for model_id, pattern in excluded_by_patterns:
            print(f"  {model_id} (contains '{pattern}')")
    else:
        print("  No exclude patterns set")

if __name__ == "__main__":
    asyncio.run(main())