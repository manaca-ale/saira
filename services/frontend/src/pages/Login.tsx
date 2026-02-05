import React, { useState } from "react";
import {
  User,
  Check,
  AlertCircle,
  Eye,
  EyeOff,
  Lock,
  Mail,
  X,
  Info,
} from "lucide-react";
import { InputField } from "../components/InputField";
import { useNavigate } from "react-router-dom";
import { Tooltip } from "../components/Tooltip";
import { useAuth } from "../contexts/AuthContext";

export const Login: React.FC = () => {
  const navigate = useNavigate();
  const { signIn } = useAuth();

  // --- Login Form State ---
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  // --- Forgot Password Modal State ---
  const [showForgotModal, setShowForgotModal] = useState(false);
  const [isForgotClosing, setIsForgotClosing] = useState(false);
  const [recoveryEmail, setRecoveryEmail] = useState("");
  const [forgotError, setForgotError] = useState("");

  // --- Register Modal State ---
  const [showRegisterModal, setShowRegisterModal] = useState(false);
  const [isRegisterClosing, setIsRegisterClosing] = useState(false);
  const [registerEmail, setRegisterEmail] = useState("");
  const [registerError, setRegisterError] = useState("");

  // --- Toast State (NEW) ---
  const [showToast, setShowToast] = useState(false);
  const [toastMessage, setToastMessage] = useState("");

  // --- Event Handlers ---
  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!email || !password) {
      setError("Por favor, preencha todos os campos");
      return;
    }

    setLoading(true);

    try {
      await signIn({ email, password });
      navigate("/dashboard");
    } catch (err) {
      setError("Email ou senha incorretos.");
    } finally {
      setLoading(false);
    }
  };

  // --- Helper to Trigger Toast ---
  const triggerToast = (message: string) => {
    setToastMessage(message);
    setShowToast(true);
    setTimeout(() => setShowToast(false), 4000); // Hide after 4 seconds
  };

  // --- Forgot Password Logic ---
  const closeForgotModal = () => {
    setIsForgotClosing(true);
    setTimeout(() => {
      setShowForgotModal(false);
      setIsForgotClosing(false);
      setForgotError("");
    }, 500);
  };

  const handleSendRecovery = (e: React.FormEvent) => {
    e.preventDefault();
    setForgotError("");

    if (!recoveryEmail) {
      setForgotError("Por favor, informe seu email.");
      return;
    }

    const subject = encodeURIComponent("Recuperação de Senha");
    const body = encodeURIComponent(
      `Solicito a recuperação de senha para o usuário: ${recoveryEmail}`,
    );

    window.location.href = `mailto:suporte@saira.com?subject=${subject}&body=${body}`;

    closeForgotModal();
    setRecoveryEmail("");

    // NEW: Show success feedback
    triggerToast("Email de recuperação enviado com sucesso!");
  };

  // --- Register Logic ---
  const closeRegisterModal = () => {
    setIsRegisterClosing(true);
    setTimeout(() => {
      setShowRegisterModal(false);
      setIsRegisterClosing(false);
      setRegisterError("");
    }, 500);
  };

  const handleSendRegistration = (e: React.FormEvent) => {
    e.preventDefault();
    setRegisterError("");

    if (!registerEmail) {
      setRegisterError("Por favor, informe seu email para contato.");
      return;
    }

    const subject = encodeURIComponent("Solicitação de Cadastro");
    const body = encodeURIComponent(
      `Gostaria de solicitar um cadastro para o email: ${registerEmail}`,
    );

    window.location.href = `mailto:suporte@saira.com?subject=${subject}&body=${body}`;

    closeRegisterModal();
    setRegisterEmail("");

    // NEW: Show success feedback
    triggerToast("Solicitação de cadastro enviada com sucesso!");
  };

  return (
    <div className="h-full w-full bg-[#121212] flex items-center justify-center p-4 lg:p-12 relative">
      <style>{`
        @keyframes modalPop {
          0% {
            opacity: 0;
            transform: scale(0.8) translateY(50px);
          }
          100% {
            opacity: 1;
            transform: scale(1) translateY(0);
          }
        }
        @keyframes modalPopExit {
          0% {
            opacity: 1;
            transform: scale(1) translateY(0);
          }
          100% {
            opacity: 0;
            transform: scale(0.8) translateY(50px);
          }
        }
      `}</style>

      {/* --- SUCCESS TOAST NOTIFICATION (NEW) --- */}
      {showToast && (
        <div className="absolute top-8 right-8 z-[70] animate-in slide-in-from-top-5 duration-300">
          <div className="bg-[#dcfce7] border border-green-200 text-[#166534] px-4 py-3 rounded-xl shadow-lg flex items-center gap-3">
            <div className="bg-green-500 rounded-full p-1 text-white">
              <Info size={12} strokeWidth={4} />
            </div>
            <span className="font-semibold text-sm select-none">
              {toastMessage}
            </span>
            <button
              onClick={() => setShowToast(false)}
              className="ml-4 hover:text-green-800 transition-colors"
            >
              <X size={16} />
            </button>
          </div>
        </div>
      )}

      {/* --- Card Container --- */}
      <div className="w-full max-w-[1400px] h-[85vh] flex flex-row bg-[#121212]">
        {/* --- Left Panel --- */}
        <div className="w-24 md:w-[40%] lg:w-1/2 h-full relative rounded-tl-none rounded-tr-[3.5rem] rounded-bl-[3.5rem] rounded-br-none overflow-hidden shrink-0 transition-all duration-300">
          <div className="absolute inset-0 bg-[#eaffb0]"></div>
          <div className="absolute top-[-20%] left-[-20%] w-[80%] h-[80%] bg-[#f7fee7] rounded-full blur-[100px] opacity-80"></div>
          <div className="absolute top-[30%] right-[-10%] w-[70%] h-[70%] bg-[#bef264] rounded-full blur-[80px] mix-blend-multiply opacity-60"></div>
          <div className="absolute bottom-[-10%] left-[10%] w-[60%] h-[60%] bg-[#d9f99d] rounded-full blur-[60px]"></div>
          <div className="absolute inset-0 bg-white/10 backdrop-blur-3xl"></div>
        </div>

        {/* --- Right Panel --- */}
        <div className="flex-1 h-full flex flex-col justify-center px-6 md:px-12 lg:px-24 py-12 bg-transparent rounded-r-[3.5rem] overflow-hidden">
          <div className="mb-10 lg:mb-14">
            <h1 className="text-3xl md:text-4xl lg:text-5xl font-semibold text-white tracking-tight select-none">
              Bem vindo ao <span className="text-[#d9f99d]">SAIRA</span>
            </h1>
          </div>

          <form
            onSubmit={handleLogin}
            className="flex flex-col gap-6 lg:gap-7 max-w-md w-full"
          >
            {error && (
              <div className="flex items-center gap-2 p-4 bg-red-500/10 border border-red-500/50 rounded-lg animate-in fade-in slide-in-from-top-2">
                <AlertCircle size={20} className="text-red-500 shrink-0" />
                <span className="text-sm text-red-400 font-medium select-none">
                  {error}
                </span>
              </div>
            )}

            <Tooltip text="Digite seu email" className="w-full" spacing="-mb-5">
              <div className="w-full">
                <InputField
                  id="email"
                  label="Email"
                  type="email"
                  placeholder="seu@email.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  icon={User}
                />
              </div>
            </Tooltip>

            <div className="space-y-1">
              <div className="relative w-full">
                <Tooltip
                  text="Digite sua senha"
                  className="w-full"
                  spacing="-mb-5"
                >
                  <InputField
                    id="password"
                    label="Senha"
                    type={showPassword ? "text" : "password"}
                    placeholder="........."
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    icon={Lock}
                  />
                </Tooltip>

                <div className="absolute right-12 top-[52px] z-10">
                  <Tooltip
                    text={showPassword ? "Ocultar senha" : "Mostrar senha"}
                    className="w-fit"
                    spacing="mb-2"
                  >
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="text-zinc-500 hover:text-[#d9f99d] transition-colors focus:outline-none"
                    >
                      {showPassword ? <Eye size={20} /> : <EyeOff size={20} />}
                    </button>
                  </Tooltip>
                </div>
              </div>

              {/* Forgot Password Link */}
              <div className="flex justify-end pt-2">
                <Tooltip text="Recuperar acesso via e-mail" className="w-fit">
                  <button
                    type="button"
                    onClick={() => {
                      setRecoveryEmail(email);
                      setShowForgotModal(true);
                    }}
                    className="text-sm text-zinc-400 hover:text-[#d9f99d] transition-colors hover:underline outline-none select-none"
                  >
                    Esqueceu a senha?
                  </button>
                </Tooltip>
              </div>
            </div>

            <div className="flex items-center mt-1">
              <Tooltip text="Salvar sessão neste dispositivo" className="w-fit">
                <label className="flex items-center cursor-pointer group select-none gap-3">
                  <div className="relative flex items-center justify-center">
                    <input
                      type="checkbox"
                      className="peer sr-only"
                      defaultChecked
                    />
                    <div className="w-5 h-5 rounded-full border border-zinc-500 peer-checked:bg-[#10b981] peer-checked:border-[#10b981] transition-all"></div>
                    <Check
                      size={12}
                      className="absolute text-black opacity-0 peer-checked:opacity-100 transition-opacity font-bold pointer-events-none"
                      strokeWidth={4}
                    />
                  </div>
                  <span className="text-sm text-zinc-400 group-hover:text-zinc-300 transition-colors">
                    Manter conectado
                  </span>
                </label>
              </Tooltip>
            </div>

            <Tooltip
              text="Clique para acessar o sistema"
              className="w-full"
              spacing="-mb-4"
            >
              <button
                type="submit"
                disabled={loading}
                className="w-full py-4 mt-6 bg-gradient-to-r from-[#efffc8] to-[#ccff33] text-black font-bold text-lg rounded-2xl shadow-[0_0_30px_rgba(217,249,157,0.4)] hover:shadow-[0_0_40px_rgba(217,249,157,0.6)] hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100 transition-all duration-300 select-none"
              >
                {loading ? "Entrando..." : "Entrar"}
              </button>
            </Tooltip>

            <div className="mt-8 text-sm text-zinc-500 flex items-center justify-center gap-2 select-none">
              <span>Está sem acesso?</span>
              <Tooltip
                text="Contatar suporte para criar conta"
                className="w-fit"
              >
                <button
                  type="button"
                  onClick={() => setShowRegisterModal(true)}
                  className="text-[#d9f99d] hover:text-[#c4f07a] transition-colors hover:underline outline-none"
                >
                  Solicite seu cadastro
                </button>
              </Tooltip>
            </div>
          </form>
        </div>
      </div>

      {/* --- FORGOT PASSWORD MODAL --- */}
      {showForgotModal && (
        <div
          className={`
                absolute inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-md p-4 
                transition-opacity duration-500
                ${isForgotClosing ? "opacity-0" : "opacity-100"} 
            `}
        >
          <form
            onSubmit={handleSendRecovery}
            className="bg-[#1a1a1a] border border-zinc-800 rounded-3xl shadow-2xl w-full max-w-md p-8 relative"
            style={{
              animation: isForgotClosing
                ? "modalPopExit 0.5s ease-in forwards"
                : "modalPop 0.5s ease-out forwards",
            }}
          >
            <button
              type="button"
              onClick={closeForgotModal}
              className="absolute top-4 right-4 text-zinc-500 hover:text-white transition-colors"
            >
              <X size={24} />
            </button>

            <div className="mb-6 select-none">
              <h2 className="text-2xl font-bold text-white mb-2">
                Recuperar Senha
              </h2>
              <p className="text-zinc-400 text-sm">
                Digite o email associado à sua conta para receber as instruções
                de recuperação.
              </p>
            </div>

            {forgotError && (
              <div className="flex items-center gap-2 p-3 mb-4 bg-red-500/10 border border-red-500/50 rounded-lg animate-[modalPop_0.3s_ease-out_forwards]">
                <AlertCircle size={18} className="text-red-500 shrink-0" />
                <span className="text-xs text-red-400 font-medium select-none">
                  {forgotError}
                </span>
              </div>
            )}

            <div className="space-y-6">
              <InputField
                id="recovery-email"
                label="Email de recuperação"
                type="email"
                placeholder="seu@email.com"
                value={recoveryEmail}
                onChange={(e) => setRecoveryEmail(e.target.value)}
                icon={Mail}
              />

              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={closeForgotModal}
                  className="flex-1 py-3 text-sm font-bold text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-xl transition-colors border border-transparent hover:border-zinc-700 select-none"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  className="flex-1 py-3 text-sm font-bold text-black bg-[#d9f99d] hover:bg-[#bef264] rounded-xl transition-colors shadow-lg shadow-[#d9f99d]/20 select-none"
                >
                  Enviar Email
                </button>
              </div>
            </div>
          </form>
        </div>
      )}

      {/* --- REQUEST REGISTRATION MODAL --- */}
      {showRegisterModal && (
        <div
          className={`
                absolute inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-md p-4 
                transition-opacity duration-500
                ${isRegisterClosing ? "opacity-0" : "opacity-100"} 
            `}
        >
          <form
            onSubmit={handleSendRegistration}
            className="bg-[#1a1a1a] border border-zinc-800 rounded-3xl shadow-2xl w-full max-w-md p-8 relative"
            style={{
              animation: isRegisterClosing
                ? "modalPopExit 0.5s ease-in forwards"
                : "modalPop 0.5s ease-out forwards",
            }}
          >
            <button
              type="button"
              onClick={closeRegisterModal}
              className="absolute top-4 right-4 text-zinc-500 hover:text-white transition-colors"
            >
              <X size={24} />
            </button>

            <div className="mb-6 select-none">
              <h2 className="text-2xl font-bold text-white mb-2">
                Solicitar Cadastro
              </h2>
              <p className="text-zinc-400 text-sm">
                Informe seu email de contato para enviarmos as instruções de
                cadastro.
              </p>
            </div>

            {registerError && (
              <div className="flex items-center gap-2 p-3 mb-4 bg-red-500/10 border border-red-500/50 rounded-lg animate-[modalPop_0.3s_ease-out_forwards]">
                <AlertCircle size={18} className="text-red-500 shrink-0" />
                <span className="text-xs text-red-400 font-medium select-none">
                  {registerError}
                </span>
              </div>
            )}

            <div className="space-y-6">
              <InputField
                id="register-email"
                label="Email de contato"
                type="email"
                placeholder="seu@email.com"
                value={registerEmail}
                onChange={(e) => setRegisterEmail(e.target.value)}
                icon={Mail}
              />

              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={closeRegisterModal}
                  className="flex-1 py-3 text-sm font-bold text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-xl transition-colors border border-transparent hover:border-zinc-700 select-none"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  className="flex-1 py-3 text-sm font-bold text-black bg-[#d9f99d] hover:bg-[#bef264] rounded-xl transition-colors shadow-lg shadow-[#d9f99d]/20 select-none"
                >
                  Solicitar
                </button>
              </div>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};
