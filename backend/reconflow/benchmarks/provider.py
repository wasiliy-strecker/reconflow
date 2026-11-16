"""Pinned official SDK with a single-attempt, Decimal-preserving HTTP transport."""

from decimal import Decimal
from functools import partial

import requests
from vastai import VastAI
from vastai.api.client import VastClient

from reconflow.benchmarks.protocol import decimal
from reconflow.config import settings


class SingleAttemptClient(VastClient):
    def _request(self, method, url, headers, json_data=None, timeout=None):
        # SDK 1.11.0 calls retry an attempt count (0 sends no request). Override
        # the transport as well: no redirect can replay a paid PUT or leak auth.
        with requests.Session() as session:
            response = session.request(
                method, url, headers=headers, json=json_data, timeout=(3, 10), allow_redirects=False
            )
        if 300 <= response.status_code < 400:
            raise requests.HTTPError("Unexpected provider redirect", response=response)
        response.json = partial(response.json, parse_float=Decimal)
        return response


class VastProvider:
    def __init__(self):
        key = settings().vast_api_key.get_secret_value()
        if not key:
            raise ValueError("Vast.ai ist noch nicht konfiguriert.")
        self.sdk = VastAI(api_key=key, server_url="https://console.vast.ai", retry=1, quiet=True)
        self.sdk.client = SingleAttemptClient(key, "https://console.vast.ai", retry=1, timeout=10)

    def offers(self, offer_id=None):
        query = {"num_gpus": {"eq": 1}, "gpu_ram": {"gte": 8192}, "reliability2": {"gte": 0.98}}
        if offer_id is not None:
            query["id"] = {"eq": offer_id}
        rows = self.sdk.search_offers(
            query=query,
            type="on-demand",
            order="dph_total",
            limit=50,
            storage=settings().gpu_disk_gb,
        )
        return [self.normalize(row) for row in rows]

    @staticmethod
    def normalize(row):
        # Missing tariffs are not zero tariffs. Such offers cannot be rented.
        return {
            "id": int(row["id"]),
            "gpu": str(row["gpu_name"]),
            "vram_mib": int(row["gpu_ram"]),
            "num_gpus": int(row["num_gpus"]),
            "hourly_usd": str(decimal(row["dph_total"])),
            "storage_usd_gb_month": str(decimal(row["storage_cost"])),
            "download_usd_gb": str(decimal(row["inet_down_cost"])),
            "upload_usd_gb": str(decimal(row["inet_up_cost"])),
        }

    def create(self, offer_id, label, env, command):
        return self.sdk.create_instance(
            id=offer_id,
            image=settings().gpu_runner_image,
            disk=settings().gpu_disk_gb,
            label=label,
            env=env,
            runtype="args",
            args=["bash", "-c", command],
            cancel_unavail=True,
        )

    def instances(self):
        return self.sdk.show_instances()

    def destroy(self, instance_id):
        return self.sdk.destroy_instance(id=int(instance_id))
