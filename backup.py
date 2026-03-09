#!/usr/bin/env python3
"""
Backup Codey-v2 codebase with timestamp.
"""

import tarfile
import os
from datetime import datetime
from pathlib import Path

def create_backup():
    """Create timestamped backup of codebase."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"codey-v2-backup-{timestamp}.tar.gz"
    backup_path = Path.home() / backup_name
    
    # Files/dirs to exclude
    exclude_patterns = {
        '.pyc', '__pycache__', '.git', '*.gguf', 
        '.pytest_cache', '.qwen', 'model',
        'checkpoints', '*.log', '.DS_Store'
    }
    
    def filter_func(tarinfo):
        """Filter out unwanted files."""
        name = tarinfo.name
        # Skip excluded patterns
        for pattern in exclude_patterns:
            if pattern in name:
                return None
        # Skip large files (>100MB)
        if tarinfo.size > 100 * 1024 * 1024:
            return None
        return tarinfo
    
    # Create backup
    source_dir = Path(__file__).parent
    print(f"Creating backup of {source_dir}...")
    
    with tarfile.open(backup_path, "w:gz") as tar:
        tar.add(source_dir, arcname="codey-v2", filter=filter_func)
    
    size_mb = backup_path.stat().st_size / (1024 * 1024)
    print(f"✓ Backup created: {backup_path}")
    print(f"  Size: {size_mb:.2f} MB")
    print(f"  Timestamp: {timestamp}")
    
    return str(backup_path)

if __name__ == "__main__":
    create_backup()
