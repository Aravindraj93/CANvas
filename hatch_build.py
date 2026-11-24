"""Require and bundle built browser assets for distributable artifacts."""
from pathlib import Path
from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if version == 'editable':
            return  # Source desktop development does not require Node.
        dist = Path(self.root) / 'frontend' / 'dist'
        if not (dist / 'index.html').is_file():
            raise RuntimeError('Browser assets missing. Run npm ci and npm run build in frontend before packaging.')
        destination = 'backend/static' if self.target_name == 'wheel' else 'frontend/dist'
        build_data.setdefault('force_include', {})[str(dist)] = destination

