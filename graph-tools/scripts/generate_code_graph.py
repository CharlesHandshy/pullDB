"""Generate a JSON graph of the Python codebase for visualization."""

from __future__ import annotations

import ast
import json
import os
import random
import string
from typing import Any, cast


# Configuration
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(ROOT_DIR, "pulldb")
OUTPUT_FILE = os.path.join(ROOT_DIR, "graph-tools", "web", "data.json")


def generate_id(prefix: str) -> str:
    """Generate a random ID with a prefix."""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=9))
    return f"{prefix}-{suffix}"


def get_docstring(node: ast.AST) -> str | None:
    """Extract docstring from an AST node."""
    if isinstance(
        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)
    ):
        return ast.get_docstring(node)
    return None


def _process_class_def(node: ast.ClassDef) -> dict[str, Any]:
    """Process a ClassDef node."""
    name = node.name
    node_type = "class"
    details: dict[str, Any] = {}

    # Bases
    bases = [ast.unparse(b) for b in node.bases]
    if bases:
        details["extends"] = ", ".join(bases)

    # Process class body for methods and properties
    class_members: list[dict[str, Any]] = []
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in child.args.args]
            if "self" in args:
                args.remove("self")
            if "cls" in args:
                args.remove("cls")

            signature = f"({', '.join(args)})"
            returns = ast.unparse(child.returns) if child.returns else "None"

            class_members.append(
                {
                    "name": child.name,
                    "type": f"{signature} -> {returns}",
                    "kind": "method",
                    "doc": ast.get_docstring(child),
                }
            )
        elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            class_members.append(
                {
                    "name": child.target.id,
                    "type": ast.unparse(child.annotation),
                    "kind": "property",
                    "doc": None,
                }
            )

    if class_members:
        details["classMembers"] = class_members

    return {"name": name, "type": node_type, "details": details}


def _process_function_def(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, Any]:
    """Process a FunctionDef or AsyncFunctionDef node."""
    name = node.name
    node_type = "function"  # Will be refined to method if parent is class
    details: dict[str, Any] = {}

    # Args
    args: list[dict[str, str]] = []
    for arg in node.args.args:
        annotation = ast.unparse(arg.annotation) if arg.annotation else "Any"
        args.append({"name": arg.arg, "type": annotation})

    return_type = ast.unparse(node.returns) if node.returns else "None"

    details["signature"] = {"parameters": args, "returnType": return_type}

    return {"name": name, "type": node_type, "details": details}


def _process_assign(node: ast.Assign) -> dict[str, Any] | None:
    """Process an Assign node."""
    # Handle top-level variables
    if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        name = node.targets[0].id
        node_type = "variable"
        # Try to infer type or value
        details = {"type": "Any"}  # Python doesn't always have explicit types on Assign
        return {"name": name, "type": node_type, "details": details}
    return None


def _process_ann_assign(node: ast.AnnAssign) -> dict[str, Any] | None:
    """Process an AnnAssign node."""
    if isinstance(node.target, ast.Name):
        name = node.target.id
        node_type = "variable"
        details = {"type": ast.unparse(node.annotation)}
        return {"name": name, "type": node_type, "details": details}
    return None


def _enrich_details_with_doc(node: ast.AST, details: dict[str, Any]) -> None:
    """Add documentation and status to details."""
    doc = get_docstring(node)
    if doc:
        details["documentation"] = doc

        # Check for prototype/status indicators
        doc_lower = doc.lower()

        # Default status
        status = "stable"

        # Danger keywords (Red)
        danger_keywords = [
            "deprecated",
            "broken",
            "will be replaced",
            "legacy",
            "obsolete",
            "do not use",
        ]
        if any(keyword in doc_lower for keyword in danger_keywords):
            status = "danger"

        # Warning keywords (Yellow)
        elif any(
            keyword in doc_lower
            for keyword in [
                "mock",
                "placeholder",
                "temporary",
                "todo",
                "wip",
                "draft",
                "experimental",
            ]
        ):
            status = "warning"

        details["status"] = status


def _process_children(
    node: ast.AST,
    node_type: str,
    source_lines: list[str],
    file_path: str,
) -> list[dict[str, Any]]:
    """Process child nodes and group them."""
    child_nodes: list[dict[str, Any]] = []

    # Check if node has body attribute (ClassDef, FunctionDef, Module, etc.)
    raw_body = getattr(node, "body", [])
    if isinstance(raw_body, list):
        body = cast(list[ast.AST], raw_body)
        for child in body:
            processed = process_node(child, source_lines, file_path)
            if processed:
                # If we are in a class, functions become methods
                if node_type == "class" and processed["type"] == "function":
                    processed["type"] = "method"
                child_nodes.append(processed)

    children: list[dict[str, Any]] = []
    if child_nodes:
        # Group by category
        groups: dict[str, list[dict[str, Any]]] = {}
        for child_dict in child_nodes:
            t = child_dict["type"]
            if t not in groups:
                groups[t] = []
            groups[t].append(child_dict)

        display_map = {
            "class": "Classes",
            "function": "Functions",
            "method": "Methods",
            "variable": "Variables",
        }

        for t, nodes in groups.items():
            display_name = display_map.get(t, t.capitalize())
            children.append(
                {
                    "id": generate_id(f"category-{t}"),
                    "name": display_name,
                    "type": "category",
                    "children": nodes,
                }
            )
    return children


def process_node(
    node: ast.AST, source_lines: list[str], file_path: str
) -> dict[str, Any] | None:
    """Process a single AST node into a graph node."""
    result: dict[str, Any] | None = None

    if isinstance(node, ast.ClassDef):
        result = _process_class_def(node)
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        result = _process_function_def(node)
    elif isinstance(node, ast.Assign):
        result = _process_assign(node)
    elif isinstance(node, ast.AnnAssign):
        result = _process_ann_assign(node)

    if not result:
        return None

    name = result["name"]
    node_type = result["type"]
    details = result["details"]

    _enrich_details_with_doc(node, details)

    lineno = getattr(node, "lineno", None)
    if isinstance(lineno, int):
        details["line"] = lineno
        details["absolutePath"] = file_path

    children = _process_children(node, node_type, source_lines, file_path)

    return {
        "id": generate_id(f"{node_type}-{name}"),
        "name": name,
        "type": node_type,
        "children": children if children else None,
        "details": details,
    }


def process_file(file_path: str) -> dict[str, Any] | None:
    """Parse a Python file and return a graph node."""
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        tree = ast.parse(content)
        source_lines = content.splitlines()

        children: list[dict[str, Any]] = []
        for node in tree.body:
            processed = process_node(node, source_lines, file_path)
            if processed:
                children.append(processed)

        # Group top-level items
        grouped_children: list[dict[str, Any]] = []
        if children:
            groups: dict[str, list[dict[str, Any]]] = {}
            for child in children:
                t = child["type"]
                if t not in groups:
                    groups[t] = []
                groups[t].append(child)

            for t, nodes in groups.items():
                display_name = t.capitalize() + "s"
                if t == "class":
                    display_name = "Classes"
                elif t == "function":
                    display_name = "Functions"

                grouped_children.append(
                    {
                        "id": generate_id(f"category-{t}"),
                        "name": display_name,
                        "type": "category",
                        "children": nodes,
                    }
                )

        return {
            "id": generate_id(f"file-{os.path.basename(file_path)}"),
            "name": os.path.basename(file_path),
            "type": "file",
            "children": grouped_children if grouped_children else None,
            "details": {
                "path": os.path.relpath(file_path, ROOT_DIR),
                "absolutePath": file_path,
            },
        }
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return None


def process_directory(dir_path: str) -> dict[str, Any] | None:
    """Recursively process a directory."""
    children: list[dict[str, Any]] = []
    try:
        for entry in os.scandir(dir_path):
            if entry.name.startswith(".") or entry.name == "__pycache__":
                continue

            if entry.is_dir():
                dir_node = process_directory(entry.path)
                if dir_node:
                    children.append(dir_node)
            elif entry.is_file() and entry.name.endswith(".py"):
                file_node = process_file(entry.path)
                if file_node:
                    children.append(file_node)
    except Exception as e:
        print(f"Error scanning directory {dir_path}: {e}")

    if not children:
        return None

    return {
        "id": generate_id(f"folder-{os.path.basename(dir_path)}"),
        "name": os.path.basename(dir_path),
        "type": "folder",
        "children": children,
    }


def main() -> None:
    """Execute the graph generation."""
    print(f"Scanning {SRC_DIR}...")
    root_children = process_directory(SRC_DIR)

    root_node: dict[str, Any] = {
        "id": "root",
        "name": "pulldb",
        "type": "root",
        "children": [root_children] if root_children else [],
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(root_node, f, indent=2)

    print(f"Graph data written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
