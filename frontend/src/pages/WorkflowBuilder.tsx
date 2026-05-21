import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../utils/api";
import { PageHeader } from "../components/ui/PageHeader";
import { Badge } from "../components/ui/Badge";

interface Workflow {
  id: string;
  name: string;
  description: string;
  workflow_type: string;
  is_active: boolean;
  step_count: number;
  created_at: string;
}

interface WorkflowStep {
  step_order: number;
  name: string;
  step_type: string;
  approver_type: string;
  approver_value: string;
  sla_hours: number;
  is_required: boolean;
}

const WorkflowBuilder: React.FC = () => {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [wfType, setWfType] = useState("access_request");
  const [steps, setSteps] = useState<WorkflowStep[]>([
    { step_order: 1, name: "Manager Approval", step_type: "approval", approver_type: "manager", approver_value: "", sla_hours: 48, is_required: true },
  ]);

  const { data, isLoading } = useQuery<{ data: Workflow[] }>({
    queryKey: ["workflows"],
    queryFn: () => api.get("/api/v1/workflows").then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: (payload: { name: string; workflow_type: string; steps: WorkflowStep[] }) =>
      api.post("/api/v1/workflows", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workflows"] });
      setShowCreate(false);
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      api.patch(`/api/v1/workflows/${id}`, { is_active: active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows"] }),
  });

  const addStep = () =>
    setSteps((prev) => [
      ...prev,
      {
        step_order: prev.length + 1,
        name: "",
        step_type: "approval",
        approver_type: "role",
        approver_value: "",
        sla_hours: 24,
        is_required: true,
      },
    ]);

  const removeStep = (i: number) =>
    setSteps((prev) => prev.filter((_, idx) => idx !== i).map((s, idx) => ({ ...s, step_order: idx + 1 })));

  const updateStep = (i: number, key: keyof WorkflowStep, value: string | number | boolean) =>
    setSteps((prev) => prev.map((s, idx) => (idx === i ? { ...s, [key]: value } : s)));

  const workflows = data?.data ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Workflow Builder"
        subtitle="Design and manage approval workflows"
        actions={
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium"
          >
            + New Workflow
          </button>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {isLoading
          ? Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-40 bg-gray-200 dark:bg-gray-700 rounded-xl animate-pulse" />
            ))
          : workflows.map((wf) => (
              <div key={wf.id} className="bg-white dark:bg-gray-800 rounded-xl shadow p-5 space-y-3">
                <div className="flex justify-between items-start">
                  <div>
                    <div className="font-semibold">{wf.name}</div>
                    <div className="text-xs text-gray-500 capitalize mt-0.5">{wf.workflow_type.replace("_", " ")}</div>
                  </div>
                  <Badge variant={wf.is_active ? "success" : "default"}>{wf.is_active ? "Active" : "Inactive"}</Badge>
                </div>
                <div className="text-sm text-gray-600 dark:text-gray-400">{wf.description || "No description"}</div>
                <div className="text-xs text-gray-500">{wf.step_count} steps</div>
                <div className="flex gap-2">
                  <button
                    onClick={() => setSelectedId(wf.id)}
                    className="flex-1 px-2 py-1.5 border rounded text-xs"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => toggleMutation.mutate({ id: wf.id, active: !wf.is_active })}
                    className={`flex-1 px-2 py-1.5 rounded text-xs text-white ${wf.is_active ? "bg-red-600 hover:bg-red-700" : "bg-green-600 hover:bg-green-700"}`}
                  >
                    {wf.is_active ? "Deactivate" : "Activate"}
                  </button>
                </div>
              </div>
            ))}
      </div>

      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 w-full max-w-2xl space-y-4 max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-semibold">Create Workflow</h2>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium mb-1">Name</label>
                <input
                  className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Type</label>
                <select
                  className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                  value={wfType}
                  onChange={(e) => setWfType(e.target.value)}
                >
                  <option value="access_request">Access Request</option>
                  <option value="role_assignment">Role Assignment</option>
                  <option value="provisioning">Provisioning</option>
                  <option value="offboarding">Offboarding</option>
                </select>
              </div>
            </div>

            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <h3 className="font-medium text-sm">Steps</h3>
                <button onClick={addStep} className="text-blue-600 hover:underline text-xs">+ Add Step</button>
              </div>
              {steps.map((step, i) => (
                <div key={i} className="border dark:border-gray-600 rounded-lg p-3 space-y-2">
                  <div className="flex justify-between items-center">
                    <span className="text-xs font-medium text-gray-500">Step {i + 1}</span>
                    {steps.length > 1 && (
                      <button onClick={() => removeStep(i)} className="text-red-500 text-xs hover:underline">Remove</button>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <input
                      className="border rounded p-1.5 text-xs dark:bg-gray-700 dark:border-gray-600"
                      placeholder="Step name"
                      value={step.name}
                      onChange={(e) => updateStep(i, "name", e.target.value)}
                    />
                    <select
                      className="border rounded p-1.5 text-xs dark:bg-gray-700 dark:border-gray-600"
                      value={step.approver_type}
                      onChange={(e) => updateStep(i, "approver_type", e.target.value)}
                    >
                      <option value="manager">Manager</option>
                      <option value="role">Role</option>
                      <option value="user">Specific User</option>
                      <option value="auto">Auto-Approve</option>
                    </select>
                    <input
                      type="number"
                      className="border rounded p-1.5 text-xs dark:bg-gray-700 dark:border-gray-600"
                      placeholder="SLA hours"
                      value={step.sla_hours}
                      onChange={(e) => updateStep(i, "sla_hours", Number(e.target.value))}
                    />
                    <label className="flex items-center gap-1.5 text-xs">
                      <input
                        type="checkbox"
                        checked={step.is_required}
                        onChange={(e) => updateStep(i, "is_required", e.target.checked)}
                      />
                      Required
                    </label>
                  </div>
                </div>
              ))}
            </div>

            <div className="flex gap-3 justify-end">
              <button onClick={() => setShowCreate(false)} className="px-4 py-2 border rounded-lg text-sm">Cancel</button>
              <button
                onClick={() => createMutation.mutate({ name, workflow_type: wfType, steps })}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm"
              >
                Create Workflow
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default WorkflowBuilder;
