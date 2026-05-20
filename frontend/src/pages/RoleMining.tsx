import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../utils/api";
import PageHeader from "../components/ui/PageHeader";
import Badge from "../components/ui/Badge";

interface RoleCandidate {
  id: string;
  name: string;
  description: string;
  user_count: number;
  entitlement_count: number;
  confidence_score: number;
  department: string;
  entitlements: string[];
  status: "candidate" | "approved" | "rejected";
}

const RoleMining: React.FC = () => {
  const qc = useQueryClient();
  const [isRunning, setIsRunning] = useState(false);

  const { data, isLoading } = useQuery<{ data: RoleCandidate[] }>({
    queryKey: ["role-candidates"],
    queryFn: () => api.get("/api/v1/roles/mining/candidates").then((r) => r.data),
  });

  const runMiningMutation = useMutation({
    mutationFn: () => api.post("/api/v1/roles/mining/run"),
    onMutate: () => setIsRunning(true),
    onSettled: () => setIsRunning(false),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["role-candidates"] }),
  });

  const actionMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "approve" | "reject" }) =>
      api.post(`/api/v1/roles/mining/candidates/${id}/${action}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["role-candidates"] }),
  });

  const candidates = data?.data ?? [];

  const confidenceColor = (score: number) =>
    score >= 0.8 ? "text-green-600" : score >= 0.6 ? "text-yellow-600" : "text-red-600";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Role Mining"
        subtitle="AI-powered role discovery and optimization"
        actions={
          <button
            onClick={() => runMiningMutation.mutate()}
            disabled={isRunning}
            className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 text-sm font-medium disabled:opacity-50 flex items-center gap-2"
          >
            {isRunning ? (
              <>
                <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                </svg>
                Mining...
              </>
            ) : (
              "⚡ Run Role Mining"
            )}
          </button>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {[
          { label: "Candidates", value: candidates.length },
          { label: "High Confidence (>80%)", value: candidates.filter((c) => c.confidence_score >= 0.8).length },
          { label: "Pending Review", value: candidates.filter((c) => c.status === "candidate").length },
          { label: "Approved", value: candidates.filter((c) => c.status === "approved").length },
        ].map((s) => (
          <div key={s.label} className="bg-white dark:bg-gray-800 rounded-xl shadow p-4">
            <div className="text-2xl font-bold">{s.value}</div>
            <div className="text-sm text-gray-500 mt-1">{s.label}</div>
          </div>
        ))}
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 animate-pulse">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-48 bg-gray-200 dark:bg-gray-700 rounded-xl" />
          ))}
        </div>
      ) : candidates.length === 0 ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-12 text-center">
          <div className="text-4xl mb-3">🔍</div>
          <h3 className="font-semibold text-gray-700 dark:text-gray-300">No role candidates yet</h3>
          <p className="text-sm text-gray-500 mt-2">Run role mining to analyze user access patterns and discover candidate roles.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {candidates.map((candidate) => (
            <div key={candidate.id} className="bg-white dark:bg-gray-800 rounded-xl shadow p-5 space-y-3">
              <div className="flex justify-between items-start">
                <div>
                  <div className="font-semibold">{candidate.name}</div>
                  <div className="text-xs text-gray-500 mt-0.5">{candidate.department}</div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-sm font-bold ${confidenceColor(candidate.confidence_score)}`}>
                    {Math.round(candidate.confidence_score * 100)}%
                  </span>
                  <Badge
                    variant={
                      candidate.status === "approved"
                        ? "success"
                        : candidate.status === "rejected"
                        ? "danger"
                        : "default"
                    }
                  >
                    {candidate.status}
                  </Badge>
                </div>
              </div>
              <div className="text-sm text-gray-600 dark:text-gray-400">{candidate.description}</div>
              <div className="flex gap-4 text-xs text-gray-500">
                <span>👥 {candidate.user_count} users</span>
                <span>🔑 {candidate.entitlement_count} entitlements</span>
              </div>
              <div className="flex flex-wrap gap-1">
                {(candidate.entitlements ?? []).slice(0, 5).map((e) => (
                  <span key={e} className="px-1.5 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded text-xs">{e}</span>
                ))}
                {(candidate.entitlements ?? []).length > 5 && (
                  <span className="px-1.5 py-0.5 bg-gray-100 dark:bg-gray-700 rounded text-xs">+{candidate.entitlements.length - 5} more</span>
                )}
              </div>
              {candidate.status === "candidate" && (
                <div className="flex gap-2">
                  <button
                    onClick={() => actionMutation.mutate({ id: candidate.id, action: "approve" })}
                    className="flex-1 px-3 py-1.5 bg-green-600 text-white text-xs rounded hover:bg-green-700"
                  >
                    Approve as Role
                  </button>
                  <button
                    onClick={() => actionMutation.mutate({ id: candidate.id, action: "reject" })}
                    className="flex-1 px-3 py-1.5 border text-xs rounded hover:bg-gray-50 dark:hover:bg-gray-700"
                  >
                    Reject
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default RoleMining;
