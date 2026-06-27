#!/usr/bin/env python3
"""Generate Gmail dot alias variants from a base email.

Gmail ignores dots in the local part — user.test@gmail.com == usertest@gmail.com.
Each variant routes to the same inbox, giving unique email addresses for signup.

Usage:
    python3 generate_email_list.py yourname -o email_list.txt
    python3 generate_email_list.py yourname -o email_list.txt --max 100 --max-dots 3
"""
import argparse
import itertools
import random
from pathlib import Path


def generate_variants(base_local: str, domain: str = "gmail.com", max_dots: int = 2) -> list[str]:
    """Generate Gmail dot alias variants with at most max_dots dots.

    - Dots placed in any gap between characters
    - No leading/trailing dots, no adjacent dots
    - Plus labels excluded (many signup flows reject +)
    """
    n = len(base_local)
    if n < 2:
        return [f"{base_local}@{domain}"]

    variants = []
    for combo in itertools.product(("", "."), repeat=n - 1):
        if combo.count(".") > max_dots:
            continue
        parts = [base_local[i] + combo[i] for i in range(n - 1)]
        parts.append(base_local[-1])
        variants.append("".join(parts) + f"@{domain}")
    return variants


def main():
    parser = argparse.ArgumentParser(description="Generate Gmail dot alias variants.")
    parser.add_argument("bases", nargs="*", default=["yourgmailuser"], help="Gmail local parts")
    parser.add_argument("-o", "--output", default="email_list.txt", help="output file")
    parser.add_argument("-m", "--max", type=int, default=None, help="max variants (random sample)")
    parser.add_argument("--max-dots", type=int, default=2, help="max dots per variant (default: 2)")
    parser.add_argument("--domain", default="gmail.com", help="Gmail domain (default: gmail.com)")
    args = parser.parse_args()

    all_variants = []
    for base in args.bases:
        all_variants.extend(generate_variants(base, domain=args.domain, max_dots=args.max_dots))

    unique = list(set(all_variants))
    if args.max and len(unique) > args.max:
        unique = random.sample(unique, args.max)

    random.shuffle(unique)
    Path(args.output).write_text("\n".join(unique) + "\n")
    print(f"Generated {len(unique)} unique variants (max {args.max_dots} dots) from {len(args.bases)} base(s) -> {args.output}")


if __name__ == "__main__":
    main()
