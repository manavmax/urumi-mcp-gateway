#!/usr/bin/env python3
"""Debug script to run model discovery and print detailed information."""

import asyncio
import sys

# Add the src/gateway directory to the path so we can import gateway modules
sys.path.insert(0, '/Users/manavsharma/Desktop/Urumi_AI/src/gateway')

import config
from config import get_settings


async def main():
    print("=== Config Debug ===")
    print(f"Config file: {config.__file__}")
    
    # Get settings
    settings = get_settings()
    print(f"Settings type: {type(settings)}")
    print(f"Settings module: {settings.__class__.__module__}")
    
    # Check if the methods exist in the class
    print(f"Has min_version_filter: {hasattr(settings.__class__, 'min_version_filter')}")
    print(f"Has exclude_patterns: {hasattr(settings.__class__, 'exclude_patterns')}")
    print(f"Has discovered_models_enabled: {hasattr(settings.__class__, 'discovered_models_enabled')}")
    
    # If they exist, try to call them
    if hasattr(settings.__class__, 'min_version_filter'):
        try:
            print(f"Min version filter: {settings.min_version_filter()}")
        except Exception as e:
            print(f"Error calling min_version_filter: {e}")
    else:
        print("min_version_filter method not found in class")
        
    if hasattr(settings.__class__, 'exclude_patterns'):
        try:
            print(f"Exclude patterns: {settings.exclude_patterns()}")
        except Exception as e:
            print(f"Error calling exclude_patterns: {e}")
    else:
        print("exclude_patterns method not found in class")
        
    if hasattr(settings.__class__, 'discovered_models_enabled'):
        try:
            print(f"Discovery enabled: {settings.discovered_models_enabled()}")
        except Exception as e:
            print(f"Error calling discovered_models_enabled: {e}")
    else:
        print("discovered_models_enabled method not found in class")

if __name__ == "__main__":
    asyncio.run(main())