import React, { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { AuthAlert, AuthCard, PasswordField } from "../components/AuthCard";
import { localPasswordProblem, primaryButton } from "../components/authForm";
import { useAuth } from "../contexts/AuthContext";
import { changePassword, errorMessage } from "../services/passwordService";

// Trocar a senha logado. Obrigatória quando a senha foi definida por um
// administrador (must_change_password): o backend bloqueia o resto até a troca.
export const ChangePasswordPage: React.FC = () => {
  const navigate = useNavigate();
  const { user, loading, replaceSessionToken, signOut } = useAuth();
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  if (loading) return null;
  if (!user) return <Navigate to="/login?next=/trocar-senha" replace />;

  const forced = !!user.must_change_password;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!current) {
      setError("Informe a senha atual.");
      return;
    }
    const problem = localPasswordProblem(password, confirm);
    if (problem) {
      setError(problem);
      return;
    }
    setSaving(true);
    try {
      const { access_token } = await changePassword(current, password);
      await replaceSessionToken(access_token);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(errorMessage(err, "Não foi possível trocar a senha. Tente de novo."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <AuthCard
      title={forced ? "Crie a sua senha" : "Trocar senha"}
      subtitle={
        forced
          ? "Você entrou com uma senha provisória, definida por outra pessoa. Para continuar, troque por uma senha só sua."
          : "As sessões abertas em outros aparelhos serão encerradas."
      }
    >
      {error && <AuthAlert kind="error">{error}</AuthAlert>}
      <form onSubmit={handleSubmit} className="flex flex-col gap-5">
        <input type="email" value={user.email} autoComplete="username" readOnly hidden />
        <PasswordField
          id="current-password"
          label={forced ? "Senha provisória" : "Senha atual"}
          value={current}
          onChange={setCurrent}
          autoComplete="current-password"
          show={show}
        />
        <PasswordField id="new-password" label="Senha nova" value={password} onChange={setPassword} autoComplete="new-password" show={show} />
        <PasswordField id="confirm-password" label="Repita a senha nova" value={confirm} onChange={setConfirm} autoComplete="new-password" show={show} />
        <label className="flex items-center gap-2 text-sm text-zinc-400 select-none cursor-pointer">
          <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} />
          Mostrar senhas
        </label>
        <button type="submit" disabled={saving} className={primaryButton}>
          {saving ? "Salvando..." : "Salvar senha nova"}
        </button>
        <button
          type="button"
          onClick={() => (forced ? signOut() : navigate(-1))}
          className="text-sm text-zinc-400 hover:text-white transition-colors select-none"
        >
          {forced ? "Sair" : "Voltar"}
        </button>
      </form>
    </AuthCard>
  );
};
