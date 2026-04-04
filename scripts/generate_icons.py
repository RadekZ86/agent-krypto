"""
Generate PWA icons for Agent Krypto
Run: python scripts/generate_icons.py
"""
from PIL import Image, ImageDraw, ImageFont
import os

SIZES = [72, 96, 128, 144, 152, 192, 384, 512]
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'app', 'static', 'icons')

def generate_icon(size):
    # Create image with dark background
    img = Image.new('RGBA', (size, size), (8, 20, 27, 255))
    draw = ImageDraw.Draw(img)
    
    # Draw gradient-like background circle
    padding = size // 8
    circle_bbox = [padding, padding, size - padding, size - padding]
    
    # Outer glow
    for i in range(3):
        offset = i * 2
        draw.ellipse(
            [padding - offset, padding - offset, size - padding + offset, size - padding + offset],
            fill=(240, 180, 74, 30 - i * 10)
        )
    
    # Main circle with gradient effect
    draw.ellipse(circle_bbox, fill=(17, 38, 48, 255), outline=(240, 180, 74, 180), width=max(2, size // 64))
    
    # Draw "K" letter
    font_size = size // 2
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except:
            font = ImageFont.load_default()
    
    text = "K"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    x = (size - text_width) // 2
    y = (size - text_height) // 2 - bbox[1]
    
    # Text shadow
    draw.text((x + 2, y + 2), text, fill=(0, 0, 0, 100), font=font)
    # Main text with gold color
    draw.text((x, y), text, fill=(240, 180, 74, 255), font=font)
    
    # Add small crypto symbol
    small_size = size // 6
    center_x = size // 2
    bottom_y = size - padding - small_size
    
    # Bitcoin-like circle at bottom
    draw.ellipse(
        [center_x - small_size//2, bottom_y, center_x + small_size//2, bottom_y + small_size],
        fill=(79, 209, 166, 200)
    )
    
    return img

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    for size in SIZES:
        icon = generate_icon(size)
        output_path = os.path.join(OUTPUT_DIR, f'icon-{size}.png')
        icon.save(output_path, 'PNG')
        print(f'Generated: icon-{size}.png')
    
    # Also create apple-touch-icon
    apple_icon = generate_icon(180)
    apple_icon.save(os.path.join(OUTPUT_DIR, 'apple-touch-icon.png'), 'PNG')
    print('Generated: apple-touch-icon.png')
    
    # Favicon
    favicon = generate_icon(32)
    favicon.save(os.path.join(OUTPUT_DIR, 'favicon-32.png'), 'PNG')
    print('Generated: favicon-32.png')

if __name__ == '__main__':
    main()
