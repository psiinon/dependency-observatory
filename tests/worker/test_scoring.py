# -*- coding: utf-8 -*-

from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest

import depobs.worker.scoring as m


# NB: later values override:
# >>> {**{'x': 2}, 'x': 1}
# {'x': 1}
#
_default_report_json = {
    "directVulnsCritical_score": 0,
    "directVulnsHigh_score": 0,
    "directVulnsLow_score": 0,
    "directVulnsMedium_score": 0,
    "indirectVulnsCritical_score": 0,
    "indirectVulnsHigh_score": 0,
    "indirectVulnsLow_score": 0,
    "indirectVulnsMedium_score": 0,
    "id": None,
    "task_id": None,
    "task_status": None,
    "authors": None,
    "contributors": None,
    "all_deps": 0,
    "dependencies": [],
    "immediate_deps": 0,
    "npmsio_score": 0,
    "release_date": None,
    "status": "scanned",
    "top_score": None,
}


score_package_testcases = {
    "zero_npmsio_score": (
        [],
        [],
        0,
        [],
        {**_default_report_json, "package": "foo", "version": "0.0.0",},
    ),
    "nonzero_npmsio_score": (
        [],
        [],
        0.53,
        [],
        {
            **_default_report_json,
            "npmsio_score": 0.53,
            "package": "foo",
            "version": "0.0.0",
        },
    ),
    "nonzero_npmsio_score_direct_vulns": (
        [
            # TODO: confirm get_vulnerability_counts doesn't return "medium" and "moderate" severities
            (None, None, "critical", 1),
            (None, None, "high", 1),
            (None, None, "medium", 1),
            (None, None, "moderate", 1),
            (None, None, "low", 1),
            (None, None, "unexpected", 1),
        ],
        [],
        0.53,
        [],
        {
            **_default_report_json,
            "directVulnsCritical_score": 1,
            "directVulnsHigh_score": 1,
            "directVulnsLow_score": 1,
            "directVulnsMedium_score": 1,
            "npmsio_score": 0.53,
            "package": "foo",
            "version": "0.0.0",
        },
    ),
    "nonzero_npmsio_score_null_npm_reg_data": (
        [],
        [(None, None, None)],
        0.53,
        [],
        {
            **_default_report_json,
            "authors": 0,
            "contributors": 0,
            "npmsio_score": 0.53,
            "package": "foo",
            "version": "0.0.0",
        },
    ),
    "nonzero_npmsio_score_npm_reg_data": (
        [],
        [
            (
                "release day!",
                ["author1@example.com"],
                ["contributor1@example.com", "contributor2@example.com"],
            )
        ],
        0.53,
        [],
        {
            **_default_report_json,
            "authors": 1,
            "contributors": 2,
            "npmsio_score": 0.53,
            "release_date": "release day!",
            "package": "foo",
            "version": "0.0.0",
        },
    ),
    "nonzero_npmsio_score_direct_dep_reports": (
        [],
        [
            (
                "release day!",
                ["author1@example.com"],
                ["contributor1@example.com", "contributor2@example.com"],
            )
        ],
        0.53,
        [
            m.PackageReport(
                directVulnsCritical_score=None,
                directVulnsHigh_score=None,
                directVulnsMedium_score=None,
                directVulnsLow_score=None,
                indirectVulnsCritical_score=None,
                indirectVulnsHigh_score=None,
                indirectVulnsMedium_score=None,
                indirectVulnsLow_score=None,
            ),
            m.PackageReport(
                directVulnsCritical_score=2,
                directVulnsHigh_score=None,
                directVulnsMedium_score=None,
                directVulnsLow_score=None,
                indirectVulnsCritical_score=None,
                indirectVulnsHigh_score=1,
                indirectVulnsMedium_score=None,
                indirectVulnsLow_score=None,
            ),
            m.PackageReport(
                directVulnsCritical_score=1,
                directVulnsHigh_score=None,
                directVulnsMedium_score=None,
                directVulnsLow_score=None,
                indirectVulnsCritical_score=None,
                indirectVulnsHigh_score=1,
                indirectVulnsMedium_score=1,
                indirectVulnsLow_score=1,
            ),
        ],
        {
            **_default_report_json,
            "authors": 1,
            "contributors": 2,
            "dependencies": [
                m.PackageReport(
                    directVulnsCritical_score=None,
                    directVulnsHigh_score=None,
                    directVulnsMedium_score=None,
                    directVulnsLow_score=None,
                    indirectVulnsCritical_score=None,
                    indirectVulnsHigh_score=None,
                    indirectVulnsMedium_score=None,
                    indirectVulnsLow_score=None,
                ).json_with_dependencies(depth=0),
                m.PackageReport(
                    directVulnsCritical_score=2,
                    directVulnsHigh_score=None,
                    directVulnsMedium_score=None,
                    directVulnsLow_score=None,
                    indirectVulnsCritical_score=None,
                    indirectVulnsHigh_score=1,
                    indirectVulnsMedium_score=None,
                    indirectVulnsLow_score=None,
                ).json_with_dependencies(depth=0),
                m.PackageReport(
                    directVulnsCritical_score=1,
                    directVulnsHigh_score=None,
                    directVulnsMedium_score=None,
                    directVulnsLow_score=None,
                    indirectVulnsCritical_score=None,
                    indirectVulnsHigh_score=1,
                    indirectVulnsMedium_score=1,
                    indirectVulnsLow_score=1,
                ).json_with_dependencies(depth=0),
            ],
            "immediate_deps": 3,
            "indirectVulnsCritical_score": 3,
            "indirectVulnsHigh_score": 2,
            "indirectVulnsLow_score": 1,
            "indirectVulnsMedium_score": 1,
            "npmsio_score": 0.53,
            "release_date": "release day!",
            "package": "foo",
            "version": "0.0.0",
        },
    ),
}


@pytest.mark.parametrize(
    "vulns, npm_registry_data, npmsio_score, direct_dep_reports, expected_package_report_with_deps_json",
    score_package_testcases.values(),
    ids=score_package_testcases.keys(),
)
def test_score_package(
    mocker,
    vulns: Iterator[
        Tuple[str, str, str, int]
    ],  # generates: package (name), version, severity, count
    npm_registry_data: Iterator[
        Tuple[Any, List[str], List[str]]
    ],  # generates: published_at, maintainers, contributors
    npmsio_score: Optional[int],
    direct_dep_reports: List[m.PackageReport],
    expected_package_report_with_deps_json: Dict[str, Any],
):
    # https://docs.python.org/3/library/unittest.mock.html#where-to-patch
    dt_mock = mocker.patch("depobs.worker.scoring.datetime")
    expected_package_report_with_deps_json["scoring_date"] = dt_mock.now()

    npmsio_score_mock = mocker.patch(
        "depobs.worker.scoring.get_npms_io_score",
        **{"return_value.first.return_value": npmsio_score},
    )
    mocker.patch(
        "depobs.worker.scoring.get_npm_registry_data", return_value=npm_registry_data
    )
    mocker.patch("depobs.worker.scoring.get_vulnerability_counts", return_value=vulns)

    scored: m.PackageReport = m.score_package(
        package_name="foo",
        package_version="0.0.0",
        direct_dep_reports=direct_dep_reports,
        all_deps_count=0,
    )
    assert scored
    assert len(scored.dependencies) == len(
        expected_package_report_with_deps_json["dependencies"]
    )
    assert scored.json_with_dependencies() == expected_package_report_with_deps_json


outer_in_iter_testcases = {
    # NB: digraph node IDs need to match PackageVersion ids
    "one_node_no_edges": (
        [[]],
        [[]],
        [0.0],
        m.nx.trivial_graph(create_using=m.nx.DiGraph),
        [m.PackageVersion(id=0, name="test-solo-pkg", version="0.1.0")],
        [
            m.PackageReport(
                package="test-solo-pkg",
                version="0.1.0",
                status="scanned",
                all_deps=0,
                directVulnsCritical_score=0,
                directVulnsHigh_score=0,
                directVulnsLow_score=0,
                directVulnsMedium_score=0,
                immediate_deps=0,
                indirectVulnsCritical_score=0,
                indirectVulnsHigh_score=0,
                indirectVulnsLow_score=0,
                indirectVulnsMedium_score=0,
                npmsio_score=0.0,
            ).json_with_dependencies(depth=0)
        ],
    ),
    "three_node_path_graph": (
        [[], [], []],
        [[], [], []],
        [0.25, 0.9, 0.34],
        m.nx.path_graph(3, create_using=m.nx.DiGraph),
        [
            m.PackageVersion(id=0, name="test-root-pkg", version="0.1.0"),
            m.PackageVersion(id=1, name="test-child-pkg", version="0.0.3"),
            m.PackageVersion(id=2, name="test-grandchild-pkg", version="2.1.0"),
        ],
        [
            {
                **_default_report_json,
                "npmsio_score": 0.25,
                "package": "test-grandchild-pkg",
                "version": "2.1.0",
            },
            {
                **_default_report_json,
                "all_deps": 1,
                "dependencies": [
                    {
                        **_default_report_json,
                        "npmsio_score": 0.25,
                        "package": "test-grandchild-pkg",
                        "version": "2.1.0",
                    },
                ],
                "immediate_deps": 1,
                "npmsio_score": 0.9,
                "package": "test-child-pkg",
                "version": "0.0.3",
            },
            {
                **_default_report_json,
                "all_deps": 2,
                "authors": None,
                "dependencies": [
                    {
                        **_default_report_json,
                        "all_deps": 1,
                        "immediate_deps": 1,
                        "npmsio_score": 0.9,
                        "package": "test-child-pkg",
                        "version": "0.0.3",
                    },
                ],
                "immediate_deps": 1,
                "npmsio_score": 0.34,
                "package": "test-root-pkg",
                "version": "0.1.0",
            },
        ],
    ),
}


@pytest.mark.parametrize(
    "vulns, npm_registry_data, npmsio_scores, graph, package_versions, expected_package_reports_with_deps_json",
    outer_in_iter_testcases.values(),
    ids=outer_in_iter_testcases.keys(),
)
def test_score_package_and_children(
    mocker,
    # mocked calls
    vulns: List[
        Iterator[Tuple[str, str, str, int]]
    ],  # generates: package (name), version, severity, count
    npm_registry_data: List[
        Iterator[Tuple[Any, List[str], List[str]]]
    ],  # generates: published_at, maintainers, contributors
    npmsio_scores: List[Optional[int]],
    # args
    graph: m.nx.DiGraph,
    package_versions: List[m.PackageVersion],
    expected_package_reports_with_deps_json: List[Dict[str, Any]],
):
    dt_mock = mocker.patch("depobs.worker.scoring.datetime")

    for r in expected_package_reports_with_deps_json:
        r["scoring_date"] = dt_mock.now()
        for r_dep in r["dependencies"]:
            r_dep["scoring_date"] = dt_mock.now()

    npmsio_score_mock = mocker.patch(
        "depobs.worker.scoring.get_npms_io_score",
        **{"return_value.first.side_effect": npmsio_scores},
    )
    mocker.patch(
        "depobs.worker.scoring.get_npm_registry_data", side_effect=npm_registry_data
    )
    mocker.patch("depobs.worker.scoring.get_vulnerability_counts", side_effect=vulns)

    reports = m.score_package_and_children(graph, package_versions)

    # one report per node
    assert (
        len(graph.nodes)
        == len(package_versions)
        == len(reports)
        == len(expected_package_reports_with_deps_json)
    )

    # should have correct direct and indirect dep counts
    for report, expected_report_json in zip(
        reports, expected_package_reports_with_deps_json
    ):
        assert report.json_with_dependencies() == expected_report_json