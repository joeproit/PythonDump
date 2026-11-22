#!/usr/bin/env python3
"""Calculate MTG opening-hand land distributions exactly and by simulation.

Origin: February 2025 deck probability discussion.
Reconstructed: November 2026 (not recovered original source).
Usage: python mtg-deck-simulator.py --deck 60 --lands 24 --hand 7 --trials 100000
Dependencies: standard library. Exit: 0 success, 2 invalid input.
"""
import argparse
import math
import random

def probability(deck, lands, hand, n):
    if n < 0 or n > lands or hand-n > deck-lands:
        return 0.0
    return math.comb(lands, n)*math.comb(deck-lands, hand-n)/math.comb(deck, hand)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name, default in [('deck',60),('lands',24),('hand',7),('trials',100000),('seed',2025),('min-lands',2),('max-lands',4)]:
        p.add_argument('--'+name, type=int, default=default)
    a = p.parse_args()
    if not (a.deck > 0 and 0 <= a.lands <= a.deck and 0 <= a.hand <= a.deck
            and a.trials > 0 and 0 <= a.min_lands <= a.max_lands <= a.hand):
        p.error('Invalid deck, hand, land or trial parameters')
    rng = random.Random(a.seed)
    population = [1]*a.lands + [0]*(a.deck-a.lands)
    counts = [0]*(a.hand+1)
    for _ in range(a.trials):
        counts[sum(rng.sample(population, a.hand))] += 1
    print('Lands | Exact % | Simulated %')
    for n in range(a.hand+1):
        print(f'{n:5} | {100*probability(a.deck,a.lands,a.hand,n):7.3f} | {100*counts[n]/a.trials:11.3f}')
    exact = sum(probability(a.deck,a.lands,a.hand,n) for n in range(a.min_lands,a.max_lands+1))
    sim = sum(counts[a.min_lands:a.max_lands+1])/a.trials
    print(f'Keepable ({a.min_lands}-{a.max_lands} lands): exact {exact:.2%}; simulated {sim:.2%}')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
