"""
Скрипт-разовик: загружает filler_items из db/filler_items_seed.json в Supabase.
Запуск: python -m scripts.seed_filler_items
"""
import json
from services import file_storage as subabase_client
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services import supabase_client
from utils import config


def main() -> None:
    config.setup_logging()
    
    seed_path = Path(__file__).parent.parent / "db" / "filler_items_seed.json"
    if not seed_path.exists():
        print(f"❌ Не найден файл {seed_path}")
        sys.exit(1)
    
    with open(seed_path, encoding="utf-8") as f:
        items = json.load(f)
    
    print(f"📦 Загружаю {len(items)} filler-вещей в Supabase...")
    inserted = supabase_client.seed_filler_items(items)
    print(f"✅ Загружено: {inserted}")


if __name__ == "__main__":
    main()
