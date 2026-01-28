# MyLoader 0.20.1-1 Command Line Options Reference

> **Source**: Output from `/opt/pulldb.service/bin/myloader-0.20.1-1 --help`
> **Captured**: 2026-01-28
> **Purpose**: Authoritative reference for myloader options used in pullDB

## Connection Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--host` | `-h` | The host to connect to | |
| `--user` | `-u` | Username with the necessary privileges | |
| `--password` | `-p` | User password | |
| `--default-connection-database` | | Set the database name to connect to | `INFORMATION_SCHEMA` |
| `--ask-password` | `-a` | Prompt for user password | `FALSE` |
| `--port` | `-P` | TCP/IP port to connect to | `0` |
| `--socket` | `-S` | UNIX domain socket file to use for connection | |
| `--protocol` | | The protocol to use for connection (tcp, socket) | |
| `--compress-protocol` | `-C` | Use compression on the MySQL connection | `FALSE` |
| `--ssl` | | Connect using SSL | `FALSE` |
| `--ssl-mode` | | Desired security state: DISABLED, PREFERRED, REQUIRED, VERIFY_CA, VERIFY_IDENTITY | |
| `--key` | | The path name to the key file | |
| `--cert` | | The path name to the certificate file | |
| `--ca` | | The path name to the certificate authority file | |
| `--capath` | | Directory with trusted SSL CA certificates in PEM format | |
| `--cipher` | | Permissible ciphers for SSL encryption | |
| `--tls-version` | | Protocols the server permits for encrypted connections | |
| `--enable-cleartext-plugin` | | Enable the clear text authentication plugin (disabled by default) | |

## Filter Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--regex` | `-x` | Regular expression for 'db.table' matching | `""` |
| `--source-db` | `-s` | Database to restore | |
| `--skip-triggers` | | Do not import triggers | `FALSE` |
| `--skip-post` | | Do not import events, stored procedures and functions | `FALSE` |
| `--skip-constraints` | | Do not import constraints | `FALSE` |
| `--skip-indexes` | | Do not import secondary indexes on InnoDB tables | `FALSE` |
| `--no-data` | | Do not dump or import table data | `FALSE` |
| `--omit-from-file` | `-O` | File containing database.table entries to skip, one per line | |
| `--tables-list` | `-T` | Comma delimited table list to dump (e.g., test.t1,test.t2) | |

## Execution Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--enable-binlog` | `-e` | **DEPRECATED** - Use [myloader_session_variables] in defaults file | |
| `--optimize-keys` | | When to create indexes: `AFTER_IMPORT_PER_TABLE`, `AFTER_IMPORT_ALL_TABLES`, `SKIP` | `AFTER_IMPORT_PER_TABLE` |
| `--no-schema` | | Do not import table schemas and triggers | `FALSE` |
| `--disable-redo-log` | | Disables the REDO_LOG and enables it after | |
| `--checksum` | | Treat checksums: `skip`, `fail`, `warn` | `fail` |
| `--drop-database` | | Executes DROP DATABASE if schema database file is found | |
| `--drop-table` | `-o` | Drop mode if table exists: `FAIL`, `NONE`, `DROP`, `TRUNCATE`, `DELETE` | `FAIL` (or `DROP` if used without param) |
| `--retry-count` | | Lock wait timeout exceeded retry count | `10` |
| `--serialized-table-creation` | | Table recreation one thread at a time (same as --max-threads-for-schema-creation=1) | `FALSE` |
| `--stream` | | Receive stream from STDIN: `NO_DELETE`, `NO_STREAM_AND_NO_DELETE`, `TRADITIONAL`, `NO_STREAM` | `FALSE` |
| `--metadata-refresh-interval` | | Tables between internal metadata refresh | `100` |
| `--skip-table-sorting` | | Skip sorting tables by size (may reduce performance with many tables) | |
| `--set-gtid-purged` | | Execute SET GLOBAL gtid_purged from metadata file | |

## Thread Options

| Option | Description | Default |
|--------|-------------|---------|
| `--threads` | `-t` | Number of threads to use (0 = CPU count) | `4` (min: 2) |
| `--max-threads-per-table` | Maximum threads per table | `4` (defaults to --threads) |
| `--max-threads-for-index-creation` | Maximum threads for index creation | `4` |
| `--max-threads-for-post-actions` | Max threads for constraints, procedures, views, triggers | `1` |
| `--max-threads-for-schema-creation` | Maximum threads for schema creation | `4` |
| `--exec-per-thread` | Command to receive input via STDIN | |
| `--exec-per-thread-extension` | Input file extension when --exec-per-thread is used | |

## Statement Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--rows` | `-r` | Split INSERT statement into this many rows | `0` |
| `--queries-per-transaction` | `-q` | Number of queries per transaction | `1000` |
| `--max-statement-size` | | Max statement size (not currently used) | |
| `--max-transaction-size` | | Max transaction size in megabytes | `1000` |
| `--append-if-not-exist` | | Appends IF NOT EXISTS to CREATE TABLE | |
| `--set-names` | | Sets the names (use at your own risk) | `binary` |
| `--skip-definer` | | Removes DEFINER from CREATE statements | `FALSE` |
| `--ignore-set` | | Variables to ignore from the header of SET | |

## Load from Metadata Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--quote-character` | `-Q` | Identifier quote char: `BACKTICK`/`bt`/`` ` `` or `DOUBLE_QUOTE`/`dt`/`"` | auto-detect or `BACKTICK` |
| `--local-infile` | | Enable 'LOAD DATA LOCAL INFILE' | auto-detect or disabled |

## Application Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--help` | `-?` | Show help options | |
| `--directory` | `-d` | Directory of the dump to import | |
| `--logfile` | `-L` | Log file name (default: stdout) | |
| `--fifodir` | | Directory for FIFO files | same as backup |
| `--database` | `-B` | Alternative database to restore into | |
| `--show-warnings` | | Print warnings during INSERT IGNORE | |
| `--resume` | | Process only files from resume file in backup dir | `FALSE` |
| `--kill-at-once` | `-k` | Immediately terminate on Ctrl+C | |
| `--mysqldump` | | Expect mysqldump format when stream is used | |
| `--source-data` | | Include options in metadata for replication setup | |
| `--version` | `-V` | Show program version and exit | |
| `--verbose` | `-v` | Verbosity: 0=silent, 1=errors, 2=warnings, 3=info | `2` |
| `--debug` | | Turn on debugging (sets verbosity to 3) | `FALSE` |
| `--ignore-errors` | | Don't increment error count for comma-separated error numbers | |
| `--defaults-file` | | Use a specific defaults file | `/etc/mydumper.cnf` |
| `--defaults-extra-file` | | Additional defaults file (loaded after --defaults-file) | |
| `--source-control-command` | | Replication config command: `TRADITIONAL`, `AWS` | |
| `--optimize-keys-engines` | | Engines for multi-stage table creation | `InnoDB,ROCKSDB` |
| `--server-version` | | Set server version (avoid auto-detection) | |
| `--throttle` | | Throttle based on status var (e.g., `Threads_running=10`) | |

## PMM Options

| Option | Description | Default |
|--------|-------------|---------|
| `--pmm-path` | Path for PMM textfile collector | `/usr/local/percona/pmm2/collectors/textfile-collector/high-resolution` |
| `--pmm-resolution` | PMM resolution | `high` |

---

## Options NOT Available in 0.20.x

These options do **NOT** exist in myloader 0.20.1-1:

| ❌ Option | Notes |
|-----------|-------|
| `--connection-timeout` | **Does not exist** - removed from pullDB config |
| `--rows-per-insert` | **Does not exist** - use `--rows` instead |
| `--wait-timeout` | Does not exist |
| `--net-read-timeout` | Does not exist |
| `--net-write-timeout` | Does not exist |

## Deprecated Options (Still Work But Avoid)

| ⚠️ Option | Replacement |
|-----------|-------------|
| `--overwrite-tables` | Use `--drop-table` or `-o` instead |
| `--overwrite-unsafe` | Use `--drop-table` (exists but discouraged) |
| `--innodb-optimize-keys` | Use `--optimize-keys` instead |
| `--purge-mode` | Use `-o/--drop-table` instead |
| `--enable-binlog` | Use `[myloader_session_variables]` in defaults file |

For timeout control, use MySQL session variables via `--defaults-file` or `--defaults-extra-file`.

---

## pullDB Mapping

| pullDB Setting | myloader Option | Default |
|----------------|-----------------|---------|
| `myloader_threads` | `--threads` | `8` |
| `myloader_max_threads_per_table` | `--max-threads-per-table` | `1` |
| `myloader_max_threads_index` | `--max-threads-for-index-creation` | `1` |
| `myloader_max_threads_post_actions` | `--max-threads-for-post-actions` | `1` |
| `myloader_max_threads_schema` | `--max-threads-for-schema-creation` | `4` |
| `myloader_rows` | `--rows` | `50000` |
| `myloader_queries_per_transaction` | `--queries-per-transaction` | `1000` |
| `myloader_retry_count` | `--retry-count` | `20` |
| `myloader_throttle_threshold` | `--throttle=Threads_running=N` | `6` |
| `myloader_optimize_keys` | `--optimize-keys` | `AFTER_IMPORT_PER_TABLE` |
| `myloader_checksum` | `--checksum` | `warn` |
| `myloader_drop_table_mode` | `--drop-table` | `DROP` |
| `myloader_verbose` | `--verbose` | `3` |
| `myloader_local_infile` | `--local-infile=TRUE` | `true` |
| `myloader_skip_triggers` | `--skip-triggers` | `false` |
| `myloader_skip_constraints` | `--skip-constraints` | `false` |
| `myloader_skip_indexes` | `--skip-indexes` | `false` |
| `myloader_skip_post` | `--skip-post` | `false` |
| `myloader_skip_definer` | `--skip-definer` | `false` |
| `myloader_ignore_errors` | `--ignore-errors` | `1146` |
