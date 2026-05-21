import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../utils/api";
import { PageHeader } from "../components/ui/PageHeader";

const Settings: React.FC = () => {
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState("general");

  const { data: settings } = useQuery({
    queryKey: ["tenant-settings"],
    queryFn: () => api.get("/api/v1/tenants/settings").then((r) => r.data),
  });

  const { data: profile } = useQuery({
    queryKey: ["user-profile"],
    queryFn: () => api.get("/api/v1/users/me").then((r) => r.data),
  });

  const updateMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.patch("/api/v1/tenants/settings", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tenant-settings"] }),
  });

  const [passwordForm, setPasswordForm] = useState({ current: "", next: "", confirm: "" });

  const changePasswordMutation = useMutation({
    mutationFn: (payload: { current_password: string; new_password: string }) =>
      api.post("/api/v1/auth/change-password", payload),
  });

  const tabs = ["general", "security", "notifications", "integrations", "branding"];

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" subtitle="Manage tenant and account settings" />

      <div className="flex gap-1 border-b dark:border-gray-700">
        {tabs.map((t) => (
          <button
            key={t}
            onClick={() => setActiveTab(t)}
            className={`px-4 py-2 text-sm font-medium capitalize border-b-2 -mb-px transition-colors ${
              activeTab === t
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {activeTab === "general" && (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-6 space-y-4 max-w-2xl">
          <h3 className="font-semibold">General Settings</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">Organization Name</label>
              <input
                className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                defaultValue={settings?.data?.name ?? ""}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Timezone</label>
              <select className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600">
                <option>UTC</option>
                <option>America/New_York</option>
                <option>Asia/Kolkata</option>
                <option>Europe/London</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Default Language</label>
              <select className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600">
                <option>English</option>
                <option>Spanish</option>
                <option>French</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Session Timeout (minutes)</label>
              <input
                type="number"
                className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                defaultValue={30}
              />
            </div>
          </div>
          <button
            onClick={() => updateMutation.mutate({})}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700"
          >
            Save Changes
          </button>
        </div>
      )}

      {activeTab === "security" && (
        <div className="space-y-4 max-w-2xl">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-6 space-y-4">
            <h3 className="font-semibold">Change Password</h3>
            <div>
              <label className="block text-sm font-medium mb-1">Current Password</label>
              <input
                type="password"
                className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                value={passwordForm.current}
                onChange={(e) => setPasswordForm((f) => ({ ...f, current: e.target.value }))}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">New Password</label>
              <input
                type="password"
                className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                value={passwordForm.next}
                onChange={(e) => setPasswordForm((f) => ({ ...f, next: e.target.value }))}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Confirm New Password</label>
              <input
                type="password"
                className="w-full border rounded-lg p-2 text-sm dark:bg-gray-700 dark:border-gray-600"
                value={passwordForm.confirm}
                onChange={(e) => setPasswordForm((f) => ({ ...f, confirm: e.target.value }))}
              />
            </div>
            <button
              onClick={() =>
                changePasswordMutation.mutate({
                  current_password: passwordForm.current,
                  new_password: passwordForm.next,
                })
              }
              disabled={!passwordForm.current || passwordForm.next !== passwordForm.confirm}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
            >
              Update Password
            </button>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-6 space-y-3">
            <h3 className="font-semibold">MFA Settings</h3>
            <p className="text-sm text-gray-500">Multi-factor authentication adds an extra layer of security to your account.</p>
            <button className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm hover:bg-green-700">
              Enable MFA
            </button>
          </div>
        </div>
      )}

      {activeTab === "notifications" && (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-6 space-y-4 max-w-2xl">
          <h3 className="font-semibold">Notification Preferences</h3>
          {[
            { key: "access_request", label: "Access Request Updates" },
            { key: "approval_required", label: "Approval Required" },
            { key: "certification_reminder", label: "Certification Reminders" },
            { key: "risk_alert", label: "Risk Alerts" },
            { key: "sod_violation", label: "SoD Violations" },
            { key: "security_alert", label: "Security Alerts" },
          ].map((n) => (
            <div key={n.key} className="flex items-center justify-between py-2 border-b dark:border-gray-700">
              <span className="text-sm">{n.label}</span>
              <div className="flex gap-4">
                {["email", "in_app"].map((ch) => (
                  <label key={ch} className="flex items-center gap-1.5 text-sm cursor-pointer">
                    <input type="checkbox" defaultChecked />
                    <span className="capitalize">{ch.replace("_", "-")}</span>
                  </label>
                ))}
              </div>
            </div>
          ))}
          <button className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">
            Save Preferences
          </button>
        </div>
      )}

      {(activeTab === "integrations" || activeTab === "branding") && (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-8 text-center text-gray-500">
          <p className="text-sm">{activeTab.charAt(0).toUpperCase() + activeTab.slice(1)} settings are managed in the dedicated sections.</p>
        </div>
      )}
    </div>
  );
};

export default Settings;
