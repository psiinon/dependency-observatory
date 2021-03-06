import asyncio
import logging
from typing import Iterable

import depobs.docker.containers as containers
from depobs.scanner.models.docker_image import DockerImage
from depobs.util.traceback_util import exc_to_str

log = logging.getLogger(__name__)


async def build_images(
    docker_pull: bool, images: Iterable[DockerImage]
) -> Iterable[str]:
    try:
        built_image_tags: Iterable[str] = await asyncio.gather(
            *[
                containers.build(
                    image.dockerfile_bytes, image.local.repo_name, pull=docker_pull
                )
                for image in images
            ]
        )
        return built_image_tags
    except Exception as err:
        log.error(f"error occurred building images: {err}\n{exc_to_str()}")
        raise err
