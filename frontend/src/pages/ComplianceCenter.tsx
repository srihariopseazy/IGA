import React from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import api from "../utils/api";
import { PageHeader } from "../components/ui/PageHeader";
import { StatsCard } from "../components/ui/StatsCard";
import { Badge } from "../components/ui/Badge";

interface ComplianceReport {
  id: string;
  report_type: string;
  framework: string;
  status: string;
  score: number;
  generated_at: string;
  findings_count: number;
  critical_count: number;
}

const FRAMEWORKS = ["SOX", "GDPR", "HIPAA", "ISO27001", "NIST", "PCI-DSS"];

const ComplianceCenter: React.FC = () => {
  const { data, isLoading } = useQuery<{ data: ComplianceReport[] }>({
    queryKey: ["compliance-reports"],
    queryFn: () => api.get("/api/v1/compliance/reports").then((r) => r.data),
  });

  const generateMutation = useMutation({
    mutationFn: (framework: string) =>
      api.post("/api/v1/compliance/reports/generate", { framework }),
  });

  const reports = data?.data ?? [];

  const scoreColor = (score: number) =>
    score >= 80 ? "text-green-600" : score >= 60 ? "text-yellow-600" : "text-red-600";

  const statusVariant: Record<string, "default" | "success" | "warning" | "danger" | "info"> = {
    generating: "info",
    ready: "success",
    failed: "danger",
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Compliance Center"
        description="Regulatory compliance monitoring and reporting"
      />

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatsCard label="Frameworks" value={FRAMEWORKS.length} />
        <StatsCard
          label="Avg Score"
          value={
            reports.length
              ? Math.round(reports.reduce((s, r) => s + r.score, 0) / reports.length) + "%"
              : "N/A"
          }
         
        />
        <StatsCard label="Critical Findings" value={reports.reduce((s, r) => s + r.critical_count, 0)} />
        <StatsCard label="Reports Generated" value={reports.length} />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {FRAMEWORKS.map((fw) => (
          <div key={fw} className="bg-white dark:bg-gray-800 rounded-xl shadow p-4 text-center">
            <div className="text-lg font-bold text-gray-800 dark:text-gray-100">{fw}</div>
            <div className="mt-3">
              <button
                onClick={() => generateMutation.mutate(fw)}
                disabled={generateMutation.isPending}
                className="w-full px-2 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 disabled:opacity-50"
              >
                Generate Report
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-xl shadow">
        <div className="p-4 border-b dark:border-gray-700">
          <h2 className="font-semibold">Recent Reports</h2>
        </div>
        {isLoading ? (
          <div className="p-8 text-center text-gray-400">Loading...</div>
        ) : reports.length === 0 ? (
          <div className="p-8 text-center text-gray-400">No reports generated yet. Select a framework above to generate your first report.</div>
        ) : (
          <div className="divide-y dark:divide-gray-700">
            {reports.map((r) => (
              <div key={r.id} className="flex items-center justify-between p-4 hover:bg-gray-50 dark:hover:bg-gray-700/50">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-full bg-gray-100 dark:bg-gray-700 flex items-center justify-center">
                    <span className={`text-lg font-bold ${scoreColor(r.score)}`}>{r.score}%</span>
                  </div>
                  <div>
                    <div className="font-medium">{r.framework} — {r.report_type}</div>
                    <div className="text-xs text-gray-500">
                      {r.findings_count} findings · {r.critical_count} critical · Generated {new Date(r.generated_at).toLocaleDateString()}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Badge variant={statusVariant[r.status] ?? "default"}>{r.status}</Badge>
                  {r.status === "ready" && (
                    <button
                      onClick={() => api.get(`/api/v1/compliance/reports/${r.id}/download`, { responseType: "blob" }).then((res) => {
                        const url = window.URL.createObjectURL(res.data);
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = `${r.framework}-report.pdf`;
                        a.click();
                      })}
                      className="text-blue-600 hover:underline text-sm"
                    >
                      Download PDF
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default ComplianceCenter;
