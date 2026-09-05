# Qingliao platform plugin for Hermes Agent.
# Registered via the plugin `register(ctx)` entry point; discovery scans
# the profile's `plugins/` (user) directory for a `plugin.yaml` manifest.
from .adapter import register
