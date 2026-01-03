#!/usr/bin/env python3
"""
Build search index for pullDB Help documentation.

Parses HTML files in web/help/ and extracts content for fuzzy search.
Generates a JSON index file that can be loaded at runtime.

Usage:
    python scripts/build_help_search_index.py
"""

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


class HTMLTextExtractor(HTMLParser):
    """Extract text content from HTML, preserving structure for keywords."""
    
    def __init__(self):
        super().__init__()
        self.text = []
        self.title = ""
        self.description = ""
        self.keywords = []
        self._in_title = False
        self._in_h1 = False
        self._in_h2 = False
        self._in_code = False
        self._in_nav = False
        self._in_script = False
        self._in_style = False
        self._skip_tags = {'script', 'style', 'nav', 'svg', 'path', 'circle', 'rect'}
        self._current_tag_stack = []
    
    def handle_starttag(self, tag, attrs):
        self._current_tag_stack.append(tag)
        
        if tag in self._skip_tags:
            return
            
        if tag == 'title':
            self._in_title = True
        elif tag == 'h1':
            self._in_h1 = True
        elif tag == 'h2':
            self._in_h2 = True
        elif tag == 'code':
            self._in_code = True
        elif tag == 'nav':
            self._in_nav = True
        elif tag == 'script':
            self._in_script = True
        elif tag == 'style':
            self._in_style = True
            
        # Extract meta description
        if tag == 'meta':
            attrs_dict = dict(attrs)
            if attrs_dict.get('name') == 'description':
                self.description = attrs_dict.get('content', '')
    
    def handle_endtag(self, tag):
        if self._current_tag_stack and self._current_tag_stack[-1] == tag:
            self._current_tag_stack.pop()
            
        if tag == 'title':
            self._in_title = False
        elif tag == 'h1':
            self._in_h1 = False
        elif tag == 'h2':
            self._in_h2 = False
        elif tag == 'code':
            self._in_code = False
        elif tag == 'nav':
            self._in_nav = False
        elif tag == 'script':
            self._in_script = False
        elif tag == 'style':
            self._in_style = False
    
    def handle_data(self, data):
        # Skip content in nav, script, style
        if self._in_nav or self._in_script or self._in_style:
            return
            
        # Skip if we're inside a skip tag
        for tag in self._current_tag_stack:
            if tag in self._skip_tags:
                return
        
        text = data.strip()
        if not text:
            return
            
        if self._in_title:
            self.title = text.replace(' - pullDB Help', '')
        elif self._in_h1:
            if not self.title:
                self.title = text
        elif self._in_h2:
            self.keywords.append(text)
        elif self._in_code:
            self.keywords.append(text)
        else:
            self.text.append(text)
    
    def get_content(self):
        """Return extracted content as a single string."""
        return ' '.join(self.text)
    
    def get_keywords(self):
        """Return extracted keywords."""
        return list(set(self.keywords))


def extract_page_info(html_path: Path, base_path: Path) -> dict | None:
    """Extract searchable information from an HTML file."""
    try:
        content = html_path.read_text(encoding='utf-8')
    except Exception as e:
        print(f"  Warning: Could not read {html_path}: {e}", file=sys.stderr)
        return None
    
    parser = HTMLTextExtractor()
    try:
        parser.feed(content)
    except Exception as e:
        print(f"  Warning: Could not parse {html_path}: {e}", file=sys.stderr)
        return None
    
    # Get relative URL from help root
    relative_path = html_path.relative_to(base_path)
    url = str(relative_path)
    
    # Skip index.html if we want clean URLs (optional)
    # if url.endswith('/index.html'):
    #     url = url[:-10]  # Remove 'index.html'
    
    # Extract first meaningful paragraph for preview
    full_content = parser.get_content()
    
    # Clean up content - remove excessive whitespace
    full_content = re.sub(r'\s+', ' ', full_content)
    
    # Create preview (first ~200 chars)
    preview = full_content[:200].strip()
    if len(full_content) > 200:
        preview += '...'
    
    return {
        'id': url.replace('/', '-').replace('.html', ''),
        'url': url,
        'title': parser.title or html_path.stem.replace('-', ' ').title(),
        'keywords': parser.get_keywords()[:20],  # Limit keywords
        'content': full_content[:1000],  # Limit content for index size
        'preview': preview
    }


def build_search_index(help_dir: Path) -> list[dict]:
    """Build search index from all HTML files in help directory."""
    index = []
    
    # Find all HTML files
    html_files = list(help_dir.rglob('*.html'))
    print(f"Found {len(html_files)} HTML files")
    
    for html_file in sorted(html_files):
        print(f"  Processing: {html_file.relative_to(help_dir)}")
        page_info = extract_page_info(html_file, help_dir)
        if page_info:
            index.append(page_info)
    
    return index


def main():
    # Determine paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    help_dir = project_root / 'pulldb' / 'web' / 'help'
    output_file = help_dir / 'search-index.json'
    
    if not help_dir.exists():
        print(f"Error: Help directory not found: {help_dir}", file=sys.stderr)
        sys.exit(1)
    
    print(f"Building search index from: {help_dir}")
    
    # Build index
    index = build_search_index(help_dir)
    
    if not index:
        print("Warning: No pages found for index", file=sys.stderr)
        sys.exit(1)
    
    # Write output
    output_data = {
        'version': '1.0',
        'generated': str(Path(__file__).name),
        'pages': index
    }
    
    output_file.write_text(
        json.dumps(output_data, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )
    
    print(f"\nGenerated search index with {len(index)} pages")
    print(f"Output: {output_file}")
    
    # Print summary
    print("\nIndexed pages:")
    for page in index:
        print(f"  - {page['title']} ({page['url']})")


if __name__ == '__main__':
    main()
