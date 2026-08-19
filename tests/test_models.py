import pytest
from pydantic import ValidationError

from models import ReportCreate


def test_valid_non_obscured_event_report():
    report = ReportCreate(
        report_type="event",
        obscured=False,
        parcel_id=1,
        event_subtype="main_break",
    )
    assert report.parcel_id == 1
    assert report.cluster_id is None


def test_valid_obscured_quality_report():
    report = ReportCreate(
        report_type="quality",
        obscured=True,
        cluster_id=5,
        taste="bad",
    )
    assert report.cluster_id == 5
    assert report.parcel_id is None


def test_rejects_invalid_report_type():
    with pytest.raises(ValidationError):
        ReportCreate(report_type="bogus", obscured=False, parcel_id=1, event_subtype="outage")


def test_rejects_non_obscured_report_without_parcel_id():
    with pytest.raises(ValidationError):
        ReportCreate(report_type="event", obscured=False, event_subtype="outage")


def test_rejects_obscured_report_with_parcel_id_set():
    with pytest.raises(ValidationError):
        ReportCreate(
            report_type="event",
            obscured=True,
            cluster_id=5,
            parcel_id=1,
            event_subtype="outage",
        )


def test_rejects_non_obscured_report_with_cluster_id_set():
    with pytest.raises(ValidationError):
        ReportCreate(
            report_type="event",
            obscured=False,
            parcel_id=1,
            cluster_id=5,
            event_subtype="outage",
        )


def test_rejects_free_text_over_500_chars():
    with pytest.raises(ValidationError):
        ReportCreate(
            report_type="event",
            obscured=False,
            parcel_id=1,
            event_subtype="outage",
            free_text="x" * 501,
        )


def test_rejects_invalid_quality_rating_value():
    with pytest.raises(ValidationError):
        ReportCreate(report_type="quality", obscured=True, cluster_id=5, taste="terrible")


def test_rejects_event_report_missing_event_subtype():
    with pytest.raises(ValidationError):
        ReportCreate(report_type="event", obscured=False, parcel_id=1)


def test_rejects_event_report_with_quality_field_set():
    with pytest.raises(ValidationError):
        ReportCreate(
            report_type="event",
            obscured=False,
            parcel_id=1,
            event_subtype="outage",
            taste="bad",
        )


def test_rejects_quality_report_with_event_field_set():
    with pytest.raises(ValidationError):
        ReportCreate(
            report_type="quality",
            obscured=True,
            cluster_id=5,
            taste="bad",
            event_subtype="outage",
        )


def test_rejects_quality_report_with_no_rating_and_no_text():
    with pytest.raises(ValidationError):
        ReportCreate(report_type="quality", obscured=True, cluster_id=5)


def test_accepts_quality_report_with_only_free_text():
    report = ReportCreate(
        report_type="quality", obscured=True, cluster_id=5, free_text="tastes off today"
    )
    assert report.free_text == "tastes off today"
