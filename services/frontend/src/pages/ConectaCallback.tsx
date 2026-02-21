import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

export const ConectaCallback: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { completeConectaLogin } = useAuth();
  const [message, setMessage] = useState("Finalizando autenticação...");

  useEffect(() => {
    async function finishLogin() {
      const error = searchParams.get("error");
      const backendMessage = searchParams.get("message");
      const ticket = searchParams.get("ticket");
      const nextPath = searchParams.get("next") || "/dashboard";

      if (error) {
        navigate(`/?error=${encodeURIComponent(backendMessage || "Falha no login com Conecta")}`, {
          replace: true,
        });
        return;
      }

      if (!ticket) {
        navigate("/?error=Ticket de autenticação ausente", { replace: true });
        return;
      }

      try {
        await completeConectaLogin(ticket);
        navigate(nextPath, { replace: true });
      } catch (err: any) {
        setMessage("Falha ao concluir login. Redirecionando...");
        const detail = err?.response?.data?.detail || err?.message || "Erro de autenticação";
        navigate(`/?error=${encodeURIComponent(detail)}`, { replace: true });
      }
    }

    finishLogin();
  }, [completeConectaLogin, navigate, searchParams]);

  return (
    <div className="h-full w-full bg-[#121212] flex items-center justify-center p-6">
      <div className="bg-[#1a1a1a] border border-zinc-800 rounded-2xl px-6 py-5 text-zinc-200">
        {message}
      </div>
    </div>
  );
};
