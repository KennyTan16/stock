import json
from pathlib import Path
import sys

if len(sys.argv) > 1:
    file_path = sys.argv[1]
else:
    # Use most recent result
    results_dir = Path(__file__).parent.parent / "results"
    files = sorted(results_dir.glob("backtest_enhanced_spike_*.json"))
    if not files:
        print("No result files found")
        sys.exit(1)
    file_path = files[-1]

print(f"Analyzing: {file_path}\n")

with open(file_path) as f:
    data = json.load(f)

alerts = data['alerts']
print(f"Total Alerts: {len(alerts)}\n")

# Quality score distribution
from collections import Counter
scores = [round(a['quality_score']) for a in alerts]
print("Quality Score Distribution:")
for q, c in sorted(Counter(scores).items()):
    print(f"  Q{q}: {c} alerts")

# Winners vs Losers quality ranges
winners = [a for a in alerts if a['outcome']['hit'] == 'target']
losers = [a for a in alerts if a['outcome']['hit'] == 'stop']

if winners:
    winner_q = [a['quality_score'] for a in winners]
    print(f"\nWinners ({len(winners)} alerts):")
    print(f"  Quality range: {min(winner_q):.1f} - {max(winner_q):.1f}")
    print(f"  Avg quality: {sum(winner_q)/len(winner_q):.1f}")

if losers:
    loser_q = [a['quality_score'] for a in losers]
    print(f"\nLosers ({len(losers)} alerts):")
    print(f"  Quality range: {min(loser_q):.1f} - {max(loser_q):.1f}")
    print(f"  Avg quality: {sum(loser_q)/len(loser_q):.1f}")

# Session breakdown
from collections import defaultdict
session_stats = defaultdict(lambda: {'total': 0, 'wins': 0})
for a in alerts:
    session = a['session']
    session_stats[session]['total'] += 1
    if a['outcome']['hit'] == 'target':
        session_stats[session]['wins'] += 1

print("\nSession Win Rates:")
for session in ['PREMARKET', 'REGULAR', 'POSTMARKET']:
    if session in session_stats:
        stats = session_stats[session]
        wr = (stats['wins'] / stats['total'] * 100) if stats['total'] > 0 else 0
        print(f"  {session}: {stats['wins']}/{stats['total']} = {wr:.1f}%")

# Bars to stop/target
winner_bars = [a['outcome']['bars_held'] for a in winners]
loser_bars = [a['outcome']['bars_held'] for a in losers]

if winner_bars:
    print(f"\nWinners hold time: avg {sum(winner_bars)/len(winner_bars):.1f} bars (range {min(winner_bars)}-{max(winner_bars)})")
if loser_bars:
    print(f"Losers hold time: avg {sum(loser_bars)/len(loser_bars):.1f} bars (range {min(loser_bars)}-{max(loser_bars)})")
