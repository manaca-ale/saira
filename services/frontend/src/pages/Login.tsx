import React, { useState } from "react";
import { User, Lock, Check } from "lucide-react";
import { InputField } from "../components/InputField";
import { useNavigate } from "react-router-dom";

export const Login: React.FC = () => {
  const navigate = useNavigate();

  // --- State Management ---
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [userError, setUserError] = useState(false);
  const [passError, setPassError] = useState(false);

  // --- Event Handlers ---
  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    setUserError(false);
    setPassError(false);

    if (username !== "admin") {
      setUserError(true);
      return;
    }
    if (password !== "12345") {
      setPassError(true);
      return;
    }
    navigate("/dashboard");
  };

  return (
    // --- Main Layout Container ---
    <div className="h-full w-full bg-[#121212] flex items-center justify-center p-4 lg:p-12">
      {/* --- Card Container --- */}
      <div className="w-full max-w-[1400px] h-[85vh] flex flex-row bg-[#121212]">
        {/* --- Left Panel: Visuals --- */}
        <div className="w-24 md:w-[40%] lg:w-1/2 h-full relative rounded-tl-none rounded-tr-[3.5rem] rounded-bl-[3.5rem] rounded-br-none overflow-hidden shrink-0 transition-all duration-300">
          <div className="absolute inset-0 bg-[#eaffb0]"></div>
          <div className="absolute top-[-20%] left-[-20%] w-[80%] h-[80%] bg-[#f7fee7] rounded-full blur-[100px] opacity-80"></div>
          <div className="absolute top-[30%] right-[-10%] w-[70%] h-[70%] bg-[#bef264] rounded-full blur-[80px] mix-blend-multiply opacity-60"></div>
          <div className="absolute bottom-[-10%] left-[10%] w-[60%] h-[60%] bg-[#d9f99d] rounded-full blur-[60px]"></div>
          <div className="absolute inset-0 bg-white/10 backdrop-blur-3xl"></div>
        </div>

        {/* --- Right Panel: Form Section --- */}
        <div className="flex-1 h-full flex flex-col justify-center px-6 md:px-12 lg:px-24 py-12 bg-transparent rounded-r-[3.5rem] overflow-y-auto">
          {/* --- Header Section --- */}
          <div className="mb-10 lg:mb-14">
            <h1 className="text-3xl md:text-4xl lg:text-5xl font-semibold text-white tracking-tight">
              Bem vindo ao <span className="text-[#d9f99d]">SAIRA</span>
            </h1>
          </div>

          {/* --- Login Form --- */}
          <form
            onSubmit={handleLogin}
            className="flex flex-col gap-6 lg:gap-7 max-w-md w-full"
          >
            <InputField
              id="username"
              label="Usuário"
              type="text"
              placeholder="nome-user"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              icon={User}
              error={userError}
              errorMessage="Usuário Inválido!"
            />

            {/* --- Password Field Group --- */}
            <div className="space-y-1">
              <InputField
                id="password"
                label="Senha"
                type="password"
                placeholder="........."
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                icon={Lock}
                error={passError}
                errorMessage="Senha inválida!"
              />

              <div className="flex justify-end pt-2">
                <a
                  href="#"
                  className="text-sm text-zinc-400 hover:text-[#d9f99d] transition-colors"
                >
                  Esqueceu a senha?
                </a>
              </div>
            </div>

            {/* --- Checkbox Option --- */}
            <div className="flex items-center mt-1">
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
            </div>

            {/* --- Submit Action --- */}
            <button
              type="submit"
              className="
                w-full py-4 mt-6
                bg-gradient-to-r from-[#efffc8] to-[#ccff33]
                text-black font-bold text-lg rounded-2xl
                shadow-[0_0_30px_rgba(217,249,157,0.4)]
                hover:shadow-[0_0_40px_rgba(217,249,157,0.6)]
                hover:scale-[1.02] active:scale-[0.98]
                transition-all duration-300
              "
            >
              Entrar
            </button>

            {/* --- Footer Links --- */}
            <div className="mt-8 text-center text-sm text-zinc-500">
              Está sem acesso?{" "}
              <a
                href="#"
                className="text-[#d9f99d] hover:text-[#c4f07a] transition-colors ml-1 hover:underline"
              >
                Solicite seu cadastro
              </a>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
};
