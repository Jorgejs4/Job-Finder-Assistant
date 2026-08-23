"""CLI entry point for the shared per-user workflow scheduler."""

from utils.supabase_client import create_server_client
from utils.workflow_dispatch import dispatch_workflow
from worker.scheduler import Scheduler


def main() -> None:
    client = create_server_client()

    def dispatch(user_id, settings):
        dispatch_workflow(
            user_id,
            settings,
            workflow="tenant-scrape.yml",
        )

    count = Scheduler(client, dispatch).dispatch_due(limit=20)
    print(f"[Scheduler] {count} workflow(s) despachado(s)")


if __name__ == "__main__":
    main()
