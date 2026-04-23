"""Report persistence adapter."""

from typing import Optional

from ...services.report_agent import Report, ReportManager


class ReportStore:
    """Adapter around report persistence."""

    def get(self, report_id: str) -> Optional[Report]:
        return ReportManager.get_report(report_id)

    def save(self, report: Report):
        ReportManager.save_report(report)

    def get_by_simulation(self, simulation_id: str) -> Optional[Report]:
        return ReportManager.get_report_by_simulation(simulation_id)

    def package_simulation_deliverables(
        self,
        report_id: str,
        simulation_id: str,
        report_section_titles: list[str] | None = None,
    ) -> dict:
        return ReportManager.package_task_deliverables(
            report_id=report_id,
            simulation_id=simulation_id,
            report_section_titles=report_section_titles,
        )

    def get_deliverables_manifest(self, report_id: str) -> dict:
        return ReportManager.get_deliverables_manifest(report_id)
