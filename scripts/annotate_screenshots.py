#!/usr/bin/env python3
"""
Annotate help screenshots with numbered circles and legends.

Reads annotation coordinates from a YAML config file and draws
numbered circles at specified positions on screenshots. Generates
annotated versions with a legend showing what each number means.

Usage:
    python scripts/annotate_screenshots.py
    python scripts/annotate_screenshots.py --config custom.yaml
    python scripts/annotate_screenshots.py --input screenshots/light --output screenshots/annotated/light

Requirements:
    pip install pillow pyyaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None  # type: ignore[assignment,misc]
    ImageDraw = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]

# Project root
PROJECT_ROOT = Path(__file__).parent.parent


def load_config(config_path: Path) -> dict[str, Any]:
    """Load annotation configuration from YAML file."""
    if yaml is None:
        print("ERROR: pyyaml not installed. Run: pip install pyyaml")
        sys.exit(1)
    
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}")
        sys.exit(1)
    
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Get a font for drawing text, with fallbacks."""
    # Try common system fonts
    font_names = [
        "DejaVuSans-Bold.ttf",
        "Arial-Bold.ttf",
        "Helvetica-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    
    for font_name in font_names:
        try:
            return ImageFont.truetype(font_name, size)
        except (OSError, IOError):
            continue
    
    # Fall back to default font
    return ImageFont.load_default()


def annotate_image(
    image_path: Path,
    output_path: Path,
    annotations: list[dict[str, Any]],
    config: dict[str, Any],
) -> bool:
    """
    Annotate a single image with numbered circles and a legend.
    
    Args:
        image_path: Path to source screenshot
        output_path: Path to save annotated version
        annotations: List of annotation dicts with x, y, label
        config: Global config with circle_radius, colors, etc.
    
    Returns:
        True if successful, False otherwise
    """
    if Image is None:
        print("ERROR: Pillow not installed. Run: pip install pillow")
        sys.exit(1)
    
    if not image_path.exists():
        print(f"  Skipping (not found): {image_path}")
        return False
    
    # Load image
    try:
        img = Image.open(image_path).convert("RGBA")
    except Exception as e:
        print(f"  Error loading {image_path}: {e}")
        return False
    
    # Create overlay for annotations
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    # Get config values
    radius = config.get("circle_radius", 16)
    circle_color = hex_to_rgb(config.get("circle_color", "#E53935"))
    text_color = hex_to_rgb(config.get("text_color", "#FFFFFF"))
    
    # Font for numbers in circles
    font_size = int(radius * 1.2)
    font = get_font(font_size)
    
    # Draw numbered circles
    for i, annotation in enumerate(annotations, 1):
        x = annotation["x"]
        y = annotation["y"]
        
        # Draw circle with slight transparency
        circle_rgba = (*circle_color, 230)
        draw.ellipse(
            [x - radius, y - radius, x + radius, y + radius],
            fill=circle_rgba,
            outline=(*circle_color, 255),
            width=2,
        )
        
        # Draw number centered in circle
        number = str(i)
        # Get text bounding box for centering
        bbox = draw.textbbox((0, 0), number, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        text_x = x - text_width // 2
        text_y = y - text_height // 2 - 2  # Slight adjustment for visual centering
        
        draw.text((text_x, text_y), number, fill=(*text_color, 255), font=font)
    
    # Composite overlay onto image
    img = Image.alpha_composite(img, overlay)
    
    # Add legend at bottom
    legend_height = 30 + len(annotations) * 24
    legend_padding = 16
    
    # Create new image with legend space
    new_height = img.height + legend_height
    final_img = Image.new("RGBA", (img.width, new_height), (255, 255, 255, 255))
    final_img.paste(img, (0, 0))
    
    # Draw legend background
    legend_draw = ImageDraw.Draw(final_img)
    legend_y_start = img.height
    legend_draw.rectangle(
        [0, legend_y_start, img.width, new_height],
        fill=(248, 250, 252, 255),  # Light gray background
    )
    
    # Draw legend title
    legend_font = get_font(14)
    title_font = get_font(16)
    legend_draw.text(
        (legend_padding, legend_y_start + 8),
        "Annotations:",
        fill=(30, 41, 59, 255),
        font=title_font,
    )
    
    # Draw legend items
    y_offset = legend_y_start + 32
    for i, annotation in enumerate(annotations, 1):
        label = annotation.get("label", "")
        legend_text = f"{i}. {label}"
        legend_draw.text(
            (legend_padding + 8, y_offset),
            legend_text,
            fill=(71, 85, 105, 255),
            font=legend_font,
        )
        y_offset += 24
    
    # Save annotated image
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_img.convert("RGB").save(output_path, "PNG", optimize=True)
    
    return True


def process_screenshots(
    config: dict[str, Any],
    input_dir: Path,
    output_dir: Path,
) -> tuple[int, int]:
    """
    Process all screenshots defined in config.
    
    Args:
        config: Annotation configuration
        input_dir: Directory containing source screenshots
        output_dir: Directory for annotated output
    
    Returns:
        Tuple of (success_count, skip_count)
    """
    screenshots = config.get("screenshots", {})
    
    if not screenshots:
        print("No screenshots defined in config")
        return 0, 0
    
    success_count = 0
    skip_count = 0
    
    for rel_path, annotations in screenshots.items():
        if not annotations:
            continue
        
        input_path = input_dir / rel_path
        output_path = output_dir / rel_path
        
        print(f"Processing: {rel_path}")
        
        if annotate_image(input_path, output_path, annotations, config):
            success_count += 1
            print(f"  ✓ Saved: {output_path}")
        else:
            skip_count += 1
    
    return success_count, skip_count


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Annotate help screenshots with numbered circles and legends",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "docs" / "help-screenshot-annotations.yaml",
        help="Path to YAML config file",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "pulldb" / "web" / "help" / "screenshots" / "light",
        help="Input directory containing screenshots",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "pulldb" / "web" / "help" / "screenshots" / "annotated" / "light",
        help="Output directory for annotated screenshots",
    )
    
    args = parser.parse_args()
    
    # Check dependencies
    if yaml is None:
        print("ERROR: pyyaml not installed. Run: pip install pyyaml")
        return 1
    
    if Image is None:
        print("ERROR: Pillow not installed. Run: pip install pillow")
        return 1
    
    print(f"Loading config: {args.config}")
    config = load_config(args.config)
    
    print(f"Input directory: {args.input}")
    print(f"Output directory: {args.output}")
    print()
    
    success, skipped = process_screenshots(config, args.input, args.output)
    
    print()
    print(f"Done! Processed: {success}, Skipped: {skipped}")
    
    return 0 if success > 0 or skipped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
