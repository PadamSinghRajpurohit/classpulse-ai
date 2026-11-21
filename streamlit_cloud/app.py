from __future__ import annotations

import runpy
import os
import sys
from pathlib import Path

# Streamlit Community Cloud runs this entrypoint from its subdirectory so it
# can use streamlit_cloud/requirements.txt without changing Vercel dependencies.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ["CLASSPULSE_DEPLOYMENT"] = "streamlit_community_cloud"

# Execute the full app as the script entrypoint so its Streamlit page config and
# main() run normally. The root app loads secrets before importing services.
runpy.run_path(str(PROJECT_ROOT / "app.py"), run_name="__main__")
