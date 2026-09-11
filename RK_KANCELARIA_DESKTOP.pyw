# -*- coding: utf-8 -*-

"""Launcher RK KANCELARIA 0.2.0-dev3.

Po spakowaniu PyInstallerem jest jedynym punktem wejścia:
- zwykły start -> Desktop,
- --sync-gui -> synchronizacja Installed/Portable,
- --self-test -> test backendu i Qt.
"""
from __future__ import annotations

import sys

if "--sync-gui" in sys.argv:
    from rk_sync import main as sync_main
    raise SystemExit(sync_main(["--gui"]))

from desktop import main
raise SystemExit(main())
