#!/usr/bin/env python3
"""Analyze a job-listing CSV and rank deduplicated results.

Origin: April 2023 discussion of Indeed CSV cleanup and salary/rating analysis.
Reconstructed: November 2026 (not recovered original source).
Usage: python indeed-csv-analyzer.py jobs.csv -o ranked.csv --min-rating 3.5
Dependencies: standard library. Exit: 0 success, 2 invalid input.
"""
import argparse
import csv
import sys
from pathlib import Path

def field(row, *names):
    normalized = {k.lower().replace('_', '').replace(' ', ''): v for k, v in row.items() if k}
    return next((str(normalized[n.lower().replace('_', '').replace(' ', '')]).strip()
                 for n in names if normalized.get(n.lower().replace('_', '').replace(' ', ''))), '')

def number(value):
    try:
        return float(value.replace('$', '').replace(',', '').strip())
    except (ValueError, AttributeError):
        return 0.0

def analyze(rows, minimum):
    unique = {}
    for i, row in enumerate(rows):
        key = field(row, 'jobkey', 'job_key', 'jk', 'jobUrl', 'url') or f'row-{i}'
        rating = number(field(row, 'companyRating', 'rating'))
        if rating < minimum:
            continue
        record = {'company': field(row, 'company', 'companyName'),
                  'title': field(row, 'title', 'jobTitle'),
                  'minimum_salary': field(row, 'minimumSalary', 'minSalary', 'salaryMin'),
                  'company_rating': field(row, 'companyRating', 'rating'),
                  'indeed_url': field(row, 'jobUrl', 'url', 'indeedUrl')}
        if key not in unique or rating > number(unique[key]['company_rating']):
            unique[key] = record
    return sorted(unique.values(), key=lambda r: (-number(r['company_rating']),
                                                   -number(r['minimum_salary']), r['company'].lower()))

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('csv_file', type=Path)
    p.add_argument('-o', '--output', type=Path, default=Path('ranked-jobs.csv'))
    p.add_argument('--min-rating', type=float, default=0)
    a = p.parse_args()
    try:
        with a.csv_file.open(newline='', encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
        if not rows:
            raise ValueError('CSV contains no job rows')
        results = analyze(rows, a.min_rating)
        with a.output.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=['company', 'title', 'minimum_salary', 'company_rating', 'indeed_url'])
            w.writeheader()
            w.writerows(results)
        print(f'Wrote {len(results)} unique listings to {a.output}')
        return 0
    except (OSError, ValueError, csv.Error) as e:
        print(f'Error: {e}', file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())
