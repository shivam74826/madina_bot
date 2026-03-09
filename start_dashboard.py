"""Quick launcher for the dashboard in preview mode."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard.app import run_standalone_dashboard
run_standalone_dashboard()
