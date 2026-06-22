import json
import statistics
from collections import defaultdict, Counter
from typing import Optional


def load_data(path: str = "data_raw.json") -> list[dict]:
    with open(path) as f:
        return json.load(f)


def compute_stats(prices: list[float]) -> dict:
    if not prices:
        return {}
    s = sorted(prices)
    n = len(s)
    return {
        "count":  n,
        "mean":   round(statistics.mean(s), 2),
        "median": round(statistics.median(s), 2),
        "stdev":  round(statistics.stdev(s), 2) if n > 1 else 0.0,
        "min":    round(min(s), 2),
        "max":    round(max(s), 2),
        "p25":    round(s[int(n * 0.25)], 2),
        "p75":    round(s[int(n * 0.75)], 2),
    }


def bucket_distribution(prices: list[float]) -> dict[str, int]:
    buckets = {
        "Free":        0,
        "$0.01–$0.99": 0,
        "$1.00–$1.49": 0,
        "$1.50–$1.99": 0,
        "$2.00–$2.49": 0,
        "$2.50–$2.99": 0,
        "$3.00–$3.99": 0,
        "$4.00+":      0,
    }
    for p in prices:
        if p == 0:             buckets["Free"] += 1
        elif p < 1.00:         buckets["$0.01–$0.99"] += 1
        elif p < 1.50:         buckets["$1.00–$1.49"] += 1
        elif p < 2.00:         buckets["$1.50–$1.99"] += 1
        elif p < 2.50:         buckets["$2.00–$2.49"] += 1
        elif p < 3.00:         buckets["$2.50–$2.99"] += 1
        elif p < 4.00:         buckets["$3.00–$3.99"] += 1
        else:                  buckets["$4.00+"] += 1
    return buckets


def group_stats(data: list[dict], key: str) -> dict[str, dict]:
    groups: dict[str, list[float]] = defaultdict(list)
    for d in data:
        groups[d.get(key, "unknown")].append(d["price_usd"])
    return {k: compute_stats(v) for k, v in groups.items() if v}


def analyze(data: list[dict]) -> dict:
    addons     = [d for d in data if d.get("type") == "add_on"]
    menu_items = [d for d in data if d.get("type") == "menu_item"]

    # Use add-ons as primary if available, otherwise all items
    primary    = addons if addons else data
    pri_prices = [d["price_usd"] for d in primary]

    # By food category
    by_category = group_stats(primary, "category")

    # By price tier ($, $$, $$$, $$$$)
    by_price_tier = group_stats(primary, "price_tier")

    # Best/worst restaurants
    by_restaurant: dict[str, list[float]] = defaultdict(list)
    for d in primary:
        by_restaurant[d["restaurant"]].append(d["price_usd"])
    rest_avgs = {
        name: round(statistics.mean(p), 2)
        for name, p in by_restaurant.items() if p
    }
    sorted_rests = sorted(rest_avgs.items(), key=lambda x: x[1], reverse=True)

    price_counts = Counter(round(p, 2) for p in pri_prices)

    return {
        "total_data_points": len(data),
        "addon_count":       len(addons),
        "menu_item_count":   len(menu_items),
        "has_addon_data":    len(addons) > 0,
        "overall_stats":     compute_stats(pri_prices),
        "addon_stats":       compute_stats([d["price_usd"] for d in addons]) if addons else {},
        "menu_item_stats":   compute_stats([d["price_usd"] for d in menu_items]) if menu_items else {},
        "distribution":      bucket_distribution(pri_prices),
        "by_category":       by_category,
        "by_price_tier":     by_price_tier,
        "top_10_expensive":  sorted_rests[:10],
        "top_10_cheapest":   [r for r in sorted_rests if r[1] > 0][-10:][::-1],
        "most_common_prices":[{"price": p, "count": c} for p, c in price_counts.most_common(5)],
        "raw_addons":        data,
    }


def print_report(analysis: dict):
    from rich.console import Console
    from rich.table import Table
    from rich import box

    console = Console()
    stats = analysis.get("overall_stats", {})

    console.print("\n[bold green]===  AVOCADO PRICE REPORT  ===[/bold green]\n")
    console.print(f"[cyan]Total records:[/cyan]      {analysis['total_data_points']}")
    console.print(f"[cyan]Add-on charges:[/cyan]     {analysis['addon_count']}")
    console.print(f"[cyan]Avocado dishes:[/cyan]     {analysis['menu_item_count']}\n")

    if stats:
        console.print("[bold yellow]OVERALL STATS[/bold yellow]")
        console.print(f"  Avg:    [bold]${stats['mean']:.2f}[/bold]")
        console.print(f"  Median: [bold]${stats['median']:.2f}[/bold]")
        console.print(f"  Range:  ${stats['min']:.2f} – ${stats['max']:.2f}\n")

    t = Table(title="By Category", box=box.SIMPLE_HEAVY)
    t.add_column("Category", style="cyan")
    t.add_column("n", justify="right")
    t.add_column("Avg $", justify="right", style="yellow")
    t.add_column("Min $", justify="right")
    t.add_column("Max $", justify="right")
    for cat, s in sorted(analysis["by_category"].items(), key=lambda x: -x[1].get("mean", 0)):
        t.add_row(cat, str(s["count"]), f"${s['mean']:.2f}", f"${s['min']:.2f}", f"${s['max']:.2f}")
    console.print(t)

    t2 = Table(title="By Price Tier", box=box.SIMPLE_HEAVY)
    t2.add_column("Tier", style="cyan")
    t2.add_column("n", justify="right")
    t2.add_column("Avg $", justify="right", style="yellow")
    for tier, s in sorted(analysis["by_price_tier"].items()):
        t2.add_row(tier or "unknown", str(s["count"]), f"${s['mean']:.2f}")
    console.print(t2)


if __name__ == "__main__":
    data = load_data("data_raw.json")
    analysis = analyze(data)
    print_report(analysis)
    with open("data_analysis.json", "w") as f:
        json.dump({k: v for k, v in analysis.items() if k != "raw_addons"}, f, indent=2)
    print("\nSaved to data_analysis.json")
