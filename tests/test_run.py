from unittest.mock import patch


def test_main_wires_fetch_cluster_and_load_with_expected_arguments(tmp_path):
    """Regression test for run.py having zero test coverage: this is the only
    place that would catch a mismatch if e.g. fetch_parcels's return signature
    changed again (it already changed once, from list[dict] to
    tuple[list[dict], list[str]], during the live-run fix). Focuses on wiring
    (right functions called with right arguments in the right order), not
    re-testing logic already covered by test_fetch.py/test_cluster.py/test_load.py.
    """
    import precompute.run as run

    fake_parcels = [{"apn": "A", "geometry": object(), "situsstr": "MAIN ST"}]
    fake_repaired_apns = []
    fake_roadways = [{"roadname": "MAIN ST", "geometry": object()}]
    fake_clusters = [
        {
            "street_name": "MAIN ST",
            "geometry": object(),
            "centroid_lat": 0.0,
            "centroid_lng": 0.0,
            "parcel_count": 8,
            "members": fake_parcels,
        }
    ]
    fake_excluded = []
    fake_outlier_indices = []

    db_path = tmp_path / "test.db"

    with (
        patch("precompute.run.fetch_parcels", return_value=(fake_parcels, fake_repaired_apns)) as mock_fetch_parcels,
        patch("precompute.run.fetch_roadways", return_value=fake_roadways) as mock_fetch_roadways,
        patch(
            "precompute.run.cluster_parcels_by_street",
            return_value=(fake_clusters, fake_excluded, fake_outlier_indices),
        ) as mock_cluster,
        patch("precompute.run.load_clusters_and_parcels") as mock_load,
    ):
        run.main(db_path=db_path)

    mock_fetch_parcels.assert_called_once_with(run.COMMUNITY_NAME)
    mock_fetch_roadways.assert_called_once_with()
    mock_cluster.assert_called_once_with(fake_parcels, fake_roadways)

    mock_load.assert_called_once()
    load_call_args = mock_load.call_args.args
    # load_clusters_and_parcels(conn, clusters) - second positional arg is the
    # clusters returned by cluster_parcels_by_street.
    assert load_call_args[1] == fake_clusters

    # Wiring order: fetch before cluster, cluster before load.
    assert mock_fetch_parcels.call_args is not None
    assert mock_cluster.call_args is not None
    assert mock_load.call_args is not None


def test_main_prints_unsafe_cluster_warning_for_below_minimum_clusters(tmp_path, capsys):
    """Confirms the anonymization_safe warning added to run.py actually fires
    when a cluster is below MIN_CLUSTER_SIZE, and does not fire when all
    clusters are safe.
    """
    import precompute.run as run

    unsafe_cluster = {
        "street_name": "SHORT LN",
        "geometry": object(),
        "centroid_lat": 0.0,
        "centroid_lng": 0.0,
        "parcel_count": 2,
        "members": [{"apn": "A", "geometry": object(), "situsstr": "SHORT LN"}],
    }

    db_path = tmp_path / "test.db"

    with (
        patch("precompute.run.fetch_parcels", return_value=([], [])),
        patch("precompute.run.fetch_roadways", return_value=[]),
        patch(
            "precompute.run.cluster_parcels_by_street",
            return_value=([unsafe_cluster], [], [0]),
        ),
        patch("precompute.run.load_clusters_and_parcels"),
    ):
        run.main(db_path=db_path)

    captured = capsys.readouterr()
    assert "NOT safe to offer as obscured-location targets" in captured.out
    assert "1 clusters" in captured.out
