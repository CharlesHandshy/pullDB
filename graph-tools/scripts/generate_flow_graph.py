import json
import os
from typing import Any


# Configuration
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUTPUT_FILE = os.path.join(ROOT_DIR, "graph-tools", "web", "flow_data.json")


class FlowGenerator:
    """Generates Cytoscape flow data for pullDB architecture."""

    def __init__(self) -> None:
        """Initialize the generator with empty views."""
        self.views: dict[str, list[dict[str, Any]]] = {
            "main": [],
            "cli": [],
            "worker": [],
            "infra": [],
            # Level 2 Views
            "cli_parse": [],
            "w_down": [],
            "w_s3": [],
            "w_restore": [],
            "w_post": [],
            # Level 3 Views
            "cp_sanitize": [],
            "s3_regex": [],
            "wd_stream": [],
            "wr_cmd": [],
            "cp_tokens": [],
            "s3_schema": [],
            "wd_check": [],
            "wr_mon": [],
            "cli_creds": [],
            # New Level 2 (Missing)
            "w_rename": [],
            # New Level 3 (Expanded)
            "rn_call": [],
            "wp_run": [],
            "cli_config": [],
            "s3_list": [],
        }

    def add_node(
        self, view: str, node_id: str, label: str, node_type: str, description: str = ""
    ) -> None:
        """Add a node to a specific view."""
        self.views[view].append(
            {
                "data": {
                    "id": node_id,
                    "label": label,
                    "type": node_type,
                    "description": description,
                }
            }
        )

    def add_edge(self, view: str, source: str, target: str, label: str = "") -> None:
        """Add an edge to a specific view."""
        self.views[view].append(
            {"data": {"source": source, "target": target, "label": label}}
        )

    def build_main_view(self) -> None:
        """Build the high-level architecture view."""
        self.add_node(
            "main",
            "cli",
            "CLI Client",
            "process",
            "User Interface & Job Submission",
        )
        self.add_node(
            "main",
            "worker",
            "Worker Service",
            "process",
            "Job Execution Daemon",
        )
        self.add_node(
            "main",
            "infra",
            "Infrastructure",
            "database",
            "Storage & State",
        )

        self.add_edge("main", "cli", "infra", "Enqueue / Config")
        self.add_edge("main", "worker", "infra", "Poll / Restore")

    def build_cli_view(self) -> None:
        """Build the CLI detailed view."""
        self.add_node("cli", "cli_start", "Start", "start", "User runs pullDB command")
        self.add_node(
            "cli",
            "cli_parse",
            "Parse Args",
            "process",
            "Validate inputs & generate user_code",
        )
        self.add_node(
            "cli",
            "cli_config",
            "Load Config",
            "process",
            "Env vars + Parameter Store",
        )
        self.add_node(
            "cli",
            "cli_creds",
            "Resolve Creds",
            "decision",
            "Secrets Manager / SSM",
        )
        self.add_node("cli", "cli_db", "MySQL", "database", "Check Host Capacity")
        self.add_node(
            "cli", "cli_enqueue", "Enqueue Job", "process", "Insert into jobs table"
        )
        self.add_node("cli", "cli_end", "Exit", "end", "Return status to user")

        self.add_edge("cli", "cli_start", "cli_parse", "")
        self.add_edge("cli", "cli_parse", "cli_config", "Valid")
        self.add_edge("cli", "cli_config", "cli_creds", "")
        self.add_edge("cli", "cli_creds", "cli_db", "Auth OK")
        self.add_edge("cli", "cli_db", "cli_enqueue", "Capacity OK")
        self.add_edge("cli", "cli_enqueue", "cli_end", "Job ID")

    def build_worker_view(self) -> None:
        """Build the Worker detailed view."""
        self.add_node("worker", "w_start", "Service Start", "start", "Daemon Init")
        self.add_node(
            "worker", "w_loop", "Poll Loop", "process", "Check for 'queued' jobs"
        )
        self.add_node("worker", "w_found", "Job Found?", "decision", "")
        self.add_node(
            "worker", "w_claim", "Claim Job", "process", "Set status='running'"
        )
        self.add_node("worker", "w_s3", "S3 Discovery", "process", "Find latest backup")
        self.add_node("worker", "w_space", "Disk Check", "decision", "Is space > 1.8x?")
        self.add_node("worker", "w_down", "Download", "process", "Stream from S3")
        self.add_node("worker", "w_restore", "Restore", "process", "myloader execution")
        self.add_node("worker", "w_post", "Post-SQL", "process", "Sanitization Scripts")
        self.add_node(
            "worker",
            "w_rename",
            "Atomic Rename",
            "process",
            "Swap Staging -> Prod",
        )
        self.add_node("worker", "w_end", "Complete", "end", "Update status='complete'")

        self.add_edge("worker", "w_start", "w_loop", "")
        self.add_edge("worker", "w_loop", "w_found", "")
        self.add_edge("worker", "w_found", "w_loop", "No Job")
        self.add_edge("worker", "w_found", "w_claim", "Yes")
        self.add_edge("worker", "w_claim", "w_s3", "")
        self.add_edge("worker", "w_s3", "w_space", "Backup Found")
        self.add_edge("worker", "w_space", "w_down", "Yes")
        self.add_edge("worker", "w_down", "w_restore", "Stream OK")
        self.add_edge("worker", "w_restore", "w_post", "Success")
        self.add_edge("worker", "w_post", "w_rename", "Scripts OK")
        self.add_edge("worker", "w_rename", "w_end", "Done")

    def build_infra_view(self) -> None:
        """Build the Infrastructure detailed view."""
        self.add_node(
            "infra",
            "i_mysql",
            "MySQL RDS",
            "database",
            "Coordination & Target DBs",
        )
        self.add_node(
            "infra",
            "i_s3",
            "S3 Buckets",
            "database",
            "Backups (Prod/Staging)",
        )
        self.add_node(
            "infra",
            "i_secrets",
            "Secrets Manager",
            "database",
            "DB Credentials",
        )
        self.add_node(
            "infra",
            "i_ssm",
            "Parameter Store",
            "database",
            "Config Values",
        )

        self.add_edge("infra", "i_secrets", "i_mysql", "Auth")
        self.add_edge("infra", "i_ssm", "i_mysql", "Config")

    def build_cli_parse_view(self) -> None:
        """Build Level 2: CLI Argument Parsing."""
        view = "cli_parse"
        self.add_node(view, "cp_start", "Start Parse", "start", "Input: Raw Tokens")
        self.add_node(
            view, "cp_user", "Check user=", "decision", "First token must be user=..."
        )
        self.add_node(
            view, "cp_sanitize", "Sanitize", "process", "Lowercase, letters only"
        )
        self.add_node(view, "cp_len", "Length Check", "decision", "Must be >= 6 chars")
        self.add_node(
            view, "cp_tokens", "Tokenize Rest", "process", "Loop through remaining args"
        )
        self.add_node(
            view, "cp_cust_qa", "Cust vs QA", "decision", "Exactly one required"
        )
        self.add_node(
            view, "cp_target", "Form Target", "process", "user_code + customer_id"
        )
        self.add_node(
            view, "cp_t_len", "Target Length", "decision", "Must be <= 51 chars"
        )
        self.add_node(
            view, "cp_return", "Return Options", "end", "Valid RestoreCLIOptions"
        )

        self.add_edge(view, "cp_start", "cp_user", "")
        self.add_edge(view, "cp_user", "cp_sanitize", "Found")
        self.add_edge(view, "cp_sanitize", "cp_len", "")
        self.add_edge(view, "cp_len", "cp_tokens", ">= 6")
        self.add_edge(view, "cp_tokens", "cp_cust_qa", "")
        self.add_edge(view, "cp_cust_qa", "cp_target", "Valid")
        self.add_edge(view, "cp_target", "cp_t_len", "")
        self.add_edge(view, "cp_t_len", "cp_return", "<= 51")

    def build_worker_s3_view(self) -> None:
        """Build Level 2: S3 Discovery."""
        view = "w_s3"
        self.add_node(
            view, "s3_start", "Start Discovery", "start", "Input: Target Name"
        )
        self.add_node(view, "s3_list", "List Objects", "process", "s3.list_objects_v2")
        self.add_node(
            view, "s3_filter", "Filter Prefix", "process", "daily/prod/{target}"
        )
        self.add_node(
            view, "s3_regex", "Parse Filenames", "process", "Extract Date & Type"
        )
        self.add_node(view, "s3_sort", "Sort by Date", "process", "Descending Order")
        self.add_node(
            view,
            "s3_schema",
            "Schema Exists?",
            "decision",
            "Check *-schema-create.sql.zst",
        )
        self.add_node(view, "s3_return", "Return Spec", "end", "Latest Valid Backup")

        self.add_edge(view, "s3_start", "s3_list", "")
        self.add_edge(view, "s3_list", "s3_filter", "")
        self.add_edge(view, "s3_filter", "s3_regex", "")
        self.add_edge(view, "s3_regex", "s3_sort", "")
        self.add_edge(view, "s3_sort", "s3_schema", "Top Candidate")
        self.add_edge(view, "s3_schema", "s3_return", "Yes")

    def build_worker_download_view(self) -> None:
        """Build Level 2: Download Logic."""
        view = "w_down"
        self.add_node(view, "wd_start", "Start Download", "start", "Input: BackupSpec")
        self.add_node(view, "wd_mkdir", "Ensure Dir", "process", "os.makedirs(dest)")
        self.add_node(view, "wd_calc", "Calc Required", "process", "size * 1.8")
        self.add_node(
            view, "wd_check", "Disk Space?", "decision", "shutil.disk_usage > required"
        )
        self.add_node(view, "wd_get", "S3 GetObject", "process", "boto3 get_object")
        self.add_node(view, "wd_stream", "Stream Loop", "process", "Read 8MB chunks")
        self.add_node(view, "wd_write", "Write File", "process", "Write to disk")
        self.add_node(view, "wd_prog", "Log Progress?", "decision", "Every 64MB")
        self.add_node(view, "wd_done", "Download Complete", "end", "Return file path")

        self.add_edge(view, "wd_start", "wd_mkdir", "")
        self.add_edge(view, "wd_mkdir", "wd_calc", "")
        self.add_edge(view, "wd_calc", "wd_check", "")
        self.add_edge(view, "wd_check", "wd_get", "Space OK")
        self.add_edge(view, "wd_get", "wd_stream", "Body Stream")
        self.add_edge(view, "wd_stream", "wd_write", "Chunk")
        self.add_edge(view, "wd_write", "wd_prog", "")
        self.add_edge(view, "wd_prog", "wd_stream", "Next Chunk")
        self.add_edge(view, "wd_prog", "wd_done", "EOF")

    def build_worker_restore_view(self) -> None:
        """Build Level 2: Restore Execution."""
        view = "w_restore"
        self.add_node(view, "wr_start", "Start Restore", "start", "Input: Tar Path")
        self.add_node(view, "wr_cmd", "Build Command", "process", "myloader --user ...")
        self.add_node(view, "wr_env", "Set Env", "process", "MYSQL_PWD=...")
        self.add_node(view, "wr_exec", "Execute", "process", "subprocess.Popen")
        self.add_node(view, "wr_mon", "Monitor", "process", "Read stdout/stderr")
        self.add_node(view, "wr_wait", "Wait", "decision", "proc.wait()")
        self.add_node(view, "wr_check", "Exit Code", "decision", "== 0?")
        self.add_node(view, "wr_end", "Success", "end", "Return True")

        self.add_edge(view, "wr_start", "wr_cmd", "")
        self.add_edge(view, "wr_cmd", "wr_env", "")
        self.add_edge(view, "wr_env", "wr_exec", "")
        self.add_edge(view, "wr_exec", "wr_mon", "")
        self.add_edge(view, "wr_mon", "wr_wait", "")
        self.add_edge(view, "wr_wait", "wr_check", "Done")
        self.add_edge(view, "wr_check", "wr_end", "Yes")

    def build_worker_post_sql_view(self) -> None:
        """Build Level 2: Post-SQL Execution."""
        view = "w_post"
        self.add_node(view, "wp_start", "Start Post-SQL", "start", "Input: DB Name")
        self.add_node(view, "wp_list", "List Scripts", "process", "glob(*.sql)")
        self.add_node(view, "wp_sort", "Sort", "process", "Lexicographical")
        self.add_node(view, "wp_loop", "Loop Scripts", "process", "For each script")
        self.add_node(view, "wp_read", "Read SQL", "process", "Read file content")
        self.add_node(view, "wp_run", "Execute", "process", "cursor.execute(sql)")
        self.add_node(view, "wp_log", "Log Result", "process", "Record success/fail")
        self.add_node(view, "wp_next", "Next?", "decision", "More scripts?")
        self.add_node(view, "wp_end", "Complete", "end", "Return Report")

        self.add_edge(view, "wp_start", "wp_list", "")
        self.add_edge(view, "wp_list", "wp_sort", "")
        self.add_edge(view, "wp_sort", "wp_loop", "")
        self.add_edge(view, "wp_loop", "wp_read", "")
        self.add_edge(view, "wp_read", "wp_run", "")
        self.add_edge(view, "wp_run", "wp_log", "")
        self.add_edge(view, "wp_log", "wp_next", "")
        self.add_edge(view, "wp_next", "wp_loop", "Yes")
        self.add_edge(view, "wp_next", "wp_end", "No")

    def build_cli_sanitize_view(self) -> None:
        """Build Level 3: CLI Sanitization."""
        view = "cp_sanitize"
        self.add_node(view, "cs_start", "Start Sanitize", "start", "Input: String")
        self.add_node(view, "cs_lower", "Lowercase", "process", "str.lower()")
        self.add_node(view, "cs_loop", "Loop Chars", "process", "For each char")
        self.add_node(view, "cs_check", "Is Alpha?", "decision", "char.isalpha()")
        self.add_node(view, "cs_keep", "Keep", "process", "Append to result")
        self.add_node(view, "cs_skip", "Skip", "process", "Ignore char")
        self.add_node(view, "cs_join", "Join", "process", "''.join(result)")
        self.add_node(view, "cs_end", "Return", "end", "Sanitized String")

        self.add_edge(view, "cs_start", "cs_lower", "")
        self.add_edge(view, "cs_lower", "cs_loop", "")
        self.add_edge(view, "cs_loop", "cs_check", "")
        self.add_edge(view, "cs_check", "cs_keep", "Yes")
        self.add_edge(view, "cs_check", "cs_skip", "No")
        self.add_edge(view, "cs_keep", "cs_loop", "Next")
        self.add_edge(view, "cs_skip", "cs_loop", "Next")
        self.add_edge(view, "cs_loop", "cs_join", "Done")
        self.add_edge(view, "cs_join", "cs_end", "")

    def build_s3_regex_view(self) -> None:
        """Build Level 3: S3 Regex Parsing."""
        view = "s3_regex"
        self.add_node(view, "sr_start", "Start Regex", "start", "Input: Filename")
        self.add_node(view, "sr_match", "Match Pattern", "process", "re.match(PATTERN)")
        self.add_node(view, "sr_check", "Match?", "decision", "Is not None?")
        self.add_node(view, "sr_group", "Extract Groups", "process", "Date, Time, Type")
        self.add_node(view, "sr_obj", "Create Spec", "process", "BackupSpec(...)")
        self.add_node(view, "sr_fail", "Ignore", "end", "Not a backup")
        self.add_node(view, "sr_end", "Return Spec", "end", "Valid BackupSpec")

        self.add_edge(view, "sr_start", "sr_match", "")
        self.add_edge(view, "sr_match", "sr_check", "")
        self.add_edge(view, "sr_check", "sr_group", "Yes")
        self.add_edge(view, "sr_check", "sr_fail", "No")
        self.add_edge(view, "sr_group", "sr_obj", "")
        self.add_edge(view, "sr_obj", "sr_end", "")

    def build_download_stream_view(self) -> None:
        """Build Level 3: Download Stream Loop."""
        view = "wd_stream"
        self.add_node(view, "ds_start", "Start Stream", "start", "Input: Body, File")
        self.add_node(view, "ds_read", "Read Chunk", "process", "body.read(8MB)")
        self.add_node(view, "ds_check", "Empty?", "decision", "chunk is None/Empty")
        self.add_node(view, "ds_write", "Write", "process", "f.write(chunk)")
        self.add_node(view, "ds_track", "Update Total", "process", "downloaded += len")
        self.add_node(view, "ds_prog", "Log?", "decision", ">= 64MB since last")
        self.add_node(view, "ds_log", "Log Info", "process", "logger.info(...)")
        self.add_node(view, "ds_end", "Finish", "end", "Close file")

        self.add_edge(view, "ds_start", "ds_read", "")
        self.add_edge(view, "ds_read", "ds_check", "")
        self.add_edge(view, "ds_check", "ds_write", "No")
        self.add_edge(view, "ds_check", "ds_end", "Yes")
        self.add_edge(view, "ds_write", "ds_track", "")
        self.add_edge(view, "ds_track", "ds_prog", "")
        self.add_edge(view, "ds_prog", "ds_log", "Yes")
        self.add_edge(view, "ds_prog", "ds_read", "No")
        self.add_edge(view, "ds_log", "ds_read", "")

    def build_restore_cmd_view(self) -> None:
        """Build Level 3: Restore Command Construction."""
        view = "wr_cmd"
        self.add_node(view, "rc_start", "Start Build", "start", "Input: Config")
        self.add_node(view, "rc_base", "Base Cmd", "process", "['myloader']")
        self.add_node(view, "rc_user", "Add User", "process", "--user={user}")
        self.add_node(view, "rc_host", "Add Host", "process", "--host={host}")
        self.add_node(view, "rc_dir", "Add Dir", "process", "--directory={dir}")
        self.add_node(view, "rc_over", "Add Overwrite", "process", "--overwrite-tables")
        self.add_node(view, "rc_verb", "Add Verbose", "process", "--verbose=3")
        self.add_node(view, "rc_end", "Return List", "end", "Command List")

        self.add_edge(view, "rc_start", "rc_base", "")
        self.add_edge(view, "rc_base", "rc_user", "")
        self.add_edge(view, "rc_user", "rc_host", "")
        self.add_edge(view, "rc_host", "rc_dir", "")
        self.add_edge(view, "rc_dir", "rc_over", "")
        self.add_edge(view, "rc_over", "rc_verb", "")
        self.add_edge(view, "rc_verb", "rc_end", "")

    def build_cli_tokens_view(self) -> None:
        """Build Level 3: CLI Tokenizer Loop."""
        view = "cp_tokens"
        self.add_node(view, "ct_start", "Start Loop", "start", "Input: Tokens[1:]")
        self.add_node(view, "ct_loop", "Next Token", "process", "For each token")
        self.add_node(
            view, "ct_check_cust", "Is customer=?", "decision", "StartsWith 'customer='"
        )
        self.add_node(
            view, "ct_check_host", "Is dbhost=?", "decision", "StartsWith 'dbhost='"
        )
        self.add_node(
            view, "ct_check_over", "Is overwrite?", "decision", "== 'overwrite'"
        )
        self.add_node(
            view, "ct_check_qa", "Is qatemplate?", "decision", "== 'qatemplate'"
        )
        self.add_node(
            view, "ct_set_cust", "Set Customer", "process", "opts.customer = val"
        )
        self.add_node(view, "ct_set_host", "Set Host", "process", "opts.dbhost = val")
        self.add_node(
            view, "ct_set_over", "Set Overwrite", "process", "opts.overwrite = True"
        )
        self.add_node(view, "ct_set_qa", "Set QA", "process", "opts.qatemplate = True")
        self.add_node(view, "ct_error", "Unknown Arg", "end", "Raise ValueError")
        self.add_node(view, "ct_end", "Done", "end", "Return Options")

        self.add_edge(view, "ct_start", "ct_loop", "")
        self.add_edge(view, "ct_loop", "ct_check_cust", "")
        self.add_edge(view, "ct_check_cust", "ct_set_cust", "Yes")
        self.add_edge(view, "ct_check_cust", "ct_check_host", "No")
        self.add_edge(view, "ct_check_host", "ct_set_host", "Yes")
        self.add_edge(view, "ct_check_host", "ct_check_over", "No")
        self.add_edge(view, "ct_check_over", "ct_set_over", "Yes")
        self.add_edge(view, "ct_check_over", "ct_check_qa", "No")
        self.add_edge(view, "ct_check_qa", "ct_set_qa", "Yes")
        self.add_edge(view, "ct_check_qa", "ct_error", "No")

        self.add_edge(view, "ct_set_cust", "ct_loop", "Next")
        self.add_edge(view, "ct_set_host", "ct_loop", "Next")
        self.add_edge(view, "ct_set_over", "ct_loop", "Next")
        self.add_edge(view, "ct_set_qa", "ct_loop", "Next")
        self.add_edge(view, "ct_loop", "ct_end", "No More Tokens")

    def build_s3_schema_view(self) -> None:
        """Build Level 3: S3 Schema Check."""
        view = "s3_schema"
        self.add_node(view, "ss_start", "Start Check", "start", "Input: Backup Key")
        self.add_node(
            view,
            "ss_derive",
            "Derive Name",
            "process",
            "Replace .tar -> -schema-create.sql.zst",
        )
        self.add_node(
            view, "ss_check", "In List?", "decision", "Is schema_key in objects?"
        )
        self.add_node(view, "ss_true", "Valid", "end", "Return True")
        self.add_node(view, "ss_false", "Invalid", "end", "Return False")

        self.add_edge(view, "ss_start", "ss_derive", "")
        self.add_edge(view, "ss_derive", "ss_check", "")
        self.add_edge(view, "ss_check", "ss_true", "Yes")
        self.add_edge(view, "ss_check", "ss_false", "No")

    def build_disk_check_view(self) -> None:
        """Build Level 3: Disk Space Check."""
        view = "wd_check"
        self.add_node(view, "dc_start", "Start Check", "start", "Input: Required Bytes")
        self.add_node(view, "dc_path", "Get Path", "process", "os.path.dirname(dest)")
        self.add_node(
            view, "dc_usage", "Get Usage", "process", "shutil.disk_usage(path)"
        )
        self.add_node(view, "dc_calc", "Compare", "decision", "usage.free > required")
        self.add_node(view, "dc_pass", "Pass", "end", "Return True")
        self.add_node(view, "dc_fail", "Fail", "end", "Raise DiskSpaceError")

        self.add_edge(view, "dc_start", "dc_path", "")
        self.add_edge(view, "dc_path", "dc_usage", "")
        self.add_edge(view, "dc_usage", "dc_calc", "")
        self.add_edge(view, "dc_calc", "dc_pass", "Yes")
        self.add_edge(view, "dc_calc", "dc_fail", "No")

    def build_restore_mon_view(self) -> None:
        """Build Level 3: Restore Monitor Loop."""
        view = "wr_mon"
        self.add_node(view, "rm_start", "Start Monitor", "start", "Input: Popen Proc")
        self.add_node(view, "rm_sel", "Select", "process", "select([stdout, stderr])")
        self.add_node(view, "rm_read", "Read Line", "process", "pipe.readline()")
        self.add_node(view, "rm_empty", "EOF?", "decision", "Line is empty?")
        self.add_node(view, "rm_log", "Log", "process", "logger.info(line)")
        self.add_node(view, "rm_end", "Done", "end", "Return")

        self.add_edge(view, "rm_start", "rm_sel", "")
        self.add_edge(view, "rm_sel", "rm_read", "Ready")
        self.add_edge(view, "rm_read", "rm_empty", "")
        self.add_edge(view, "rm_empty", "rm_log", "No")
        self.add_edge(view, "rm_log", "rm_sel", "Next")
        self.add_edge(view, "rm_empty", "rm_end", "Yes")

    def build_creds_view(self) -> None:
        """Build Level 3: Credential Resolution."""
        view = "cli_creds"
        self.add_node(
            view, "cc_start", "Start Resolve", "start", "Input: Credential Ref"
        )
        self.add_node(view, "cc_parse", "Parse Ref", "process", "Split Service:ID")
        self.add_node(
            view, "cc_type", "Service Type", "decision", "SecretsManager or SSM?"
        )
        self.add_node(
            view, "cc_sm", "Get Secret", "process", "secretsmanager.get_secret_value"
        )
        self.add_node(view, "cc_ssm", "Get Param", "process", "ssm.get_parameter")
        self.add_node(view, "cc_json", "Parse JSON", "process", "json.loads(value)")
        self.add_node(view, "cc_ret", "Return", "end", "MySQLCredentials")

        self.add_edge(view, "cc_start", "cc_parse", "")
        self.add_edge(view, "cc_parse", "cc_type", "")
        self.add_edge(view, "cc_type", "cc_sm", "SecretsManager")
        self.add_edge(view, "cc_type", "cc_ssm", "SSM")
        self.add_edge(view, "cc_sm", "cc_json", "")
        self.add_edge(view, "cc_ssm", "cc_json", "")
        self.add_edge(view, "cc_json", "cc_ret", "")

    def build_worker_rename_view(self) -> None:
        """Build Level 2: Atomic Rename Logic."""
        view = "w_rename"
        self.add_node(view, "rn_start", "Start Rename", "start", "Input: Job ID")
        self.add_node(view, "rn_conn", "Get Conn", "process", "Get DB Connection")
        self.add_node(
            view, "rn_check", "Check Staging", "decision", "Staging DB Exists?"
        )
        self.add_node(
            view, "rn_call", "Call Proc", "process", "CALL atomic_rename(...)"
        )
        self.add_node(
            view, "rn_drop", "Drop Staging", "process", "DROP DATABASE staging"
        )
        self.add_node(view, "rn_end", "Complete", "end", "Return Success")

        self.add_edge(view, "rn_start", "rn_conn", "")
        self.add_edge(view, "rn_conn", "rn_check", "")
        self.add_edge(view, "rn_check", "rn_call", "Yes")
        self.add_edge(view, "rn_check", "rn_end", "No (Error)")
        self.add_edge(view, "rn_call", "rn_drop", "Success")
        self.add_edge(view, "rn_drop", "rn_end", "")

    def build_rename_call_view(self) -> None:
        """Build Level 3: Atomic Rename Procedure Call."""
        view = "rn_call"
        self.add_node(view, "rc_start", "Start Call", "start", "Input: Conn, Names")
        self.add_node(view, "rc_cursor", "Get Cursor", "process", "conn.cursor()")
        self.add_node(
            view, "rc_exec", "Execute", "process", "cursor.execute('CALL ...')"
        )
        self.add_node(view, "rc_commit", "Commit", "process", "conn.commit()")
        self.add_node(view, "rc_close", "Close", "process", "cursor.close()")
        self.add_node(view, "rc_end", "Return", "end", "Success")

        self.add_edge(view, "rc_start", "rc_cursor", "")
        self.add_edge(view, "rc_cursor", "rc_exec", "")
        self.add_edge(view, "rc_exec", "rc_commit", "")
        self.add_edge(view, "rc_commit", "rc_close", "")
        self.add_edge(view, "rc_close", "rc_end", "")

    def build_post_sql_run_view(self) -> None:
        """Build Level 3: Post-SQL Execution Details."""
        view = "wp_run"
        self.add_node(view, "pr_start", "Start Exec", "start", "Input: SQL")
        self.add_node(view, "pr_try", "Try Block", "process", "Begin Try")
        self.add_node(view, "pr_exec", "Execute", "process", "cursor.execute(sql)")
        self.add_node(view, "pr_commit", "Commit", "process", "conn.commit()")
        self.add_node(view, "pr_except", "Exception?", "decision", "Error Occurred?")
        self.add_node(view, "pr_roll", "Rollback", "process", "conn.rollback()")
        self.add_node(view, "pr_raise", "Raise", "end", "Re-raise Error")
        self.add_node(view, "pr_end", "Success", "end", "Return")

        self.add_edge(view, "pr_start", "pr_try", "")
        self.add_edge(view, "pr_try", "pr_exec", "")
        self.add_edge(view, "pr_exec", "pr_commit", "")
        self.add_edge(view, "pr_commit", "pr_except", "")
        self.add_edge(view, "pr_except", "pr_roll", "Yes")
        self.add_edge(view, "pr_roll", "pr_raise", "")
        self.add_edge(view, "pr_except", "pr_end", "No")

    def build_config_load_view(self) -> None:
        """Build Level 3: Configuration Loading."""
        view = "cli_config"
        self.add_node(view, "cl_start", "Start Load", "start", "Init Config")
        self.add_node(view, "cl_env", "Load Env", "process", "os.environ.get()")
        self.add_node(view, "cl_ssm", "Load SSM", "process", "Get Parameter Store")
        self.add_node(view, "cl_merge", "Merge", "process", "Overlay SSM on Env")
        self.add_node(view, "cl_valid", "Validate", "decision", "Required fields?")
        self.add_node(view, "cl_err", "Error", "end", "Raise ConfigError")
        self.add_node(view, "cl_end", "Return", "end", "Config Object")

        self.add_edge(view, "cl_start", "cl_env", "")
        self.add_edge(view, "cl_env", "cl_ssm", "")
        self.add_edge(view, "cl_ssm", "cl_merge", "")
        self.add_edge(view, "cl_merge", "cl_valid", "")
        self.add_edge(view, "cl_valid", "cl_err", "Missing")
        self.add_edge(view, "cl_valid", "cl_end", "OK")

    def build_s3_list_view(self) -> None:
        """Build Level 3: S3 Pagination."""
        view = "s3_list"
        self.add_node(view, "sl_start", "Start List", "start", "Input: Bucket, Prefix")
        self.add_node(view, "sl_page", "Get Paginator", "process", "s3.get_paginator")
        self.add_node(view, "sl_iter", "Iterate Pages", "process", "For page in pages")
        self.add_node(
            view, "sl_cont", "Get Contents", "process", "page.get('Contents')"
        )
        self.add_node(view, "sl_ext", "Extend List", "process", "all_objs.extend()")
        self.add_node(view, "sl_next", "Next Page?", "decision", "More pages?")
        self.add_node(view, "sl_end", "Return", "end", "Full Object List")

        self.add_edge(view, "sl_start", "sl_page", "")
        self.add_edge(view, "sl_page", "sl_iter", "")
        self.add_edge(view, "sl_iter", "sl_cont", "")
        self.add_edge(view, "sl_cont", "sl_ext", "")
        self.add_edge(view, "sl_ext", "sl_next", "")
        self.add_edge(view, "sl_next", "sl_iter", "Yes")
        self.add_edge(view, "sl_next", "sl_end", "No")

    def generate(self) -> None:
        """Generate the flow data and write to file."""
        self.build_main_view()
        self.build_cli_view()
        self.build_worker_view()
        self.build_infra_view()

        # Level 2
        self.build_cli_parse_view()
        self.build_worker_s3_view()
        self.build_worker_download_view()
        self.build_worker_restore_view()
        self.build_worker_post_sql_view()

        # Level 3
        self.build_cli_sanitize_view()
        self.build_s3_regex_view()
        self.build_download_stream_view()
        self.build_restore_cmd_view()

        # New Level 3
        self.build_cli_tokens_view()
        self.build_s3_schema_view()
        self.build_disk_check_view()
        self.build_restore_mon_view()
        self.build_creds_view()

        # New Level 2 (Missing)
        self.build_worker_rename_view()

        # New Level 3 (Expanded)
        self.build_rename_call_view()
        self.build_post_sql_run_view()
        self.build_config_load_view()
        self.build_s3_list_view()

        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(self.views, f, indent=2)

        print(f"Flow data written to {OUTPUT_FILE}")


if __name__ == "__main__":
    generator = FlowGenerator()
    generator.generate()
