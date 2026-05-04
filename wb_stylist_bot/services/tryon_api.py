"""
Клиент FASHN.AI для виртуальной примерки.
API docs: https://docs.fashn.ai/
Endpoints:
  POST /v1/run         — запустить примерку
  GET  /v1/status/{id} — статус (polling)
"""
import asyncio
import logging
from typing import Optional

import httpx

from utils import config

log = logging.getLogger(__name__)

API_BASE = "https://api.fashn.ai/v1"
MAX_POLLS = 30
POLL_INTERVAL = 3  # секунд


async def run_tryon(
    model_image_url: str,
    garment_image_url: str,
    category: str = "tops",
    timeout: float = 120.0,
) -> Optional[str]:
    """
    Запускает примерку и ждёт результат.
    
    Args:
        model_image_url: URL фото человека
        garment_image_url: URL фото вещи
        category: 'tops' | 'bottoms' | 'one-pieces'
    
    Returns:
        URL результата или None при ошибке.
    """
    headers = {
        "Authorization": f"Bearer {config.FASHN_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model_name": "tryon-v1.6",
        "inputs": {
            "model_image": model_image_url,
            "garment_image": garment_image_url,
            "category": category,
        },
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        # 1. Запуск
        try:
            r = await client.post(f"{API_BASE}/run", headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as e:
            log.error(f"FASHN run failed: {e}")
            try:
                log.error(f"FASHN response: {r.text[:500]}")
            except Exception:
                pass
            return None

        prediction_id = data.get("id")
        if not prediction_id:
            log.error(f"FASHN: no prediction id in response: {data}")
            return None

        log.info(f"FASHN: started prediction {prediction_id} for category={category}")

        # 2. Polling
        for poll in range(MAX_POLLS):
            await asyncio.sleep(POLL_INTERVAL)
            try:
                r = await client.get(f"{API_BASE}/status/{prediction_id}", headers=headers)
                r.raise_for_status()
                status_data = r.json()
            except httpx.HTTPError as e:
                log.warning(f"FASHN poll {poll} failed: {e}")
                continue

            status = status_data.get("status")
            log.debug(f"FASHN {prediction_id} status: {status}")

            if status == "completed":
                output = status_data.get("output") or []
                if output and isinstance(output, list):
                    log.info(f"FASHN: completed in ~{(poll+1) * POLL_INTERVAL}s")
                    return output[0]
                log.error(f"FASHN: completed but no output: {status_data}")
                return None

            if status in ("failed", "canceled"):
                error = status_data.get("error") or "unknown error"
                log.error(f"FASHN: prediction failed: {error}")
                return None

        log.error(f"FASHN: prediction {prediction_id} timed out after {MAX_POLLS * POLL_INTERVAL}s")
        return None


async def chain_tryon(
    starting_model_url: str,
    items_in_order: list[dict],
    progress_callback=None,
) -> Optional[str]:
    """
    Последовательная примерка нескольких вещей.
    
    Args:
        starting_model_url: исходное фото юзера
        items_in_order: список вещей, отсортированный по порядку одевания.
                        Каждый item: {name, photo_url, fashn_category}
        progress_callback: async callable(current_index, total, item_name) для прогресса
    
    Returns:
        URL финального результата или None.
    """
    current_image = starting_model_url

    for i, item in enumerate(items_in_order, start=1):
        if progress_callback:
            await progress_callback(i, len(items_in_order), item["name"])

        result = await run_tryon(
            model_image_url=current_image,
            garment_image_url=item["photo_url"],
            category=item["fashn_category"],
        )
        if not result:
            log.error(f"Chain tryon failed at step {i}/{len(items_in_order)}: {item['name']}")
            return None

        current_image = result

    return current_image
