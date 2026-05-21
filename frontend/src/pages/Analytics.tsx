import React from "react";
import { useQuery } from "@tanstack/react-query";
import api from "../utils/api";
import { PageHeader } from "../components/ui/PageHeader";
import { StatsCard } from "../components/ui/StatsCard";

interface AnalyticsData {
  user_growth: { month: string; count: number }[];
  request_trend: { month: string; submitted: number; approved: number; rejected: number }[];
  risk_distribution: { level: string; count: number }[];
  top_entitlements: { name: string; user_count: number }[];
  sod_trend: { month: string; violations: number }[];
  compliance_scores: { framework: string; score: number }[];
}

const BAR_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4"];

const MiniBar: React.FC<{ data: { label: string; value: number }[]; maxVal?: number }> = ({ data, maxVal }) => {
  const max = maxVal ?? Math.max(...data.map((d) => d.value), 1);
  return (
    <div className="space-y-2">
      {data.map((d, i) => (
        <div key={d.label} className="flex items-center gap-2">
          <div className="w-24 text-xs text-right text-gray-500 truncate">{d.label}</div>
          <div className="flex-1 bg-gray-100 dark:bg-gray-700 rounded-full h-4 overflow-hidden">
            <div
              className="h-4 rounded-full transition-all duration-500"
              style={{ width: `${(d.value / max) * 100}%`, backgroundColor: BAR_COLORS[i % BAR_COLORS.length] }}
            />
          </div>
          <div className="w-8 text-xs text-gray-600 dark:text-gray-400">{d.value}</div>
        </div>
      ))}
    </div>
  );
};

const Analytics: React.FC = () => {
  const { data, isLoading } = useQuery<{ data: AnalyticsData }>({
    queryKey: ["analytics"],
    queryFn: () => api.get("/api/v1/audit/analytics").then((r) => r.data),
  });

  const analytics = data?.data;

  if (isLoading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-8 bg-gray-200 dark:bg-gray-700 rounded w-48" />
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-24 bg-gray-200 dark:bg-gray-700 rounded-xl" />
          ))}
        </div>
        <div className="grid grid-cols-2 gap-6">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-48 bg-gray-200 dark:bg-gray-700 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Analytics" description="Identity governance insights and trends" />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatsCard label="Total Users" value={analytics?.user_growth?.slice(-1)[0]?.count ?? 0} />
        <StatsCard label="Monthly Requests" value={analytics?.request_trend?.slice(-1)[0]?.submitted ?? 0} />
        <StatsCard label="High Risk Users" value={analytics?.risk_distribution?.find((r) => r.level === "high")?.count ?? 0} />
        <StatsCard label="SoD Violations (Month)" value={analytics?.sod_trend?.slice(-1)[0]?.violations ?? 0} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-5">
          <h3 className="font-semibold mb-4">Risk Distribution</h3>
          <MiniBar
            data={(analytics?.risk_distribution ?? []).map((r) => ({ label: r.level, value: r.count }))}
          />
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-5">
          <h3 className="font-semibold mb-4">Top Requested Entitlements</h3>
          <MiniBar
            data={(analytics?.top_entitlements ?? []).slice(0, 8).map((e) => ({
              label: e.name,
              value: e.user_count,
            }))}
          />
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-5">
          <h3 className="font-semibold mb-4">Request Trend (6 months)</h3>
          <div className="space-y-3">
            {(analytics?.request_trend ?? []).slice(-6).map((m) => (
              <div key={m.month} className="space-y-1">
                <div className="flex justify-between text-xs text-gray-500">
                  <span>{m.month}</span>
                  <span>{m.submitted} submitted</span>
                </div>
                <div className="flex gap-1 h-3">
                  <div
                    className="bg-blue-500 rounded"
                    style={{ width: `${(m.submitted / Math.max(m.submitted, 1)) * 100}%` }}
                    title="Submitted"
                  />
                  <div
                    className="bg-green-500 rounded"
                    style={{ width: `${(m.approved / Math.max(m.submitted, 1)) * 100}%` }}
                    title="Approved"
                  />
                  <div
                    className="bg-red-500 rounded"
                    style={{ width: `${(m.rejected / Math.max(m.submitted, 1)) * 100}%` }}
                    title="Rejected"
                  />
                </div>
              </div>
            ))}
          </div>
          <div className="flex gap-4 mt-3 text-xs text-gray-500">
            <span className="flex items-center gap-1"><span className="w-3 h-3 bg-blue-500 rounded inline-block" /> Submitted</span>
            <span className="flex items-center gap-1"><span className="w-3 h-3 bg-green-500 rounded inline-block" /> Approved</span>
            <span className="flex items-center gap-1"><span className="w-3 h-3 bg-red-500 rounded inline-block" /> Rejected</span>
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-5">
          <h3 className="font-semibold mb-4">Compliance Scores</h3>
          <MiniBar
            maxVal={100}
            data={(analytics?.compliance_scores ?? []).map((c) => ({ label: c.framework, value: c.score }))}
          />
        </div>
      </div>
    </div>
  );
};

export default Analytics;
