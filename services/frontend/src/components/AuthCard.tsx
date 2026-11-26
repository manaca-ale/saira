import React from "react";
import { AlertCircle, CheckCircle2 } from "lucide-react";

// Moldura escura das telas de senha (definir pelo link e trocar), no estilo do login.
export const AuthCard: React.FC<{ title: React.ReactNode; subtitle?: React.ReactNode; children?: React.ReactNode }> = ({
  title,
  subtitle,
  children,
}) => (
  <div className="h-full w-full flex items-center justify-center p-4 relative overflow-hidden">
    <div className="absolute inset-0 bg-[#1e1e1d]"></div>
    <div className="absolute inset-0 bg-[linear-gradient(120deg,rgba(255,255,255,0.04)_0%,rgba(255,255,255,0.015)_28%,transparent_56%)]"></div>
    <div className="relative z-10 w-full max-w-md bg-[#1a1a1a] border border-zinc-800 rounded-3xl shadow-2xl p-8">
      <div className="mb-6 select-none">
        <p className="text-sm font-semibold text-[#d9f99d] mb-3">SAÍRA</p>
        <h1 className="text-2xl font-bold text-white mb-2">{title}</h1>
        {subtitle && <p className="text-zinc-400 text-sm">{subtitle}</p>}
      </div>
      {children}
    </div>
  </div>
);

export const AuthAlert: React.FC<{ kind: "error" | "success"; children: React.ReactNode }> = ({ kind, children }) =>
  kind === "error" ? (
    <div className="flex items-start gap-2 p-3 mb-4 bg-red-500/10 border border-red-500/50 rounded-lg">
      <AlertCircle size={18} className="text-red-500 shrink-0 mt-0.5" />
      <span className="text-sm text-red-300">{children}</span>
    </div>
  ) : (
    <div className="flex items-start gap-2 p-3 mb-4 bg-green-500/10 border border-green-500/50 rounded-lg">
      <CheckCircle2 size={18} className="text-green-400 shrink-0 mt-0.5" />
      <span className="text-sm text-green-200">{children}</span>
    </div>
  );

export const PasswordField: React.FC<{
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: string;
  show: boolean;
}> = ({ id, label, value, onChange, autoComplete, show }) => (
  <div className="flex flex-col gap-2">
    <label htmlFor={id} className="text-sm font-semibold text-[#d9f99d] select-none">
      {label}
    </label>
    <input
      id={id}
      type={show ? "text" : "password"}
      value={value}
      autoComplete={autoComplete}
      onChange={(e) => onChange(e.target.value)}
      className="w-full bg-transparent border border-zinc-600 focus:border-[#ccff33] rounded-xl py-3 px-4 text-white outline-none transition-colors"
    />
  </div>
);
