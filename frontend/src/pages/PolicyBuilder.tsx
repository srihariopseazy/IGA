import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../utils/api";
import { PageHeader } from "../components/ui/PageHeader";
import { Badge } from "../components/ui/Badge";

interface PolicyRule {
  id: string;
  name: string;
  description: string;
  rule_type: string;
  effect: string;
  is_active: boolean;
  priority: number;
  conditions: Record<string, unknown>;
  created_at: string;
}

const PolicyBuilder: React.FC = () => {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    rule_type: "access_control",
    effect: "deny",
    priority: 100,
    conditions: "{}",
  });
  const [condError, setCondError] = useState("");

  const { data, isLoading } = useQuery<{ data: PolicyRule[] }>({
    queryKey: ["policy-rules"],
    queryFn: () => api.get("/api/v1/compliance/policies").then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: (payload: Omit<typeof form, "conditions"> & { conditions: Record<string, unknown> }) =>
      api.post("/api/v1/compliance/policies", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["policy-rules"] });
      setShowCreate(false);
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      api.patch(`/api/v1/compliance/policies/${id}`, { is_active: active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["policy-rules"] }),
  });

  const handleCreate = () => {
    try {
      const conditions = JSON.parse(form.conditions);
      setCondError("");
      createMutation.mutate({ ...form, conditions });
    } catch {
      setCondError("Invalid JSON in conditions");
    }
  };

  const rules = data?.data ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Policy Builder"
        description="Define and manage access control and compliance policies"
        actions={
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium"
          >
            + New Policy
          </button>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-4">
          <div className="text-2xl font-bold">{rules.length}</div>
          <div className="text-sm text-gray-500 mt-1">Total Policies</div>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-4">
          <div className="text-2xl font-bold text-green-600">{rules.filter((r) => r.is_active).length}</div>
          <div className="text-sm text-gray-500 mt-1">Active</div>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-4">
          <div className="text-2xl font-bold text-red-600">{rules.filter((r) => r.effect === "deny").length}</div>
          <div className="text-sm text-gray-500 mt-1">Deny Rules</div>
        </div>
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-xl shadow divide-y dark:divide-gray-700">
        {isLoading ? (
          <div className="p-8 text-center text-gray-400">Loading policies...</div>
        ) : rules.length === 0 ? (
          <div className="p-8 text-center text-gray-400">No policies defined. Create your first policy above.</div>
        ) : (
          rules
            .sort((a, b) => a.priority - b.priority)
            .map((rule) => (
              <div key={rule.id} className="flex items-start justify-between p-4 hover:bg-gray-50 dark:hover:bg-gray-700/50">
                <div className="flex items-start gap-3">
                  <div className="mt-1">
                    <div className={`w-3 h-3 rounded-full ${rule.is_active ? "bg-green-500" : "bg-gray-300"}`} />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{rule.name}</span>
                      <Badge variant={rule.effect === "allow" ? "success" : "danger"}>{rule.effect}</Badge>
                      <span className="text-xs text-gray-400 capitalize">{rule.rule_type.replace("_", " ")}</span>
                    </div>
                    <div className="text-sm text-gray-500 mt-0.5">{rule.description}</div>
                    <div className="text-xs text-gray-400 mt-1">Priority: {rule.priority}</div>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => toggleMutation.mutate({ id: rule.id, active: !rule.is_active })}
                    className={`px-2 py-1 text-white text-xs rounded ${rule.is_active ? "bg-red-600 hover:bg-red-700" : "bg-green-600 hover:bg-green-700"}`}
                  >
                    {rule.is_active ? "Disable" : "Enable"}
                  </button>
                </div>
              </div>
            ))
        )}
      </div>

      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 w-full max-w-lg space-y-4">
            <h2 className="text-lg font-semibold">Create Policy Rule</h2>
            <div>
              <label className="block text-sm font-medium mb-1">Name</label>
              <input className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Description</label>
              <textarea className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600" rows={2} value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="block text-sm font-medium mb-1">Type</label>
                <select className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600" value={form.rule_type} onChange={(e) => setForm((f) => ({ ...f, rule_type: e.target.value }))}>
                  <option value="access_control">Access Control</option>
                  <option value="sod">SoD Rule</option>
                  <option value="geo_restriction">Geo Restriction</option>
                  <option value="time_based">Time Based</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Effect</label>
                <select className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600" value={form.effect} onChange={(e) => setForm((f) => ({ ...f, effect: e.target.value }))}>
                  <option value="allow">Allow</option>
                  <option value="deny">Deny</option>
                  <option value="mfa_required">MFA Required</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Priority</label>
                <input type="number" className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600" value={form.priority} onChange={(e) => setForm((f) => ({ ...f, priority: Number(e.target.value) }))} />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Conditions (JSON)</label>
              <textarea
                className={`w-full border rounded-lg p-2 text-sm font-mono dark:bg-gray-700 dark:border-gray-600 ${condError ? "border-red-500" : ""}`}
                rows={4}
                value={form.conditions}
                onChange={(e) => setForm((f) => ({ ...f, conditions: e.target.value }))}
              />
              {condError && <p className="text-xs text-red-500 mt-1">{condError}</p>}
            </div>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setShowCreate(false)} className="px-4 py-2 border rounded-lg text-sm">Cancel</button>
              <button onClick={handleCreate} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm">Create Policy</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default PolicyBuilder;
