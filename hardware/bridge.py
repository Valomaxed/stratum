"""Forward newline-delimited calibrated observations to the local twin API.

Examples:
  python hardware/bridge.py --demo
  python hardware/bridge.py --port COM3 --baud 115200   # optional pyserial
  Get-Content packets.jsonl | python hardware/bridge.py --stdin
"""
import argparse
import json
import sys
import urllib.request
import urllib.error


def forward(line, url):
    packet = json.loads(line)
    if not isinstance(packet, dict) or not isinstance(packet.get('measurements'), dict):
        raise ValueError('Packet must have a measurements object')
    body = json.dumps(packet, allow_nan=False).encode()
    req = urllib.request.Request(url, body, {'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument('--port'); source.add_argument('--stdin', action='store_true'); source.add_argument('--demo', action='store_true')
    p.add_argument('--baud', type=int, default=115200)
    p.add_argument('--url', default='http://127.0.0.1:8766/api/observations')
    p.add_argument('--protocol', choices=('single','multi'), default='single', help='Excitation protocol for the synthetic demo packet')
    p.add_argument('--refinement',choices=('legacy','sparse'),default='sparse',help='Refinement method for the synthetic demo packet')
    args = p.parse_args()
    if args.demo:
        sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))
        import numpy as np
        from twin.fem import demo_truss
        from twin.load_cases import LoadCaseSensors
        s = LoadCaseSensors(demo_truss(),args.protocol); damage = np.zeros(21); damage[13] = .3
        values=s.response(damage).reshape(s.case_count,s.physical_count)
        by_case={case['id']:{c['id']:float(v) for c,v in zip(s.catalog,row)} for case,row in zip(s.cases,values)}
        packet = {'load_scale':1, 'physics':True,'protocol':args.protocol,'refinement':args.refinement,'noise_std':0,
                  'measurements':by_case['LC1'] if args.protocol=='single' else by_case}
        print(json.dumps(forward(json.dumps(packet), args.url), indent=2)); return
    if args.port:
        try:
            import serial
        except ImportError:
            p.error('Serial input needs optional pyserial: python -m pip install pyserial')
        stream = serial.Serial(args.port, args.baud, timeout=1)
    else:
        stream = sys.stdin
    try:
        while True:
            line = stream.readline()
            if not line:
                if args.stdin: break
                continue
            try:
                if isinstance(line, bytes): line=line.decode('utf-8')
                output = forward(line, args.url)
                print(json.dumps(output), flush=True)
            except (ValueError, UnicodeDecodeError, urllib.error.URLError) as error:
                print(f'Packet rejected: {error}', file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        if args.port: stream.close()


if __name__ == '__main__':
    main()
