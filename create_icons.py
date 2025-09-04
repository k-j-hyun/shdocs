#!/usr/bin/env python3
"""
Create PNG icons from SVG using Pillow
"""

import os
from pathlib import Path
from PIL import Image, ImageDraw

def create_icon_png(size):
    """Create a PNG icon of specified size"""
    # Create a new image with RGBA mode (supports transparency)
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Calculate scaling factor
    scale = size / 512
    
    # Background circle (pink gradient approximation)
    center = size // 2
    radius = int(240 * scale)
    
    # Draw gradient background (simplified as solid color)
    draw.ellipse(
        [center - radius, center - radius, center + radius, center + radius],
        fill=(255, 107, 157, 255),  # #FF6B9D
        outline=(255, 255, 255, 255),
        width=max(1, int(8 * scale))
    )
    
    # Calendar body
    cal_width = int(256 * scale)
    cal_height = int(192 * scale)
    cal_x = int((size - cal_width) // 2)
    cal_y = int(160 * scale)
    
    # Calendar background
    draw.rectangle(
        [cal_x, cal_y, cal_x + cal_width, cal_y + cal_height],
        fill=(255, 255, 255, 240),
        outline=None
    )
    
    # Calendar header
    header_height = int(48 * scale)
    draw.rectangle(
        [cal_x, cal_y, cal_x + cal_width, cal_y + header_height],
        fill=(255, 255, 255, 255),
        outline=None
    )
    
    # Pink header line
    draw.rectangle(
        [cal_x, cal_y + int(32 * scale), cal_x + cal_width, cal_y + header_height],
        fill=(255, 107, 157, 255),
        outline=None
    )
    
    # Calendar rings
    ring_width = max(1, int(8 * scale))
    ring_height = int(32 * scale)
    ring_y = int(144 * scale)
    
    draw.rectangle(
        [cal_x + int(48 * scale), ring_y, cal_x + int(48 * scale) + ring_width, ring_y + ring_height],
        fill=(102, 102, 102, 255)
    )
    draw.rectangle(
        [cal_x + cal_width - int(56 * scale), ring_y, cal_x + cal_width - int(48 * scale), ring_y + ring_height],
        fill=(102, 102, 102, 255)
    )
    
    # Some calendar dots (events)
    dot_size = max(2, int(4 * scale))
    draw.ellipse(
        [cal_x + int(48 * scale) - dot_size, cal_y + int(64 * scale) - dot_size,
         cal_x + int(48 * scale) + dot_size, cal_y + int(64 * scale) + dot_size],
        fill=(255, 107, 157, 255)
    )
    
    # Sheets overlay (green rectangle)
    sheets_w = int(48 * scale)
    sheets_h = int(36 * scale)
    sheets_x = cal_x + cal_width - sheets_w - int(8 * scale)
    sheets_y = cal_y + cal_height - sheets_h - int(8 * scale)
    
    draw.rectangle(
        [sheets_x, sheets_y, sheets_x + sheets_w, sheets_y + sheets_h],
        fill=(52, 168, 83, 230),  # #34A853 with opacity
        outline=None
    )
    
    # Sheets lines
    line_width = int(40 * scale)
    line_height = max(1, int(4 * scale))
    for i in range(4):
        y_pos = sheets_y + int(8 * scale) + i * int(8 * scale)
        draw.rectangle(
            [sheets_x + int(4 * scale), y_pos, sheets_x + int(4 * scale) + line_width, y_pos + line_height],
            fill=(255, 255, 255, 200)
        )
    
    return img

def main():
    sizes = [72, 96, 128, 144, 152, 192, 384, 512]
    
    icons_dir = Path('static/icons')
    icons_dir.mkdir(exist_ok=True)
    
    print("Generating PNG icons...")
    for size in sizes:
        img = create_icon_png(size)
        png_path = icons_dir / f'icon-{size}x{size}.png'
        img.save(png_path, 'PNG')
        print(f"Generated: {png_path}")
    
    print("All PNG icons generated successfully!")

if __name__ == '__main__':
    main()