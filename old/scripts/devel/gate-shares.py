"""Print agents' suite CPU shares, warn above 10%, and enforce their limits."""
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sys


def check(admissions, measurements):
    limits = {}
    try:
        lines = admissions.read_text().splitlines()
    except FileNotFoundError:
        lines = []
    for number, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        fields = line.split(maxsplit=2)
        try:
            name, maximum, reason = fields
            maximum = Decimal(maximum)
            if (not maximum.is_finite() or not 0 < maximum <= 100
                    or name in limits or not reason.strip()):
                raise ValueError
        except (ValueError, InvalidOperation):
            raise ValueError(f'{admissions}:{number}: expected NAME MAX_PERCENT REASON; '
                             'unique name, percent above 0 and at most 100, reason in words') from None
        limits[name] = maximum
    cpu = {}
    for line in measurements.read_text().splitlines():
        name, value = line.split()
        value = Decimal(value)
        if not value.is_finite() or value < 0:
            raise ValueError(f'{measurements}: invalid CPU seconds for {name}')
        cpu[name] = cpu.get(name, Decimal(0)) + value
    total = sum(cpu.values(), Decimal(0))
    failed = False
    for name, value in sorted(cpu.items(), key=lambda item: (-item[1], item[0])):
        share = value * 100 / total if total else Decimal(0)
        print(f'gate-share {name} {value:.3f} {share:.3f}%', file=sys.stderr)
        maximum = limits.get(name, Decimal('12.5'))
        if share > maximum:
            admission = ('add NAME MAX_PERCENT REASON' if name not in limits else
                         f'exceeds MAX_PERCENT {maximum}')
            print(f'check.sh: {name} CPU share {share:.3f}%: {admission} in {admissions}',
                  file=sys.stderr)
            failed = True
        elif name not in limits and share > 10:
            print(f'check.sh: {name} CPU share {share:.3f}%: past 10%, add a line to '
                  f'{admissions} before it passes 12.5%', file=sys.stderr)
    return int(failed)


if __name__ == '__main__':
    try:
        sys.exit(check(Path(sys.argv[1]), Path(sys.argv[2])))
    except (OSError, ValueError, InvalidOperation) as error:
        print(f'check.sh: gate-shares: {error}', file=sys.stderr)
        sys.exit(1)
