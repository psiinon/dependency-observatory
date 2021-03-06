import asyncio
import aiohttp
import backoff
import math
from typing import Any, AsyncGenerator, Dict, Iterable, Optional, TypedDict
import logging

from depobs.clients.aiohttp_client_config import AIOHTTPClientConfig
from depobs.scanner.models.package_meta_result import Result
from depobs.util.serialize_util import grouper
from depobs.util.traceback_util import exc_to_str

log = logging.getLogger(__name__)


class NPMRegistryClientConfig(
    AIOHTTPClientConfig, total=False
):  # don't require keys defined below

    # an npm registry access token for fetch_npm_registry_metadata. Defaults NPM_PAT env var. Should be read-only.
    npm_auth_token: str


def aiohttp_session(config: NPMRegistryClientConfig) -> aiohttp.ClientSession:
    # "Accept": "application/json vnd.npm.install-v1+json; q=1.0, # application/json; q=0.8, */*"
    # doesn't include author and maintainer info

    # alternatively npm login then
    # npm view [<@scope>/]<name>[@<version>] [<field>[.<subfield>]...]

    # the registry does support GET·/{package}/{version}
    #
    # https://github.com/npm/registry/blob/master/docs/REGISTRY-API.md#getpackageversion
    #
    # but it seems to be busted for scoped packages e.g.
    # e.g. https://registry.npmjs.com/@hapi/bounce/2.0.8
    #
    # https://replicate.npmjs.com/ (flattened scopes) seems to be busted
    headers = {"Accept": "application/json", "User-Agent": config["user_agent"]}
    # from 'npm token create --read-only' to give us a higher rate limit
    if config.get("npm_auth_token", None):
        headers["Authorization"] = f"Bearer {config['npm_auth_token']}"

    return aiohttp.ClientSession(
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=config["total_timeout"]),
        connector=aiohttp.TCPConnector(limit=config["max_connections"]),
        raise_for_status=True,
    )


async def async_query(
    session: aiohttp.ClientSession, package_name: str, dry_run: bool
) -> Optional[Dict]:
    # NB: scoped packages OK e.g. https://registry.npmjs.com/@babel/core
    url = f"https://registry.npmjs.com/{package_name}"
    response_json: Optional[Dict] = None
    if dry_run:
        log.warn(f"in dry run mode: skipping GET {url}")
        return response_json

    log.debug(f"GET {url}")
    try:
        response = await session.get(url)
        response_json = await response.json()
        return response_json
    except aiohttp.ClientResponseError as err:
        if is_not_found_exception(err):
            log.info(f"got 404 for package {package_name}")
            log.debug(f"{url} not found: {err}")
            return None
        raise err


def is_not_found_exception(err: Exception) -> bool:
    is_aiohttp_404 = isinstance(err, aiohttp.ClientResponseError) and err.status == 404
    return is_aiohttp_404


async def fetch_npm_registry_metadata(
    config: NPMRegistryClientConfig,
    package_names: Iterable[str],
    total_packages: Optional[int] = None,
) -> AsyncGenerator[Result[Dict[str, Dict]], None]:
    """
    Fetches npm registry metadata for one or more node package names
    """
    total_groups: Optional[int] = None
    if total_packages:
        total_groups = math.ceil(total_packages / config["package_batch_size"])
    async with aiohttp_session(config) as s:
        async_query_with_backoff = backoff.on_exception(
            backoff.expo,
            (aiohttp.ClientResponseError, aiohttp.ClientError, asyncio.TimeoutError),
            max_tries=config["max_retries"],
            giveup=is_not_found_exception,
            logger=log,
        )(async_query)

        for i, group in enumerate(grouper(package_names, config["package_batch_size"])):
            log.info(f"fetching group {i} of {total_groups}")
            try:
                group_results = await asyncio.gather(
                    *[
                        async_query_with_backoff(s, package_name, config["dry_run"])
                        for package_name in group
                        if package_name is not None
                    ]
                )
                for result in group_results:
                    if result is not None:
                        yield result
            except Exception as err:
                log.error(
                    f"error fetching group {i} for package names {group}: {err}:\n{exc_to_str()}"
                )
                yield err
