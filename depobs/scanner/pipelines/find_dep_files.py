import argparse
import asyncio
from dataclasses import asdict, dataclass
import functools
import logging
import pathlib
from random import randrange
from typing import Any, AsyncGenerator, Dict, Generator, Iterable, Tuple, Union

from depobs.util.serialize_util import get_in, extract_fields
import depobs.scanner.docker.containers as containers
from depobs.scanner.docker.images import build_images
from depobs.scanner.models.org_repo import OrgRepo
from depobs.scanner.models.git_ref import GitRef
from depobs.scanner.models.pipeline import add_docker_args
from depobs.scanner.models.language import (
    dependency_file_patterns,
    DependencyFile,
    DockerImage,
    docker_images,
)
from depobs.scanner.pipelines.util import exc_to_str

log = logging.getLogger(__name__)

__doc__ = """
Given a repo_url, clones the repo, lists git refs for each tag
"""


def parse_args(pipeline_parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser = add_docker_args(parser)
    parser.add_argument(
        "--glob",
        type=str,
        action="append",
        required=False,
        default=list(dependency_file_patterns.keys()),
        help=f"manifest globs to search for dep files in the repo. "
        f"Defaults to: {list(dependency_file_patterns.keys())}",
    )
    return parser


async def run_find_dep_files(
    item: Tuple[OrgRepo, GitRef], args: argparse.Namespace
) -> AsyncGenerator[Dict, None]:
    org_repo, git_ref = item
    log.debug(
        f"running find-dep-files on repo {org_repo.github_clone_url!r} ref {git_ref!r}"
    )
    name = f"dep-obs-find-dep-files-{org_repo.org}-{org_repo.repo}-{hex(randrange(1 << 32))[2:]}"

    async with containers.run(
        "dep-obs/find-dep-files:latest", name=name, cmd="/bin/bash",
    ) as c:
        await c.run("mkdir -p /repos", wait=True, check=True)
        await containers.ensure_repo(
            c, org_repo.github_clone_url, working_dir="/repos/"
        )
        await containers.ensure_ref(c, git_ref, working_dir="/repos/repo")
        branch, commit, tag, ripgrep_version = await asyncio.gather(
            containers.get_branch(c, working_dir="/repos/repo"),
            containers.get_commit(c, working_dir="/repos/repo"),
            containers.get_tag(c, working_dir="/repos/repo"),
            containers.get_ripgrep_version(c, working_dir="/repos/repo"),
        )
        log.debug(f"{name} stdout: {await c.log(stdout=True)}")
        log.debug(f"{name} stderr: {await c.log(stderr=True)}")

        for dep_file_path in await containers.find_files(
            args.glob, c, working_dir="/repos/repo"
        ):
            log.info(f"{c['Name']} found dep file: {dep_file_path}")
            yield dict(
                org=org_repo.org,
                repo=org_repo.repo,
                ref=git_ref.to_dict(),
                repo_url=org_repo.github_clone_url,
                commit=commit,
                branch=branch,
                tag=tag,
                versions={"ripgrep": ripgrep_version},
                dependency_file=DependencyFile.from_dict(
                    dict(
                        path=dep_file_path,
                        sha256=await containers.sha256sum(
                            c, dep_file_path, working_dir="/repos/repo"
                        )
                        or "",
                    )
                ).to_dict(),
            )


async def run_pipeline(
    source: Generator[Dict[str, Any], None, None], args: argparse.Namespace
) -> AsyncGenerator[Dict[str, Any], None]:
    log.info(f"started pipeline {__name__} with globs: {args.glob}")
    if args.docker_build:
        images: Iterable[DockerImage] = [docker_images["dep-obs/find-dep-files:latest"]]
        log.info(
            f"building images: {[image.base.repo_name_tag + ' as ' + image.local.repo_name_tag for image in images]}"
        )
        built_image_tags: Iterable[str] = await build_images(args.docker_pull, images)
        log.info(f"successfully built and tagged images {built_image_tags}")

    for item in source:
        org_repo, git_ref = (
            OrgRepo.from_github_repo_url(item["repo_url"]),
            GitRef.from_dict(item["ref"]),
        )
        log.debug(f"finding dep files for {org_repo} {git_ref}")
        try:
            async for dep_file in run_find_dep_files((org_repo, git_ref), args):
                yield dep_file
        except Exception as e:
            log.error(f"error running find_dep_files:\n{exc_to_str()}")
