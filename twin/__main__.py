import argparse
import json


def main():
    parser = argparse.ArgumentParser(description="Structural digital twin research prototype")
    commands = parser.add_subparsers(dest="command", required=True)
    server = commands.add_parser("serve", help="Start the local viewer and HTTP API")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8766)
    seismic_verify=commands.add_parser('seismic-verify',help='Run independent OpenSees seismic verification and time-step convergence')
    seismic_verify.add_argument('--opensees-python',required=True)
    train = commands.add_parser("train", help="Generate synthetic FEM cases and train/evaluate random forests")
    train.add_argument("--samples", type=int, default=2400)
    train.add_argument("--seed", type=int, default=2026)
    bridge_train=commands.add_parser('bridge-train',help='Generate full dynamic bridge crossings and train a scoped RF baseline')
    bridge_train.add_argument('--cases-per-member',type=int,default=40)
    bridge_train.add_argument('--healthy-cases',type=int,default=400)
    bridge_train.add_argument('--workers',type=int,default=4)
    bridge_train.add_argument('--seed',type=int,default=281026)
    bridge_sparse=commands.add_parser('bridge-sparse-study',help='Compare paired dynamic bridge sensor budgets and placements')
    bridge_sparse.add_argument('--workers',type=int,default=2)
    study = commands.add_parser("study", help="Train and benchmark paired single/multiple static load protocols")
    study.add_argument("--samples", type=int, default=2400)
    study.add_argument("--seed", type=int, default=2026)
    study.add_argument("--physics-cases", type=int, default=60)
    robust=commands.add_parser("robust-study",help="Tune sparse refinement on fresh validation cases, then audit on fresh held-out cases")
    robust.add_argument("--validation-cases",type=int,default=120)
    robust.add_argument("--test-cases",type=int,default=240)
    robust.add_argument("--workers",type=int,default=2)
    robust.add_argument("--validation-seed",type=int,default=31027)
    robust.add_argument("--test-seed",type=int,default=41027)
    demo = commands.add_parser("demo", help="Print a healthy/damaged numerical comparison")
    demo.add_argument("--model", choices=("planar", "space"), default="planar")
    args = parser.parse_args()
    if args.command == "serve":
        from .server import serve
        serve(args.host, args.port)
    elif args.command == 'seismic-verify':
        from .seismic_benchmark import run
        report=run(args.opensees_python)
        print(json.dumps({'passed':report['passed'],'report':'data/seismic-validation/report.md'}))
        if not report['passed']:raise SystemExit(1)
    elif args.command == "train":
        from .learning import train
        print(json.dumps(train(args.samples, args.seed), indent=2))
    elif args.command == "study":
        from .experiments import study
        report = study(args.samples,args.seed,args.physics_cases)
        print(json.dumps({"samples":report["samples"],"test_cases":report["test_cases"],
                         "elapsed_seconds":report["elapsed_seconds"],"report":"data/load-study/report.json"},indent=2))
    elif args.command=="robust-study":
        from .robust_study import run
        report=run(args.validation_cases,args.test_cases,args.workers,args.validation_seed,args.test_seed)
        print(json.dumps({"validation_cases":report["validation_cases"],"test_cases":report["test_cases"],
                          "elapsed_seconds":report["elapsed_seconds"],"report":"data/robust-study/report.json"},indent=2))
    elif args.command=='bridge-train':
        from .bridge_learning import train as train_bridge
        train_bridge(args.cases_per_member,args.healthy_cases,args.workers,args.seed)
    elif args.command=='bridge-sparse-study':
        from .bridge_sparse import run as sparse_bridge
        sparse_bridge(args.workers)
    else:
        import numpy as np
        from .models import FACTORIES
        model = FACTORIES[args.model](); damage = np.zeros(len(model.members))
        target = 4 if args.model == "space" else 13
        damage[target] = 0.3
        print(model.name, f"({model.dim}D, {len(model.nodes)} joints, {len(model.members)} members)")
        for name, loss in (("healthy", np.zeros_like(damage)), (f"M{target+1:02} loss 30%", damage)):
            result = model.solve(loss)
            print(name, "peak displacement magnitude (mm):", round(np.max(np.linalg.norm(result["displacement"].reshape(-1,model.dim),axis=1))*1000, 4),
                  "first frequencies (Hz):", model.modes(loss, 3)["frequencies"].round(3))


if __name__ == "__main__":
    main()
