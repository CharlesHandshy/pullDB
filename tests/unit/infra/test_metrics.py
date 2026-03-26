"""Unit tests for pulldb.infra.metrics.

Covers:
  MetricLabels.to_dict  — all set, some None, all None
  emit_counter          — log level INFO, metric_type, metric_name, metric_value, labels merged
  emit_gauge            — same contract for gauge type
  emit_timer            — same contract for timer type, duration formatted to 3dp
  emit_event            — log level WARNING, event_message field
  time_operation        — measures real elapsed time, emits on normal exit,
                          emits on exception (finally), yields None

HCA Layer: shared (tests)
"""

from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock, call, patch

import pytest

from pulldb.infra.metrics import (
    MetricLabels,
    emit_counter,
    emit_event,
    emit_gauge,
    emit_timer,
    time_operation,
)


# ---------------------------------------------------------------------------
# MetricLabels.to_dict
# ---------------------------------------------------------------------------


class TestMetricLabelsToDict:
    def test_all_fields_set(self) -> None:
        labels = MetricLabels(
            job_id="job-1",
            target="acme",
            phase="download",
            status="success",
        )
        d = labels.to_dict()
        assert d == {
            "job_id": "job-1",
            "target": "acme",
            "phase": "download",
            "status": "success",
        }

    def test_none_fields_excluded(self) -> None:
        labels = MetricLabels(job_id="job-2", target=None, phase="restore", status=None)
        d = labels.to_dict()
        assert "target" not in d
        assert "status" not in d
        assert d["job_id"] == "job-2"
        assert d["phase"] == "restore"

    def test_all_none_returns_empty_dict(self) -> None:
        labels = MetricLabels()
        assert labels.to_dict() == {}

    def test_returns_new_dict_each_call(self) -> None:
        labels = MetricLabels(job_id="j1")
        d1 = labels.to_dict()
        d2 = labels.to_dict()
        assert d1 == d2
        assert d1 is not d2  # independent copies


# ---------------------------------------------------------------------------
# emit_counter
# ---------------------------------------------------------------------------


class TestEmitCounter:
    def test_logs_at_info_level(self) -> None:
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_counter("jobs_enqueued_total")
            mock_log.info.assert_called_once()
            mock_log.warning.assert_not_called()

    def test_extra_contains_metric_type_counter(self) -> None:
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_counter("jobs_enqueued_total")
            _, kwargs = mock_log.info.call_args
            assert kwargs["extra"]["metric_type"] == "counter"

    def test_extra_contains_metric_name(self) -> None:
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_counter("my_counter")
            _, kwargs = mock_log.info.call_args
            assert kwargs["extra"]["metric_name"] == "my_counter"

    def test_default_value_is_1(self) -> None:
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_counter("c")
            _, kwargs = mock_log.info.call_args
            assert kwargs["extra"]["metric_value"] == 1

    def test_custom_value_propagated(self) -> None:
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_counter("c", value=5)
            _, kwargs = mock_log.info.call_args
            assert kwargs["extra"]["metric_value"] == 5

    def test_labels_merged_into_extra(self) -> None:
        labels = MetricLabels(job_id="j1", phase="download")
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_counter("c", labels=labels)
            _, kwargs = mock_log.info.call_args
            assert kwargs["extra"]["job_id"] == "j1"
            assert kwargs["extra"]["phase"] == "download"

    def test_no_labels_does_not_add_label_keys(self) -> None:
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_counter("c")
            _, kwargs = mock_log.info.call_args
            assert "job_id" not in kwargs["extra"]
            assert "target" not in kwargs["extra"]


# ---------------------------------------------------------------------------
# emit_gauge
# ---------------------------------------------------------------------------


class TestEmitGauge:
    def test_metric_type_is_gauge(self) -> None:
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_gauge("queue_depth", 42.0)
            _, kwargs = mock_log.info.call_args
            assert kwargs["extra"]["metric_type"] == "gauge"

    def test_value_propagated(self) -> None:
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_gauge("disk_free_gb", 3.14)
            _, kwargs = mock_log.info.call_args
            assert kwargs["extra"]["metric_value"] == 3.14

    def test_zero_value_logged(self) -> None:
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_gauge("active_restores", 0)
            _, kwargs = mock_log.info.call_args
            assert kwargs["extra"]["metric_value"] == 0

    def test_logs_at_info(self) -> None:
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_gauge("g", 1.0)
            mock_log.info.assert_called_once()


# ---------------------------------------------------------------------------
# emit_timer
# ---------------------------------------------------------------------------


class TestEmitTimer:
    def test_metric_type_is_timer(self) -> None:
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_timer("restore_duration_seconds", 1.234)
            _, kwargs = mock_log.info.call_args
            assert kwargs["extra"]["metric_type"] == "timer"

    def test_duration_stored_as_float(self) -> None:
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_timer("t", 2.5)
            _, kwargs = mock_log.info.call_args
            assert kwargs["extra"]["metric_value"] == 2.5

    def test_log_message_formatted_to_3dp(self) -> None:
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_timer("t", 1.23456)
            args, _ = mock_log.info.call_args
            assert "1.235" in args[0]  # rounded to 3 decimal places

    def test_labels_included(self) -> None:
        labels = MetricLabels(status="success")
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_timer("t", 1.0, labels=labels)
            _, kwargs = mock_log.info.call_args
            assert kwargs["extra"]["status"] == "success"


# ---------------------------------------------------------------------------
# emit_event
# ---------------------------------------------------------------------------


class TestEmitEvent:
    def test_logs_at_warning_level(self) -> None:
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_event("disk_capacity_insufficient", "Only 2GB free")
            mock_log.warning.assert_called_once()
            mock_log.info.assert_not_called()

    def test_metric_type_is_event(self) -> None:
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_event("e", "msg")
            _, kwargs = mock_log.warning.call_args
            assert kwargs["extra"]["metric_type"] == "event"

    def test_metric_name_stored(self) -> None:
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_event("myloader_nonzero_exit", "exit code 1")
            _, kwargs = mock_log.warning.call_args
            assert kwargs["extra"]["metric_name"] == "myloader_nonzero_exit"

    def test_event_message_stored(self) -> None:
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_event("e", "some detail")
            _, kwargs = mock_log.warning.call_args
            assert kwargs["extra"]["event_message"] == "some detail"

    def test_labels_merged(self) -> None:
        labels = MetricLabels(job_id="j42", target="acme")
        with patch("pulldb.infra.metrics.logger") as mock_log:
            emit_event("e", "msg", labels=labels)
            _, kwargs = mock_log.warning.call_args
            assert kwargs["extra"]["job_id"] == "j42"
            assert kwargs["extra"]["target"] == "acme"


# ---------------------------------------------------------------------------
# time_operation
# ---------------------------------------------------------------------------


class TestTimeOperation:
    def test_emits_timer_on_normal_exit(self) -> None:
        with patch("pulldb.infra.metrics.logger") as mock_log:
            with time_operation("restore_duration_seconds"):
                pass
            mock_log.info.assert_called_once()
            _, kwargs = mock_log.info.call_args
            assert kwargs["extra"]["metric_type"] == "timer"
            assert kwargs["extra"]["metric_name"] == "restore_duration_seconds"

    def test_emits_timer_on_exception(self) -> None:
        """Timer must fire even if the wrapped block raises."""
        with patch("pulldb.infra.metrics.logger") as mock_log:
            with pytest.raises(ValueError):
                with time_operation("op_duration"):
                    raise ValueError("boom")
            mock_log.info.assert_called_once()
            _, kwargs = mock_log.info.call_args
            assert kwargs["extra"]["metric_type"] == "timer"

    def test_measures_real_elapsed_time(self) -> None:
        """Duration must be >= the sleep time."""
        with patch("pulldb.infra.metrics.logger") as mock_log:
            with time_operation("sleep_op"):
                time.sleep(0.05)
            _, kwargs = mock_log.info.call_args
            duration = kwargs["extra"]["metric_value"]
            assert duration >= 0.04  # at least 40ms

    def test_yields_none(self) -> None:
        with patch("pulldb.infra.metrics.logger"):
            with time_operation("op") as val:
                assert val is None

    def test_labels_passed_through(self) -> None:
        labels = MetricLabels(phase="post_sql", status="success")
        with patch("pulldb.infra.metrics.logger") as mock_log:
            with time_operation("t", labels=labels):
                pass
            _, kwargs = mock_log.info.call_args
            assert kwargs["extra"]["phase"] == "post_sql"
            assert kwargs["extra"]["status"] == "success"
