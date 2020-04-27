import argparse
import asyncio
from collections import ChainMap
from datetime import datetime
import logging
import pathlib
from random import randrange
import sys
import time
from typing import (
    AbstractSet,
    Any,
    AnyStr,
    AsyncGenerator,
    Dict,
    Generator,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)
import typing

import sqlalchemy
from sqlalchemy import tuple_
from sqlalchemy.orm import Load, load_only

from depobs.database.models import (
    db,
    Advisory,
    PackageVersion,
    PackageLink,
    PackageGraph,
    NPMSIOScore,
    NPMRegistryEntry,
)
from depobs.scanner.db.connect import create_engine, create_session
from depobs.scanner.models.pipeline import add_db_arg
from depobs.scanner.pipelines.postprocess import (
    parse_stdout_as_json,
    parse_stdout_as_jsonlines,
)
from depobs.util.serialize_util import (
    extract_fields,
    extract_nested_fields,
    get_in,
)
from sqlalchemy.dialects.postgresql import array

log = logging.getLogger(__name__)


__doc__ = """Saves JSON lines to a postgres DB"""


Base = db.Model


def parse_args(pipeline_parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser = add_db_arg(parser)
    parser.add_argument(
        "--create-tables",
        action="store_true",
        required=False,
        default=False,
        help="Creates tables in the DB.",
    )
    parser.add_argument(
        "--create-views",
        action="store_true",
        required=False,
        default=False,
        help="Creates materialized views in the DB.",
    )
    parser.add_argument(
        "--input-type", type=str, required=True, help="Input type to save."
    )
    return parser


# TODO: move to db/schema.py
VIEWS: List[str] = [
    # CREATE MATERIALIZED VIEW IF NOT EXISTS <table_name> AS <query>
    # CREATE MATERIALIZED VIEW IF NOT EXISTS refs_with_repo AS (
    # SELECT
    #   refs.id AS id,
    #   refs.commit AS commit,
    #   refs.tag AS tag,
    #   refs.commit_ts AS commit_ts,
    #   repos.url AS url
    # FROM repos
    # INNER JOIN refs ON repos.id = refs.repo_id
    # )
    # """,
]


def get_package_version_link_id_query(
    session: sqlalchemy.orm.Session, link: Tuple[int, int]
) -> sqlalchemy.orm.query.Query:
    parent_package_id, child_package_id = link
    return session.query(PackageLink.id).filter_by(
        parent_package_id=parent_package_id, child_package_id=child_package_id
    )


def get_package_version_id_query(
    session: sqlalchemy.orm.Session, pkg: Dict
) -> sqlalchemy.orm.query.Query:
    return session.query(PackageVersion.id).filter_by(
        name=pkg["name"], version=pkg["version"], language="node"
    )


def get_node_advisory_id_query(
    session: sqlalchemy.orm.Session, advisory: Dict
) -> sqlalchemy.orm.query.Query:
    return session.query(Advisory.id).filter_by(language="node", url=advisory["url"])


def add_new_package_version(session: sqlalchemy.orm.Session, pkg: Dict) -> None:
    get_package_version_id_query(session, pkg).one_or_none() or session.add(
        PackageVersion(
            name=pkg.get("name", None),
            version=pkg.get("version", None),
            language="node",
            url=pkg.get(
                "resolved", None
            ),  # is null for the root for npm list and yarn list output
        )
    )


def insert_package_graph(session: sqlalchemy.orm.Session, task_data: Dict) -> None:
    link_ids = []
    for task_dep in task_data.get("dependencies", []):
        add_new_package_version(session, task_dep)
        session.commit()
        parent_package_id = get_package_version_id_query(session, task_dep).first()

        for dep in task_dep.get("dependencies", []):
            # is fully qualified semver for npm (or file: or github: url), semver for yarn
            name, version = dep.rsplit("@", 1)
            child_package_id = get_package_version_id_query(
                session, dict(name=name, version=version)
            ).first()

            link_id = get_package_version_link_id_query(
                session, (parent_package_id, child_package_id)
            ).one_or_none()
            if not link_id:
                session.add(
                    PackageLink(
                        child_package_id=child_package_id,
                        parent_package_id=parent_package_id,
                    )
                )
                session.commit()
                link_id = get_package_version_link_id_query(
                    session, (parent_package_id, child_package_id)
                ).first()
            link_ids.append(link_id)

    session.add(
        PackageGraph(
            root_package_version_id=get_package_version_id_query(
                session, task_data["root"]
            ).first()
            if task_data["root"]
            else None,
            link_ids=link_ids,
            package_manager="yarn" if "yarn" in task_data["command"] else "npm",
            package_manager_version=None,
        )
    )
    session.commit()


def insert_package_audit(session: sqlalchemy.orm.Session, task_data: Dict) -> None:
    is_yarn_cmd = bool("yarn" in task_data["command"])
    # NB: yarn has .advisory and .resolution

    # the same advisory JSON (from the npm DB) is
    # at .advisories{k, v} for npm and .advisories[].advisory for yarn
    advisories = (
        (item.get("advisory", None) for item in task_data.get("advisories", []))
        if is_yarn_cmd
        else task_data.get("advisories", dict()).values()
    )
    non_null_advisories = (adv for adv in advisories if adv)

    for advisory in non_null_advisories:
        advisory_fields = extract_nested_fields(
            advisory,
            {
                "package_name": ["module_name"],
                "npm_advisory_id": ["id"],
                "vulnerable_versions": ["vulnerable_versions"],
                "patched_versions": ["patched_versions"],
                "created": ["created"],
                "updated": ["updated"],
                "url": ["url"],
                "severity": ["severity"],
                "cves": ["cves"],
                "cwe": ["cwe"],
                "exploitability": ["metadata", "exploitability"],
                "title": ["title"],
            },
        )
        advisory_fields["cwe"] = int(advisory_fields["cwe"].lower().replace("cwe-", ""))
        advisory_fields["language"] = "node"
        advisory_fields["vulnerable_package_version_ids"] = []

        get_node_advisory_id_query(
            session, advisory_fields
        ).one_or_none() or session.add(Advisory(**advisory_fields))
        session.commit()

        # TODO: update other advisory fields too
        impacted_versions = set(
            finding.get("version", None)
            for finding in advisory.get("findings", [])
            if finding.get("version", None)
        )
        db_advisory = (
            session.query(Advisory.id, Advisory.vulnerable_package_version_ids)
            .filter_by(language="node", url=advisory["url"])
            .first()
        )
        impacted_version_package_ids = list(
            vid
            for result in session.query(PackageVersion.id)
            .filter(
                PackageVersion.name == advisory_fields["package_name"],
                PackageVersion.version.in_(impacted_versions),
            )
            .all()
            for vid in result
        )
        if len(impacted_versions) != len(impacted_version_package_ids):
            log.warning(
                f"missing package versions for {advisory_fields['package_name']!r}"
                f" in the db or misparsed audit output version:"
                f" {impacted_versions} {impacted_version_package_ids}"
            )

        if db_advisory.vulnerable_package_version_ids is None:
            session.query(Advisory.id).filter_by(id=db_advisory.id).update(
                dict(vulnerable_package_version_ids=list())
            )

        # TODO: lock the row?
        vpvids = set(
            list(
                session.query(Advisory)
                .filter_by(id=db_advisory.id)
                .first()
                .vulnerable_package_version_ids
            )
        )
        vpvids.update(set(impacted_version_package_ids))

        session.query(Advisory.id).filter_by(id=db_advisory.id).update(
            dict(vulnerable_package_version_ids=sorted(vpvids))
        )
        session.commit()


async def run_pipeline(
    source: Generator[Dict[str, Any], None, None], args: argparse.Namespace
) -> AsyncGenerator[None, None]:
    log.info(f"{__name__} pipeline started")
    engine = create_engine(args.db_url)
    if args.create_tables:
        Base.metadata.create_all(engine)

    if args.create_views:
        # TODO: with contextlib.closing
        connection = engine.connect()
        for command in VIEWS:
            _ = connection.execute(command)
            log.info(f"ran: {command}")
        connection.close()

    # use input type since it could write to multiple tables
    with create_session(engine) as session:
        if args.input_type == "postprocessed_repo_task":
            for line in source:
                for task_data in line["tasks"]:
                    if task_data["name"] == "list_metadata":
                        insert_package_graph(session, task_data)
                    elif task_data["name"] == "audit":
                        insert_package_audit(session, task_data)
                    else:
                        log.warning(f"skipping unrecognized task {task_data['name']}")
        elif args.input_type == "dep_meta_npm_reg":
            insert_npm_registry_data(session, source)
        elif args.input_type == "dep_meta_npmsio":
            insert_npmsio_data(session, source)
        else:
            raise NotImplementedError()
    # be the right type for the pipeline runner
    await asyncio.sleep(0)
    yield
