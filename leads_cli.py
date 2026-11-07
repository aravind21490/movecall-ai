"""Tiny admin tool for the human owner.

  python leads_cli.py list
  python leads_cli.py approve 3     (same effect as replying 'approve #3' in the room)
"""
import sys

import leads


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "list":
        for lead in leads.list_leads():
            print(
                f"#{lead['id']:<4} {lead['status']:<9} {lead['name'] or '-':<18} "
                f"{lead['pickup'] or '-'} -> {lead['destination'] or '-'}"
            )
        return 0
    if len(argv) == 3 and argv[1] == "approve" and argv[2].isdigit():
        ok = leads.set_status(int(argv[2]), "approved")
        print("approved" if ok else "no such lead")
        return 0 if ok else 1
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
