# pullDB Graph Tools

This directory contains visualization tools for the pullDB codebase and architecture.

## Tools

### 1. Code Graph Visualizer (`web/code.html`)
A 2D interactive tree graph of the Python codebase (`pulldb/` directory).
- **Visualizes**: Classes, methods, functions, variables, and their hierarchy.
- **Features**:
  - Color-coded nodes based on type (Class, Method, etc.).
  - Status indicators (Stable, Warning, Danger) based on docstrings.
  - Search functionality.
  - VS Code integration (links to open files).

### 2. Logical Flow Visualizer (`web/flow.html`)
A 3D directed acyclic graph (DAG) of the application's logical flow.
- **Visualizes**: The step-by-step process from CLI initiation to Worker execution and completion.
- **Features**:
  - 3D navigation (Rotate, Pan, Zoom).
  - Color-coded nodes (Start/End, Process, Decision, Failure).

## How to Run

1.  **Generate Data**:
    Run the generation scripts to parse the latest code and update the JSON data files.
    ```bash
    # From project root
    python3 graph-tools/scripts/generate_code_graph.py
    python3 graph-tools/scripts/generate_flow_graph.py
    ```

2.  **Start Web Server**:
    Serve the `web/` directory to view the visualizations.
    ```bash
    cd graph-tools/web
    python3 -m http.server 8081
    ```

3.  **View in Browser**:
    - Main Menu: [http://localhost:8081/](http://localhost:8081/)
    - Code Graph: [http://localhost:8081/code.html](http://localhost:8081/code.html)
    - Flow Graph: [http://localhost:8081/flow.html](http://localhost:8081/flow.html)

## Directory Structure

- `scripts/`: Python scripts to generate JSON data.
  - `generate_code_graph.py`: Parses `pulldb/` source code using AST.
  - `generate_flow_graph.py`: Generates static flow data based on architecture.
- `web/`: Frontend assets.
  - `index.html`: Main menu landing page.
  - `code.html`: D3.js visualization for the code graph.
  - `flow.html`: 3d-force-graph visualization for the flow graph.
  - `data.json`: Generated code graph data.
  - `flow_data.json`: Generated flow graph data.

## Updating the Tools

- **To update the Code Graph logic**: Edit `scripts/generate_code_graph.py`. You can modify how AST nodes are parsed or how status is determined.
- **To update the Flow Graph logic**: Edit `scripts/generate_flow_graph.py`. Add new nodes or links to reflect architectural changes.
- **To update the Visualization UI**: Edit `web/code.html` or `web/flow.html`. These contain the D3.js and 3d-force-graph logic respectively.
