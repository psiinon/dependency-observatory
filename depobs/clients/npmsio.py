import asyncio
import logging
from typing import Any, AsyncGenerator, Dict, Iterable, Optional

import aiohttp

from depobs.clients.aiohttp_client_config import AIOHTTPClientConfig
from depobs.util.serialize_util import grouper
from depobs.scanner.models.package_meta_result import Result

log = logging.getLogger(__name__)


class NPMSIOClientConfig(
    AIOHTTPClientConfig, total=False
):  # don't require keys defined below
    pass


def aiohttp_session(config: NPMSIOClientConfig) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": config["user_agent"],
        },
        timeout=aiohttp.ClientTimeout(total=config["total_timeout"]),
        connector=aiohttp.TCPConnector(limit=config["max_connections"]),
        raise_for_status=True,
    )


async def async_query(
    session: aiohttp.ClientSession, json: Iterable[str], dry_run: bool
) -> Optional[Dict]:
    url = "https://api.npms.io/v2/package/mget"
    log.debug(f"posting {json} to {url}")
    response_json: Optional[Dict] = None
    if dry_run:
        log.warn(f"in dry run mode: skipping POST")
    else:
        response = await session.post(url, json=json)
        response_json = await response.json()
    log.debug(f"got response json {response_json!r}")
    return response_json


async def fetch_npmsio_scores(
    config: NPMSIOClientConfig,
    package_names: Iterable[str],
    total_packages: Optional[int] = None,
) -> AsyncGenerator[Result[Dict[str, Dict]], None]:
    """
    Fetches npms.io score and analysis for one or more node package names

    Uses: https://api-docs.npms.io/#api-Package-GetMultiPackageInfo
    """
    async with aiohttp_session(config) as s:
        group_results = await asyncio.gather(
            *[
                async_query(
                    s,
                    [
                        package_name
                        for package_name in group
                        if package_name is not None
                    ],
                    config["dry_run"],
                )
                for group in grouper(package_names, config["package_batch_size"])
                if group is not None
            ]
        )
        # NB: org/scope e.g. "@babel" in @babel/babel is flattened into the scope field.
        # pull {data1}, {data2} from {package_name_1: {data1}, package_name_2: {data2}}
        for group_result in group_results:
            if group_result is None:
                continue

            for result in group_result.values():
                yield result
