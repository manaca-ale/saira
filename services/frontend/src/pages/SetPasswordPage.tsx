import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AuthAlert, AuthCard, PasswordField } from "../components/AuthCard";
import { localPasswordProblem, primaryButton } from "../components/authForm";
import {
  errorDetail,
  errorMessage,
  getPasswordTokenInfo,
  setPasswordWithToken,
  type PasswordTokenInfo,
} from "../services/passwordService";

// Lê o token do fragmento (#token=...): o navegador não manda o fragmento ao
// servidor, então o token não fica em log de acesso.
function readToken(): string {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  return params.get("token") || "";
}

// Página do link do convite e do "esqueci minha senha" (/definir-senha#token=...).
export const SetPasswordPage: React.FC = () => {
  const navigate = useNavigate();
  const [token] = useState(readToken);
  const [info, setInfo] = useState<PasswordTokenInfo | null>(null);
  const [checking, setChecking] = useState(!!token);
  const [linkError, setLinkError] = useState(
    token ? "" : "Link incompleto. Abra o link do e-mail de novo ou copie o endereço inteiro.",
  );
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [doneEmail, setDoneEmail] = useState<string | null>(null);

  useEffect(() => {
    // Tira o token da barra de endereço (e do histórico) assim que ele é lido.
    if (window.location.hash) {
      window.history.replaceState(null, "", window.location.pathname);
    }
    if (!token) return;
    getPasswordTokenInfo(token)
      .then(setInfo)
      .catch((e) => setLinkError(errorMessage(e, "Não foi possível conferir o link. Tente de novo.")))
      .finally(() => setChecking(false));
  }, [token]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    const problem = localPasswordProblem(password, confirm);
    if (problem) {
      setError(problem);
      return;
    }
    setSaving(true);
    try {
      const result = await setPasswordWithToken(token, password);
      setDoneEmail(result.email || info?.email || "");
    } catch (err) {
      const message = errorMessage(err, "Não foi possível salvar a senha. Tente de novo.");
      const detail = errorDetail(err);
      if (typeof detail === "string" && detail.startsWith("token_")) setLinkError(message);
      else setError(message);
    } finally {
      setSaving(false);
    }
  };

  const goToLogin = () => navigate(doneEmail ? `/login?email=${encodeURIComponent(doneEmail)}` : "/login");

  if (checking) {
    return <AuthCard title="Conferindo o link..." />;
  }

  if (doneEmail !== null) {
    return (
      <AuthCard title="Senha criada">
        <AuthAlert kind="success">Pronto! Agora entre com o seu e-mail e a senha que você acabou de criar.</AuthAlert>
        <button type="button" onClick={goToLogin} className={primaryButton}>
          Ir para o login
        </button>
      </AuthCard>
    );
  }

  if (linkError || !info) {
    return (
      <AuthCard title="Link indisponível">
        <AuthAlert kind="error">{linkError || "Link inválido."}</AuthAlert>
        <button type="button" onClick={() => navigate("/login")} className={primaryButton}>
          Ir para o login
        </button>
      </AuthCard>
    );
  }

  const firstName = info.name.split(" ")[0];
  return (
    <AuthCard
      title={info.purpose === "invite" ? `Boas-vindas, ${firstName}` : `Nova senha, ${firstName}`}
      subtitle={
        <>
          {info.purpose === "invite" ? "Crie a senha da sua conta " : "Crie uma senha nova para "}
          <span className="text-zinc-200">{info.email}</span>. Use pelo menos 8 caracteres; uma frase curta é
          mais fácil de lembrar e mais difícil de adivinhar.
        </>
      }
    >
      {error && <AuthAlert kind="error">{error}</AuthAlert>}
      <form onSubmit={handleSubmit} className="flex flex-col gap-5">
        {/* Campo de usuário oculto: ajuda o gerenciador de senhas a guardar o par certo. */}
        <input type="email" value={info.email} autoComplete="username" readOnly hidden />
        <PasswordField id="new-password" label="Senha nova" value={password} onChange={setPassword} autoComplete="new-password" show={show} />
        <PasswordField id="confirm-password" label="Repita a senha" value={confirm} onChange={setConfirm} autoComplete="new-password" show={show} />
        <label className="flex items-center gap-2 text-sm text-zinc-400 select-none cursor-pointer">
          <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} />
          Mostrar senha
        </label>
        <button type="submit" disabled={saving} className={primaryButton}>
          {saving ? "Salvando..." : "Criar senha"}
        </button>
      </form>
    </AuthCard>
  );
};
