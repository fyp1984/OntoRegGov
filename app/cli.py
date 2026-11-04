"""命令行入口：python -m app.cli seed|demo。"""
import sys
from . import seed


def main():
    if len(sys.argv) < 2:
        print("用法: python -m app.cli [seed|demo]")
        return
    cmd = sys.argv[1]
    if cmd == "seed":
        seed.seed()
    elif cmd == "demo":
        from scripts.demo_e2e import run
        run()
    elif cmd == "import-checks":
        from .ontology import checks_import
        s = checks_import.import_checks()
        import json
        print("[import-checks]", json.dumps({k: v for k, v in s.items()}, ensure_ascii=False))
    elif cmd == "import-control-placeholders":
        from .ontology import checks_import
        import json
        s = checks_import.import_control_placeholders()
        print("[import-control-placeholders]", json.dumps(s, ensure_ascii=False))
    elif cmd == "demo-checks":
        from scripts.demo_checks import run
        run()
    else:
        print("未知命令:", cmd)


if __name__ == "__main__":
    main()
