"""Tests for worker log normalization utilities."""

from __future__ import annotations

"""HCA Layer: tests."""

from pulldb.worker.log_normalizer import NormalizedLogEvent, normalize_myloader_line


def test_thread_start_event_parses_minimal_fields() -> None:
    line = "** Message: 17:27:50.761: S-Thread 19: Starting import"

    event = normalize_myloader_line(line, version="0.19")

    assert event == NormalizedLogEvent(
        tool="myloader",
        version="0.19",
        severity="info",
        phase="thread-start",
        time="17:27:50.761",
        thread=19,
        schema=None,
        table=None,
        table_pct=None,
        tables_processed=None,
        message="S-Thread 19: Starting import",
        raw=line,
    )


def test_table_progress_event_extracts_schema_table_and_pct() -> None:
    line = (
        "** Message: 18:38:43.845: Thread 7: "
        "`actiontermiteaz_legacy`.`chemicalTickets` [ 21% ] | Tables: 93/497"
    )

    event = normalize_myloader_line(line, version="0.19")
    assert event is not None
    assert event.schema == "actiontermiteaz_legacy"
    assert event.table == "chemicalTickets"
    assert event.table_pct == 21
    assert event.tables_processed == (93, 497)
    assert event.thread == 7
    assert event.phase == "table-data"
    assert event.severity == "info"
    assert event.time == "18:38:43.845"


def test_legacy_thread_dump_line_maps_to_table_data_phase() -> None:
    line = (
        "** Message: 17:50:01.899: Thread 7 dumping data for "
        "`actiontermiteaz_local`.`BKP_266201_employeeLocator_240908`"
    )

    event = normalize_myloader_line(line, version="0.9")
    assert event is not None
    assert event.schema == "actiontermiteaz_local"
    assert event.table == "BKP_266201_employeeLocator_240908"
    assert event.phase == "table-data"
    assert event.thread == 7
    assert event.version == "0.9"


def test_warning_line_sets_warning_severity() -> None:
    line = (
        "** (myloader-0.19.3-3:1832388): WARNING **: 18:38:22.734: "
        "Not able to determine database version - ERROR 1049: Unknown database 'system'"
    )

    event = normalize_myloader_line(line, version="0.19")
    assert event is not None
    assert event.severity == "warning"
    assert event.phase == "warning"
    assert event.message.startswith("Not able to determine")


def test_non_log_line_returns_none() -> None:
    assert normalize_myloader_line("random output", version="0.19") is None
