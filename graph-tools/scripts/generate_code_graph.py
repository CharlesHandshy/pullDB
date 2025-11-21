"""Generate a JSON graph of the Python codebase for visualization."""

import ast
import json
import os
import random
import string
import sys

# Configuration
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SRC_DIR = os.path.join(ROOT_DIR, 'pulldb')
OUTPUT_FILE = os.path.join(ROOT_DIR, 'graph-tools', 'web', 'data.json')


def generate_id(prefix):
    """Generate a random ID with a prefix."""
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=9))
    return f"{prefix}-{suffix}"


def get_docstring(node):
    """Extract docstring from an AST node."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
        return ast.get_docstring(node)
    return None


def process_node(node, source_lines, file_path):
    """Process a single AST node into a graph node."""
    name = getattr(node, 'name', None)
    node_type = None
    details = {}
    children = []

    if isinstance(node, ast.ClassDef):
        name = node.name
        node_type = 'class'
        # Bases
        bases = [ast.unparse(b) for b in node.bases]
        if bases:
            details['extends'] = ', '.join(bases)

        # Process class body for methods and properties
        class_members = []
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [a.arg for a in child.args.args]
                if 'self' in args:
                    args.remove('self')
                if 'cls' in args:
                    args.remove('cls')

                signature = f"({', '.join(args)})"
                returns = ast.unparse(child.returns) if child.returns else "None"

                class_members.append({
                    'name': child.name,
                    'type': f"{signature} -> {returns}",
                    'kind': 'method',
                    'doc': ast.get_docstring(child)
                })
            elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                class_members.append({
                    'name': child.target.id,
                    'type': ast.unparse(child.annotation),
                    'kind': 'property',
                    'doc': None
                })

        if class_members:
            details['classMembers'] = class_members

    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        name = node.name
        node_type = 'function'  # Will be refined to method if parent is class

        # Args
        args = []
        for arg in node.args.args:
            annotation = ast.unparse(arg.annotation) if arg.annotation else "Any"
            args.append({'name': arg.arg, 'type': annotation})

        return_type = ast.unparse(node.returns) if node.returns else "None"

        details['signature'] = {
            'parameters': args,
            'returnType': return_type
        }

    elif isinstance(node, ast.Assign):
        # Handle top-level variables
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            node_type = 'variable'
            # Try to infer type or value
            details['type'] = 'Any'  # Python doesn't always have explicit types on Assign

    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        name = node.target.id
        node_type = 'variable'
        details['type'] = ast.unparse(node.annotation)

    if not name or not node_type:
        return None

    # Common details
    doc = get_docstring(node)
    if doc:
        details['documentation'] = doc
        
        # Check for prototype/status indicators
        doc_lower = doc.lower()
        
        # Default status
        status = 'stable'
        
        # Danger keywords (Red)
        danger_keywords = ['deprecated', 'broken', 'will be replaced', 'legacy', 'obsolete', 'do not use']
        if any(keyword in doc_lower for keyword in danger_keywords):
            status = 'danger'
            
        # Warning keywords (Yellow)
        elif any(keyword in doc_lower for keyword in ['mock', 'placeholder', 'temporary', 'todo', 'wip', 'draft', 'experimental']):
            status = 'warning'
            
        details['status'] = status

    if hasattr(node, 'lineno'):
        details['line'] = node.lineno
        details['absolutePath'] = file_path

    # Recursion for nested structures (like classes containing methods)
    # But for the graph, we might want to flatten or group.
    # The TS script groups by category.

    child_nodes = []
    if hasattr(node, 'body') and isinstance(node.body, list):
        for child in node.body:
            processed = process_node(child, source_lines, file_path)
            if processed:
                # If we are in a class, functions become methods
                if node_type == 'class' and processed['type'] == 'function':
                    processed['type'] = 'method'
                child_nodes.append(processed)

    if child_nodes:
        # Group by category
        groups = {}
        for child in child_nodes:
            t = child['type']
            if t not in groups:
                groups[t] = []
            groups[t].append(child)

        grouped_children = []
        for t, nodes in groups.items():
            display_name = t.capitalize()
            if t == 'class':
                display_name = 'Classes'
            elif t == 'function':
                display_name = 'Functions'
            elif t == 'method':
                display_name = 'Methods'
            elif t == 'variable':
                display_name = 'Variables'

            grouped_children.append({
                'id': generate_id(f"category-{t}"),
                'name': display_name,
                'type': 'category',
                'children': nodes
            })
        children = grouped_children

    return {
        'id': generate_id(f"{node_type}-{name}"),
        'name': name,
        'type': node_type,
        'children': children if children else None,
        'details': details
    }


def process_file(file_path):
    """Parse a Python file and return a graph node."""
    try:
        with open(file_path, encoding='utf-8') as f:
            content = f.read()

        tree = ast.parse(content)
        source_lines = content.splitlines()

        children = []
        for node in tree.body:
            processed = process_node(node, source_lines, file_path)
            if processed:
                children.append(processed)

        # Group top-level items
        grouped_children = []
        if children:
            groups = {}
            for child in children:
                t = child['type']
                if t not in groups:
                    groups[t] = []
                groups[t].append(child)

            for t, nodes in groups.items():
                display_name = t.capitalize() + 's'
                if t == 'class':
                    display_name = 'Classes'
                elif t == 'function':
                    display_name = 'Functions'

                grouped_children.append({
                    'id': generate_id(f"category-{t}"),
                    'name': display_name,
                    'type': 'category',
                    'children': nodes
                })

        return {
            'id': generate_id(f"file-{os.path.basename(file_path)}"),
            'name': os.path.basename(file_path),
            'type': 'file',
            'children': grouped_children if grouped_children else None,
            'details': {
                'path': os.path.relpath(file_path, ROOT_DIR),
                'absolutePath': file_path
            }
        }
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return None


def process_directory(dir_path):
    """Recursively process a directory."""
    children = []
    try:
        for entry in os.scandir(dir_path):
            if entry.name.startswith('.') or entry.name == '__pycache__':
                continue

            if entry.is_dir():
                dir_node = process_directory(entry.path)
                if dir_node:
                    children.append(dir_node)
            elif entry.is_file() and entry.name.endswith('.py'):
                file_node = process_file(entry.path)
                if file_node:
                    children.append(file_node)
    except Exception as e:
        print(f"Error scanning directory {dir_path}: {e}")

    if not children:
        return None

    return {
        'id': generate_id(f"folder-{os.path.basename(dir_path)}"),
        'name': os.path.basename(dir_path),
        'type': 'folder',
        'children': children
    }


def main():
    """Execute the graph generation."""
    print(f"Scanning {SRC_DIR}...")
    root_children = process_directory(SRC_DIR)

    root_node = {
        'id': 'root',
        'name': 'pulldb',
        'type': 'root',
        'children': [root_children] if root_children else []
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(root_node, f, indent=2)

    print(f"Graph data written to {OUTPUT_FILE}")


if __name__ == '__main__':
    main()

