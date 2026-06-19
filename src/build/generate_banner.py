#!/usr/bin/env python3
# ==============================================================================
# GDC Boot Banner Generator
# ==============================================================================
# Generates the custom GDC vintage parchment boot banner containing the 
# ISO build version and compilation timestamp.
# ==============================================================================

import sys
from datetime import datetime

def generate_boot_text(version: str, timestamp: datetime = None) -> str:
    """Generates the GDC Software ASCII logo wrapped in a vintage parchment frame
    with the 'Version' and 'Created On' lines perfectly aligned at the colon 
    and centered as a block within the inner workspace.
    
    Args:
        version (str): The version string passed in at ISO build time.
        timestamp (datetime): Optional datetime object. Defaults to current system time.
    
    Returns:
        str: Fully formatted, line-break separated ASCII screen text.
    """
    if timestamp is None:
        timestamp = datetime.now()
        
    # Format the dynamic timestamps and strings
    tz_str = timestamp.astimezone().tzname() or "UTC"
    date_val = f" {timestamp.strftime('%Y-%m-%d %H:%M')} {tz_str}"
    version_val = f" {version}"
    
    key1, val1 = "Version:", version_val
    key2, val2 = "Created On:", date_val
    
    # Pad the keys and values so the colons line up perfectly
    max_key_len = max(len(key1), len(key2))
    max_val_len = max(len(val1), len(val2))
    
    line1_content = f"{key1.rjust(max_key_len)}{val1.ljust(max_val_len)}"
    line2_content = f"{key2.rjust(max_key_len)}{val2.ljust(max_val_len)}"
    
    # Calculate perfect block centering within the inner 66-character text area
    inner_width = 66
    block_width = len(line1_content)
    
    # Total padding needed for the block
    total_padding = inner_width - block_width
    left_pad = total_padding // 2
    right_pad = total_padding - left_pad
    
    # Apply the block padding to both lines
    centered_version = (" " * left_pad) + line1_content + (" " * right_pad)
    centered_date = (" " * left_pad) + line2_content + (" " * right_pad)

    # The static upper frame and GDC Software logo art
    logo_block = [
        "__| |__________________________________________________________________| |__",
        "__   __________________________________________________________________   __",
        "  | |                                                                  | |  ",
        "  | |                                                                  | |  ",
        "  | |    ______  ______      ______                                    | |  ",
        "  | |  .' ___  ||_   _ `.  .' ___  |                                   | |  ",
        "  | | / .'   \\_|  | | `. \\/ .'   \\_|                                   | |  ",
        "  | | | |    ____  | |  | || |                                         | |  ",
        "  | | \\ `.___]  |_| |_.' /\\ `.___.'\\                                   | |  ",
        "  | |  `._____.'|______.'  `.____ .'                                   | |  ",
        "  | |  ______             ___  _                                       | |  ",
        "  | | .' ____ \\          .' ..]/ |_                                    | |  ",
        "  | | | (___ \\_|  .--.   _| |_ `| |-'_   _   __  ,--.   _ .--.  .---.  | |  ",
        "  | |  _.____`. / .'`\\ \\'-| |-' | | [ \\ [ \\ [  ]`'_\\ : [ `/'`\\]/ /__\\\\ | |  ",
        "  | | | \\____) || \\__. |  | |   | |, \\ \\/\\ \\/ / // | |, | |     | \\__., | |  ",
        "  | |  \\______.' '.__.'  [___]  \\__/  \\__/\\__/  \\'-;__/[___]    '.__.' | |  ",
        "  | |                                                                  | |  "
    ]
    
    # Construct the dynamic middle rows
    version_line = f"  | |{centered_version}| |  "
    date_line = f"  | |{centered_date}| |  "
    
    # The closing frame assets
    footer_block = [
        "__| |__________________________________________________________________| |__",
        "__   __________________________________________________________________   __",
        "  | |                                                                  | |  "
    ]
    
    full_screen = logo_block + [version_line, date_line] + footer_block
    
    return "\n".join(full_screen) + "\n"

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: generate_banner.py <output_file_path> <version>")
        sys.exit(1)
        
    output_path = sys.argv[1]
    version = sys.argv[2]
    
    banner = generate_boot_text(version)
    with open(output_path, "w") as f:
        f.write(banner)
    
    print(f"[-] Successfully generated build banner at {output_path}")
