"""Platform router for launchd/cron installation."""

from __future__ import annotations

import sys

from src.scheduling.os.cron import CronScheduleInstaller
from src.scheduling.os.launchd import LaunchdScheduleInstaller
from src.scheduling.os.status import ScheduleInstallStatusDAO, ScheduleLogPathsDAO
from src.scheduling.store import ScheduleStore
from src.scheduling.os.executable_locator import ScheduleExecutableLocator
from src.scheduling.os.logs import ScheduleLogs

__all__ = ["ScheduleOSIntegration"]


class ScheduleOSIntegration:
    """Install/uninstall schedules into the local OS scheduler."""

    def __init__(
        self,
        *,
        store: type[ScheduleStore] = ScheduleStore,
        launchd_installer: LaunchdScheduleInstaller | None = None,
        cron_installer: CronScheduleInstaller | None = None,
    ) -> None:
        """Bind the platform router to the canonical store/installers."""
        self._store: type[ScheduleStore] = store
        self._launchd: LaunchdScheduleInstaller = launchd_installer or LaunchdScheduleInstaller()
        self._cron: CronScheduleInstaller = cron_installer or CronScheduleInstaller()

    def install(self, *, reference: str) -> ScheduleInstallStatusDAO:
        """Install ``reference`` into the local OS scheduler."""
        loaded = self._store.load(reference=reference)
        executable = ScheduleExecutableLocator.locate()
        log_paths: ScheduleLogPathsDAO = ScheduleLogs.ensure(schedule_id=loaded.schedule_id)
        if sys.platform == "darwin":
            return self._launchd.install(
                definition=loaded.definition,
                executable=executable,
                log_paths=log_paths,
            )
        if sys.platform.startswith("linux"):
            return self._cron.install(
                definition=loaded.definition,
                executable=executable,
                log_paths=log_paths,
            )
        raise RuntimeError(f"Unsupported scheduler platform: {sys.platform}")

    def uninstall(self, *, reference: str) -> ScheduleInstallStatusDAO:
        """Uninstall ``reference`` from the local OS scheduler."""
        loaded = self._store.load(reference=reference)
        if sys.platform == "darwin":
            return self._launchd.uninstall(definition=loaded.definition)
        if sys.platform.startswith("linux"):
            return self._cron.uninstall(definition=loaded.definition)
        raise RuntimeError(f"Unsupported scheduler platform: {sys.platform}")

    def status(self, *, reference: str) -> ScheduleInstallStatusDAO:
        """Report whether ``reference`` is registered with the local OS scheduler."""
        loaded = self._store.load(reference=reference)
        if sys.platform == "darwin":
            return self._launchd.status(definition=loaded.definition)
        if sys.platform.startswith("linux"):
            return self._cron.status(definition=loaded.definition)
        raise RuntimeError(f"Unsupported scheduler platform: {sys.platform}")
