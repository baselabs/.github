"""Real GHCR round-trip payloads, generated only on GitHub-hosted runners."""
from pathlib import Path
import sys

PAYLOADS = {
    'payload.txt': b'BaseLabs qualified artifact custody v1\n',
    'payload with spaces.bin': bytes(range(256)) + b'\x00\xff\r\nqualified\n',
}


def main():
    command, target = sys.argv[1:]
    directory = Path(target)
    if command == 'create':
        (directory / 'nested').mkdir(parents=True)
        for name, content in PAYLOADS.items():
            parent = directory / 'nested' if name == 'payload.txt' else directory
            (parent / name).write_bytes(content)
    elif command == 'verify':
        if {p.name for p in directory.iterdir()} != set(PAYLOADS):
            raise SystemExit('Fetched payload set differs from the candidate payload set')
        for name, expected in PAYLOADS.items():
            if (directory / name).read_bytes() != expected:
                raise SystemExit('Fetched bytes differ from the candidate: ' + name)
        print('Both payloads match every candidate byte, including binary content and basenames.')
    else:
        raise SystemExit('unknown fixture operation')


if __name__ == '__main__':
    main()
