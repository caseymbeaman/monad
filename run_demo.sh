#!/usr/bin/env bash
# Starts the Monad Blitz demo dashboard (demo_app.py) with its dark theme.
# The theme is passed here instead of in .streamlit/config.toml so app.py keeps its own look.
cd "$(dirname "$0")"
exec streamlit run demo_app.py \
  --theme.base dark \
  --theme.primaryColor "#C2456F" \
  --theme.backgroundColor "#0B0A0B" \
  --theme.secondaryBackgroundColor "#171315" \
  --theme.textColor "#F5EEF1" \
  "$@"
